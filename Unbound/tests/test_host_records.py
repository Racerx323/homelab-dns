"""Offline production transaction, HA gate and approval contracts; no host contact."""
import base64
import copy
import hashlib
import fcntl
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = load('records', 'apply-host-records.py')
v = load('verify', 'verify-host-records.py')
d = load('dispatch', 'dispatch-host-records.py')
ACTIVE = {u: {'ActiveState': 'active', 'SubState': 'running', 'MainPID': '123', 'Result': 'success'} for u in m.SERVICES}
CHECK = {'argv': ['/usr/bin/dig', '@127.0.0.1', '-p', '5335', 'ntp1.local.theama.co.', 'A'],
         'expected': {'rcode': 'NOERROR', 'answers': [['ntp1.local.theama.co.', 'A', '10.1.0.51']]}}


def checks():
    return [copy.deepcopy(CHECK), dict(copy.deepcopy(CHECK), argv=['/usr/bin/dig', '@::1', '-p', '5335', 'ntp1.local.theama.co.', 'A'])]


class Files(unittest.TestCase):
    def test_atomic_install_and_directory_fsync(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'live.conf'; p.write_bytes(b'old')
            old = p.open('rb')
            with patch.object(m, 'sync_directory', wraps=m.sync_directory) as sync:
                m.install(p, b'new', os.getuid(), os.getgid(), 0o640)
                sync.assert_called_once_with(p.parent)
            self.assertEqual(old.read(), b'old'); old.close()
            self.assertEqual(p.read_bytes(), b'new'); self.assertEqual(p.stat().st_mode & 0o777, 0o640)
            self.assertEqual(list(p.parent.iterdir()), [p])

    def test_failed_replace_preserves_original(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'live'; p.write_bytes(b'old')
            with patch.object(m.os, 'replace', side_effect=OSError('replace failed')):
                with self.assertRaises(OSError): m.install(p, b'new', os.getuid(), os.getgid(), 0o600)
            self.assertEqual(p.read_bytes(), b'old'); self.assertEqual(list(p.parent.iterdir()), [p])

    def test_post_rename_fsync_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'live'; p.write_bytes(b'old')
            with patch.object(m, 'sync_directory', side_effect=OSError('directory fsync failed')):
                with self.assertRaises(OSError): m.install(p, b'new', os.getuid(), os.getgid(), 0o600)
            self.assertEqual(p.read_bytes(), b'new')

    def test_symlink_and_hash_drift_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'live'; p.write_bytes(b'old'); link = Path(folder)/'link'; link.symlink_to(p)
            for path, digest in [(p, '0'*64), (link, m.sha(b'old'))]:
                with self.assertRaises(RuntimeError): m.verify_file(path, digest)

    def test_last_moment_destination_drift_preserved_before_rename(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'zone.conf'; path.write_bytes(b'foreign'); path.chmod(0o644)
            expected = {'sha256': m.sha(b'old'), 'uid': os.getuid(), 'gid': os.getgid(), 'mode': 0o644}
            with self.assertRaisesRegex(RuntimeError, 'file_drift'):
                m.install(path, b'new', os.getuid(), os.getgid(), 0o644, expected=expected)
            self.assertEqual(path.read_bytes(), b'foreign')
            self.assertEqual(list(path.parent.iterdir()), [path])

    def test_exclusive_backup_file_rejects_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)/'backup'; m.durable_file(p, b'old')
            with self.assertRaises(FileExistsError): m.durable_file(p, b'new')
            self.assertEqual(p.read_bytes(), b'old')

    def test_backup_corruption_stops_before_restoration(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); backup = root/'backup'; backup.mkdir(mode=0o700)
            (backup/'original.conf').write_bytes(b'corrupted'); dest = root/'live'; dest.write_bytes(b'new')
            with patch.object(m, 'backup_check'), patch.object(m, 'command') as cmd:
                with self.assertRaises(RuntimeError): m.restore({}, dest, backup, {'sha256': m.sha(b'old')}, m.sha(b'new'))
                cmd.assert_not_called()
            self.assertEqual(dest.read_bytes(), b'new')

    def test_live_lock_blocks_overlapping_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); lock = root/'.zone-deployment.lock'
            with lock.open('w') as held:
                fcntl.flock(held, fcntl.LOCK_EX)
                payload = {'operation': {'policy': m.POLICY, 'target_path': str(root/'zone.conf')}, 'phase': 'apply'}
                with patch.object(m.os, 'geteuid', return_value=0), patch.object(m, 'transaction') as tx:
                    with self.assertRaises(BlockingIOError): m.main(payload)
                    tx.assert_not_called()


class Health(unittest.TestCase):
    def test_local_accepts_both_or_no_vips_after_failover(self):
        for owned in ([], sorted(m.VIPS)):
            with patch.object(m, 'sample', return_value={'services': ACTIVE, 'vips': owned}), patch.object(m, 'event'):
                self.assertEqual(m.health({})['vips'], owned)

    def test_paired_gate_accepts_either_owner(self):
        rows = [{'hostname': 'a', 'services': ACTIVE, 'dns_passed': True, 'vips': sorted(m.VIPS)},
                {'hostname': 'b', 'services': ACTIVE, 'dns_passed': True, 'vips': []}]
        self.assertEqual(m.cluster_gate(rows), 'a')
        rows[0]['vips'], rows[1]['vips'] = rows[1]['vips'], rows[0]['vips']
        self.assertEqual(m.cluster_gate(rows), 'b')

    def test_paired_gate_rejects_split_duplicate_lost_peer_and_bad_dns(self):
        base = [{'hostname': 'a', 'services': ACTIVE, 'dns_passed': True, 'vips': sorted(m.VIPS)},
                {'hostname': 'b', 'services': ACTIVE, 'dns_passed': True, 'vips': []}]
        for mode in ('split', 'duplicate', 'missing', 'failed', 'dns', 'same-host'):
            rows = copy.deepcopy(base)
            if mode == 'split': rows[0]['vips'] = ['10.1.0.55']; rows[1]['vips'] = ['fd36:5aa8:6971:1::55']
            if mode == 'duplicate': rows[1]['vips'] = sorted(m.VIPS)
            if mode == 'missing': rows[0]['vips'] = []
            if mode == 'failed': rows[1]['services']['unbound']['ActiveState'] = 'failed'
            if mode == 'dns': rows[1]['dns_passed'] = False
            if mode == 'same-host': rows[1]['hostname'] = 'a'
            with self.subTest(mode=mode), self.assertRaises(RuntimeError): m.cluster_gate(rows)

    def test_transient_activation_converges_two_samples(self):
        clock = [0]; transient = copy.deepcopy(ACTIVE); transient['unbound']['ActiveState'] = 'activating'
        rows = [{'services': transient, 'vips': []}, {'services': ACTIVE, 'vips': []}, {'services': ACTIVE, 'vips': []}]
        with patch.object(m, 'sample', side_effect=rows), patch.object(m, 'event'), patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(m.time, 'sleep', side_effect=lambda n: clock.__setitem__(0, clock[0]+n)):
            m.health({}, settle=True)
        self.assertEqual(clock[0], 2)

    def test_health_does_not_accept_a_late_successful_sample(self):
        clock = [0]
        def delayed(deadline):
            clock[0] = deadline+1
            return {'services': ACTIVE, 'vips': []}
        with patch.object(m, 'sample', side_effect=delayed), patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, 'health_sample_deadline'): m.health({}, settle=True)

    def test_permanent_transition_is_bounded(self):
        clock = [0]; states = copy.deepcopy(ACTIVE); states['unbound']['ActiveState'] = 'activating'
        with patch.object(m, 'sample', return_value={'services': states, 'vips': []}), patch.object(m, 'event'), patch.object(m.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(m.time, 'sleep', side_effect=lambda n: clock.__setitem__(0, clock[0]+n)):
            with self.assertRaisesRegex(RuntimeError, 'convergence_timeout'): m.health({}, settle=True)
        self.assertEqual(clock[0], 30)


class Restart(unittest.TestCase):
    def test_full_restart_order_with_direct_dns_before_pihole(self):
        events = []
        def cmd(argv, **kwargs):
            events.append(argv)
            return 'ActiveState=active\nSubState=running\nMainPID=123\nResult=success\n'
        node = {'before_checks': checks(), 'candidate_checks': checks()}
        with patch.object(m, 'command', side_effect=cmd), patch.object(m, 'check_dns', side_effect=lambda *args: events.append('dns')), patch.object(m, 'health'):
            m.restart_services(node)
        self.assertEqual(events[0], ['systemctl', 'restart', 'unbound.service'])
        self.assertEqual(events[-1], ['/usr/local/bin/pihole', 'restartdns'])
        self.assertEqual(events[2:-1], ['dns', 'dns'])
        self.assertNotIn('reload', json.dumps(events))

    def test_unbound_failure_or_bad_direct_answer_prevents_pihole_restart(self):
        for bad_state in (True, False):
            events = []
            def cmd(argv, **kwargs):
                events.append(argv)
                return 'ActiveState=failed\n' if bad_state else 'ActiveState=active\nSubState=running\nMainPID=123\nResult=success\n'
            with patch.object(m, 'command', side_effect=cmd), patch.object(m, 'check_dns', side_effect=RuntimeError('bad dns')):
                with self.assertRaises(RuntimeError): m.restart_services({'candidate_checks': checks()})
            self.assertNotIn(['/usr/local/bin/pihole', 'restartdns'], events)

    def test_dns_rcode_and_exact_answers_including_empty(self):
        with patch.object(m, 'command', return_value=';; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 1\nntp1.local.theama.co. 60 IN A 10.1.0.51\n'):
            m.check_dns(CHECK, {'127.0.0.1'})
        empty = dict(CHECK, expected={'rcode': 'NXDOMAIN', 'answers': []})
        with patch.object(m, 'command', return_value=';; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 1\n'):
            m.check_dns(empty, {'127.0.0.1'})
            with self.assertRaises(RuntimeError): m.check_dns(CHECK, {'127.0.0.1'})
        with patch.object(m, 'command', return_value=';; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 1\n'):
            with self.assertRaises(RuntimeError): m.check_dns(empty, {'127.0.0.1'})


class Transactions(unittest.TestCase):
    def run_transaction(self, failure=None, recovery_failure=False, interruption=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); dest = root/'live.conf'; dest.write_bytes(b'old'); dest.chmod(0o644)
            backup = root/'backup'; before = {'sha256': m.sha(b'old'), 'uid': os.getuid(), 'gid': os.getgid(), 'mode': 0o644}
            node = {'hostname': 'fixture', 'boot_id': 'fixture-boot', 'backup_directory': str(backup), 'binaries': {},
                    'files': {str(dest): before, '/etc/unbound/unbound.conf': {'sha256': 'unused'}},
                    'expanded_sha256': m.sha(b'expanded'), 'before_checks': checks(), 'candidate_checks': checks()}
            op = {'policy': m.POLICY, 'target_path': str(dest), 'candidate_sha256': m.sha(b'new'), 'nodes': {'secondary': node}}
            payload = {'operation': op, 'node': 'secondary', 'phase': 'apply', 'candidate': base64.b64encode(b'new').decode(), 'expanded': base64.b64encode(b'expanded').decode()}
            verify = m.verify_file; original_read = Path.read_text; restarts = []; commands = []; states = []
            def read(path, *args, **kwargs):
                return 'fixture-boot' if str(path) == '/proc/sys/kernel/random/boot_id' else original_read(path, *args, **kwargs)
            def cmd(argv, **kwargs):
                commands.append(argv)
                if argv == ['hostname']: return 'fixture'
                if argv[0] == 'journalctl': return '-- cursor: fixture\n'
                return ''
            def restart(node, restoring=False):
                restarts.append(restoring)
                if interruption and not restoring: raise KeyboardInterrupt()
                if failure and not restoring:
                    if failure == 'drift': dest.write_bytes(b'foreign')
                    raise RuntimeError(failure)
                if restoring and recovery_failure: raise RuntimeError('recovery failure')
            def state(path, value):
                # Offline user owns the fixture; native root run tests actual root metadata.
                m.install(path/'state.json', (json.dumps(value)+'\n').encode(), os.getuid(), os.getgid(), 0o600)
                states.append(value['phase'])
            with patch.object(m.os, 'geteuid', return_value=0), patch.object(Path, 'read_text', read), patch.object(Path, 'glob', return_value=[dest]), patch.object(m, 'verify_file', side_effect=lambda p, h: b'' if str(p) == '/etc/unbound/unbound.conf' else verify(p, h)), patch.object(m, 'command', side_effect=cmd), patch.object(m.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')), patch.object(m, 'health'), patch.object(m, 'backup_check'), patch.object(m, 'state_write', side_effect=state), patch.object(m, 'restart_services', side_effect=restart), patch.object(m, 'event'):
                if interruption:
                    with self.assertRaises(KeyboardInterrupt): m.transaction(payload)
                    self.assertEqual(dest.read_bytes(), b'new'); self.assertEqual(states[-1], 'installed')
                    payload['phase'] = 'rollback'; m.transaction(payload)
                elif failure:
                    with self.assertRaisesRegex(RuntimeError, 'rollback_unverified' if recovery_failure or failure == 'drift' else failure): m.transaction(payload)
                else:
                    m.transaction(payload)
                    self.assertEqual(dest.read_bytes(), b'new'); self.assertEqual(states[-1], 'applied_requires_cluster_dns_gate')
                    payload['phase'] = 'rollback'; m.transaction(payload)
            expected = b'foreign' if failure == 'drift' else b'old'
            self.assertEqual(dest.read_bytes(), expected); self.assertEqual((backup/'original.conf').read_bytes(), b'old')
            self.assertNotIn(['unbound-control', 'reload'], commands)
            return restarts, states

    def test_apply_then_explicit_rollback(self): self.assertEqual(self.run_transaction()[0], [False, True])
    def test_restart_failure_restores_and_restarts_both(self): self.assertEqual(self.run_transaction('restart failure')[0], [False, True])
    def test_foreign_destination_preserved_and_recovery_held(self): self.run_transaction('drift')
    def test_recovery_failure_not_accepted(self): self.run_transaction('restart failure', recovery_failure=True)
    def test_interruption_retains_backup_and_explicit_recovery(self): self.run_transaction(interruption=True)
    def test_old_policy_rejected_before_commands(self):
        with patch.object(m, 'command') as cmd:
            with self.assertRaisesRegex(RuntimeError, 'new_restart'): m.main({'operation': {}})
            cmd.assert_not_called()


class Controller(unittest.TestCase):
    def test_owner_change_converges_and_uses_serving_nodes_state(self):
        clock = [0]; count = [0]; checked = []
        op = {'nodes': {'secondary': {'hostname': 's'}, 'primary': {'hostname': 'p'}},
              'vip_before_checks': ['old'], 'vip_candidate_checks': ['new']}
        def fetch(root, operation, label, desired, timeout):
            count[0] += 1
            owner = 'p' if count[0] <= 2 else 's'
            return {'hostname': 's' if label == 'secondary' else 'p', 'services': ACTIVE, 'dns_passed': True,
                    'vips': sorted(m.VIPS) if (label == 'secondary') == (owner == 's') else []}
        with patch.object(v.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(v.time, 'sleep', side_effect=lambda n: clock.__setitem__(0, clock[0]+n)), patch.object(m, 'check_dns', side_effect=lambda c, *a, **k: checked.append(c)):
            result = v.paired_gate(Path('.'), op, m, {'secondary': 'candidate', 'primary': 'before'}, fetch)
        self.assertEqual(result['owner'], 's'); self.assertEqual(checked, ['old', 'new', 'new'])

    def test_dispatch_requires_fresh_gate_and_consumes_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)/'bundle'; root.mkdir()
            op = {'policy': m.POLICY, 'prepared_epoch': int(time.time())-1, 'expires_epoch': int(time.time())+86400,
                  'nodes': {'secondary': {'ssh': 'pi@192.0.2.53', 'host_key_alias': 'fixture'}}}
            content = {'node.py': b'# fixture', 'dispatch.py': b'# fixture', 'verify.py': b'# fixture', 'operation.json': json.dumps(op).encode(),
                       'known_hosts': b'fixture', 'candidate.conf': b'new', 'secondary-candidate-expanded.conf': b'expanded'}
            for name, raw in content.items(): (root/name).write_bytes(raw)
            index = ''.join(hashlib.sha256(raw).hexdigest()+'  '+name+'\n' for name, raw in content.items()).encode()
            (root/'SHA256SUMS').write_bytes(index); digest = hashlib.sha256(index).hexdigest()
            with patch.object(d.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run:
                with self.assertRaises(FileNotFoundError): d.main(root, digest, 'secondary', 'apply')
                run.assert_not_called()
                gate = root.parent/'gate-before.json'; gate.write_text(json.dumps({'accepted': True, 'sha256': digest, 'recorded_epoch': time.time()-121}))
                with self.assertRaisesRegex(RuntimeError, 'fresh_paired_gate'): d.main(root, digest, 'secondary', 'apply')
                gate.write_text(json.dumps({'accepted': True, 'sha256': digest, 'recorded_epoch': time.time()}))
                self.assertEqual(d.main(root, digest, 'secondary', 'apply'), 0)
                with self.assertRaises(FileExistsError): d.main(root, digest, 'secondary', 'apply')
                self.assertEqual(run.call_count, 1)
                argv = run.call_args.args[0]
                self.assertIn('StrictHostKeyChecking=yes', argv); self.assertIn('HostKeyAlias=fixture', argv)

    def test_permanent_cluster_split_times_out_without_acceptance(self):
        clock = [0]
        op = {'nodes': {'secondary': {'hostname': 's'}, 'primary': {'hostname': 'p'}}}
        def fetch(root, operation, label, desired, timeout):
            return {'hostname': label, 'services': ACTIVE, 'dns_passed': True, 'vips': sorted(m.VIPS)}
        with patch.object(v.time, 'monotonic', side_effect=lambda: clock[0]), patch.object(v.time, 'sleep', side_effect=lambda n: clock.__setitem__(0, clock[0]+n)):
            with self.assertRaisesRegex(RuntimeError, 'cluster_convergence_timeout'):
                v.paired_gate(Path('.'), op, m, {'secondary': 'before', 'primary': 'before'}, fetch)
        self.assertEqual(clock[0], 180)

    def test_snapshot_rejects_wrong_authenticated_result_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'node.py').write_bytes(b'# fixture')
            op = {'target_path': '/zone', 'candidate_sha256': 'new', 'nodes': {'secondary': {
                'hostname': 'expected', 'boot_id': 'boot', 'files': {'/zone': {'sha256': 'old'}},
                'ssh': 'pi@192.0.2.53', 'host_key_alias': 'fixture'}}}
            row = subprocess.CompletedProcess([], 0, json.dumps({'hostname': 'wrong', 'boot_id': 'boot', 'zone_sha256': 'old'}).encode(), b'')
            with patch.object(v.subprocess, 'run', return_value=row):
                with self.assertRaisesRegex(RuntimeError, 'snapshot_identity'): v.snapshot(root, op, 'secondary', 'before')

    def test_wrong_hash_rejected_before_target_contact(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'SHA256SUMS').write_bytes(b'')
            with patch.object(d.subprocess, 'run') as run:
                with self.assertRaisesRegex(RuntimeError, 'authorization_hash'): d.main(root, '0'*64, 'primary', 'apply')
                run.assert_not_called()


class NtpCandidate(unittest.TestCase):
    def test_exact_forward_reverse_native_identity(self):
        text = (ROOT/'configs/pihole-local-zone.conf').read_text()
        records = re.findall(r'^\s*local-data:\s+"ntp1\.local\.theama\.co\. IN (A|AAAA) ([^"\s]+)"\s*$', text, re.M)
        self.assertCountEqual(records, [('A', '10.1.0.51'), ('AAAA', 'fd36:5aa8:6971:1::51')])
        self.assertIsNone(ipaddress.ip_address(dict(records)['AAAA']).ipv4_mapped)
        for address in ('10.1.0.51', 'fd36:5aa8:6971:1::51'):
            self.assertEqual(re.findall(r'^\s*local-data-ptr:\s+"'+re.escape(address)+r' ([^"\s]+)"\s*$', text, re.M), ['ntp1.local.theama.co.'])
        self.assertNotIn('ntp2.local.theama.co', text)


if __name__ == '__main__': unittest.main()
