"""Offline scope, immutable input, candidate and one-use readiness contracts."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
LOADER = importlib.util.spec_from_file_location('readiness', ROOT/'scripts/inspect-ntp-dns-readiness.py')
d = importlib.util.module_from_spec(LOADER); LOADER.loader.exec_module(d)
BASE = b'''server:
    local-zone: "local.theama.co." static
    local-data: "ntp1.local.theama.co. IN A 10.1.0.51"
    local-data: "unrelated.local.theama.co. IN A 10.1.2.100"
    local-data-ptr: "10.1.0.51 ntp1.local.theama.co."
'''


class ReadinessTests(unittest.TestCase):
    def test_qualification_scope_boot_and_review_binding(self):
        def qualify(spec):
            spec['qualification'] = True
            spec['target'] = d.expected_target('dns53', True)
            spec['operation_id'] = 'ntp1-dns53-controls-qualification-20261020-v1'
        raw, _, spec = self.bundle('dns53', mutate=qualify)
        self.assertEqual(d.unpack(raw, d.sha(raw))[0]['target']['boot_id'], d.CONTROL_BOOTS['dns53'])
        self.assertIn('No reload, restart', d.review(spec))
        def wrong_boot(spec):
            qualify(spec); spec['target']['boot_id'] = 'other'
        raw, _, _ = self.bundle('dns53', mutate=wrong_boot)
        with self.assertRaises(ValueError): d.unpack(raw, d.sha(raw))
        with self.assertRaises(ValueError): d.expected_target('ntp', True)

    def test_control_projection_preserves_path_semantics_without_config_secrets(self):
        raw = b'REMOTE_HOST="10.1.0.54"\nPASSWORD="must-not-export"\nAPI_KEY="must-not-export"\nsource=/etc/unbound\nrsync --exclude=/etc/pihole/custom.list --delete\n'
        projection = d.control_projection(raw)
        self.assertNotIn('must-not-export', json.dumps(projection))
        self.assertNotIn('source_lines', projection)
        self.assertIn('/etc/unbound', projection['paths'])
        self.assertIn('--exclude=/etc/pihole/custom.list', projection['rsync_options'])
        code = d.control_projection(raw, code=True)
        self.assertNotIn('must-not-export', json.dumps(code))
        self.assertEqual(code['source_lines'][1]['text'], '[REDACTED]')

    def test_qualification_does_not_dispatch_readiness_or_native_controls(self):
        spec = {'mode': 'dns53', 'qualification': True, 'operation_id': 'fixture',
                'target': d.expected_target('dns53', True)}
        with patch.object(d, 'host_identity', return_value={'same': True}), patch.object(d, 'collect_controls') as controls, patch.object(d, 'collect_dns') as dns, patch.object(d, 'collect_ntp') as ntp:
            self.assertTrue(d.collect(spec)['capture_complete'])
            controls.assert_called_once(); dns.assert_not_called(); ntp.assert_not_called()

    def test_control_read_rejects_out_of_scope_and_arbitrary_symlinks(self):
        for name in ('/etc/shadow', '/home/pi/.ssh/id_ed25519', '/etc/gravity-sync/other.conf'):
            with self.assertRaises(ValueError): d.control_read(name)

    def test_controls_collects_sources_without_executing_controls_and_detects_drift(self):
        for drift, binary_unavailable in ((False, False), (True, False), (False, True)):
            result = {'findings': []}
            calls = []
            def probe(argv, **kwargs):
                calls.append(argv)
                return {'returncode': 0, 'stdout': '# unit source\n', 'stderr': ''}
            addresses = json.dumps([{'addr_info': [{'local': d.VIPS[0]}, {'local': d.VIPS[1]}]}])
            meta = {'sha256': 'same'}
            def protected_read(name):
                if name == '/usr/sbin/unbound-control' and binary_unavailable:
                    raise ValueError('protected bounded regular file required')
                return b'config', meta
            values = [('active' if not drift or n < 3 else 'changed') for n in range(6)]
            with patch.object(d, 'unit', side_effect=values), patch.object(d, 'required', return_value=addresses), patch.object(d, 'read_file', side_effect=protected_read), patch.object(d, 'config_graph', return_value=(b'control-enable: yes\n', {}, [])), patch.object(d, 'control_read', return_value=(b'PASSWORD=do-not-export\nrestartDNS() { service pihole-FTL restart; }\n', meta)), patch.object(d, 'sync_projection', return_value={'units': {}}), patch.object(d.glob, 'glob', return_value=[]), patch.object(d, 'probe', side_effect=probe):
                if drift:
                    with self.assertRaises(ValueError): d.collect_controls({}, result)
                else:
                    d.collect_controls({}, result)
                    if binary_unavailable:
                        self.assertEqual(result['unbound_control_binary']['unavailable'], 'ValueError')
                        self.assertTrue(result['control_units'])
                        self.assertTrue(result['services_after'])
                    self.assertNotIn('do-not-export', json.dumps(result))
                    self.assertEqual(result['remote_control_settings'], ['control-enable: yes'])
                    self.assertTrue(all(result['vip_ownership'].values()))
            self.assertTrue(calls)
            self.assertTrue(all(argv[:2] == ['/usr/bin/systemctl', 'cat'] or argv[:2] == ['/usr/bin/systemctl', 'show'] for argv in calls))

    def test_control_projection_never_exports_raw_cron_command_or_environment(self):
        raw = b'30 5 * * * root curl https://private.invalid/secret --password dont-export\nEnvironment=TOKEN=dont-export\n'
        config = d.control_projection(raw)
        self.assertNotIn('dont-export', json.dumps(config))
        self.assertEqual(config['schedule_prefixes'], [{'line': 1, 'schedule': '30 5 * * *'}])
        code = d.control_projection(raw, code=True)
        self.assertTrue(all(line['text'] == '[REDACTED]' for line in code['source_lines']))

    def test_candidate_preserves_live_data_and_adds_only_two_records_idempotently(self):
        result, lines = d.ntp_candidate(BASE)
        self.assertTrue(result.startswith(BASE)); self.assertEqual(len(lines), 2)
        self.assertNotIn('::83', result.decode())
        self.assertIn('ntp1.local.theama.co. IN AAAA fd36:5aa8:6971:1::51', result.decode())
        self.assertEqual(d.ntp_candidate(result), (result, []))

    def test_real_repository_candidate_includes_namespace_policy_and_exact_records(self):
        raw = (ROOT/'configs/pihole-local-zone.conf').read_bytes()
        self.assertEqual(d.ntp_candidate(raw), (raw, []))

    def test_conflicts_duplicates_missing_ipv4_and_unsupported_fragment_hold(self):
        candidate, _ = d.ntp_candidate(BASE)
        for raw in (candidate.replace(b'IN AAAA fd36:5aa8:6971:1::51', b'IN AAAA fd36:5aa8:6971:1::52'),
                    candidate+b'local-data: "ntp1.local.theama.co. IN AAAA fd36:5aa8:6971:1::51"\n',
                    BASE.replace(b'IN A 10.1.0.51', b'IN A 10.1.0.52'), BASE+b'include: "/etc/private.conf"\n',
                    BASE+b'local-data: "secret.local.theama.co. IN TXT confidential"\n',
                    candidate.replace(b'::51 ntp1.local.theama.co.', b'::51 wrong.local.theama.co.')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                d.ntp_candidate(raw)

    def test_native_address_checks_reject_missing_mapped_wrong_prefix_and_dad(self):
        rows = [{'addr_info': [{'local': d.ADDRESSES[0], 'prefixlen': 22}, {'local': d.ADDRESSES[1], 'prefixlen': 64}]}]
        self.assertTrue(all(d.address_checks(rows).values()))
        for change in ({'tentative': True}, {'dadfailed': True}, {'prefixlen': 128}, {'local': '::ffff:10.1.0.51'}):
            bad = copy.deepcopy(rows); bad[0]['addr_info'][1].update(change)
            self.assertFalse(d.address_checks(bad)['6'])

    def test_graph_expands_only_approved_files_and_substitutes_exact_fragment(self):
        main = b'include: "/etc/unbound/unbound.conf.d/*.conf"\n'
        values = {'/etc/unbound/unbound.conf': main, d.FRAGMENT: BASE}
        def read(path):
            raw = values[str(path)]; return raw, {'size': len(raw), 'sha256': d.sha(raw)}
        with patch.object(d, 'read_file', side_effect=read), patch.object(d.glob, 'glob', return_value=[d.FRAGMENT]):
            expanded, files, edges = d.config_graph()
            candidate, _ = d.ntp_candidate(BASE)
            proposed, _, _ = d.config_graph(replacement=candidate)
        self.assertEqual(expanded, BASE); self.assertEqual(proposed, candidate)
        self.assertEqual(len(files), 2); self.assertEqual(edges[0]['child'], d.FRAGMENT)

    def test_graph_rejects_external_includes_cycles_and_unsupported_contexts(self):
        for raw in (b'include: "/etc/shadow"\n', b'include-toplevel: "/etc/unbound/a.conf"\n',
                    b'include: "/etc/unbound/unbound.conf"\n'):
            with patch.object(d, 'read_file', return_value=(raw, {'size': len(raw)})), patch.object(d.glob, 'glob', return_value=['/etc/unbound/unbound.conf']):
                with self.assertRaises(ValueError): d.config_graph()

    def test_pure_root_toplevel_includes_preserve_sections(self):
        main = b'include-toplevel: "/etc/unbound/unbound.conf.d/*.conf"\n'
        values = {'/etc/unbound/unbound.conf': main, d.FRAGMENT: BASE}
        def read(path):
            raw = values[str(path)]; return raw, {'size': len(raw), 'sha256': d.sha(raw)}
        with patch.object(d, 'read_file', side_effect=read), patch.object(d.glob, 'glob', return_value=[d.FRAGMENT]):
            self.assertEqual(d.config_graph()[0], BASE)

    def bundle(self, mode='ntp', mutate=None, extra=False):
        files = {'runner.py': (ROOT/'scripts/inspect-ntp-dns-readiness.py').read_bytes(),
                 'helper.py': b'# helper fixture\n', 'tests.py': Path(__file__).read_bytes(),
                 'candidate.conf': d.ntp_candidate(BASE)[0], 'known_hosts': b'fixture key\n'}
        now = int(time.time())
        spec = {'mode': mode, 'target': copy.deepcopy(d.TARGETS[mode]), 'operation_id': 'ntp1-'+('address' if mode == 'ntp' else mode)+'-readiness-20261020-v1',
                'prepared_epoch': now, 'expires_epoch': now+86400,
                'members': {name: d.sha(raw) for name, raw in files.items()}}
        if mutate: mutate(spec)
        files.update({'spec.json': d.encoded(spec), 'review.md': d.review(spec).encode()})
        if extra: files['unexpected'] = b'x'
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as archive:
            for name, raw in files.items():
                item = tarfile.TarInfo(name); item.size = len(raw); archive.addfile(item, io.BytesIO(raw))
        return buffer.getvalue(), files, spec

    def test_closed_archive_target_expiry_integrity_and_review_binding(self):
        raw, _, _ = self.bundle(); d.unpack(raw, d.sha(raw))
        for mutate in (lambda s: s['target'].update(user='other'), lambda s: s.update(prepared_epoch=1, expires_epoch=86401),
                       lambda s: s['members'].update({'helper.py': 'wrong'})):
            raw, _, _ = self.bundle(mutate=mutate)
            with self.assertRaises(ValueError): d.unpack(raw, d.sha(raw))
        raw, _, _ = self.bundle(extra=True)
        with self.assertRaises(ValueError): d.unpack(raw, d.sha(raw))
        raw, _, _ = self.bundle()
        with self.assertRaises(ValueError): d.unpack(raw, 'wrong')

    def execute_fixture(self, mode, mutate_input=False):
        raw, files, spec = self.bundle(mode)
        helper = MagicMock()
        capture = {'operation_id': spec['operation_id'], 'spec_sha256': d.sha(d.encoded(spec)),
                   'capture_complete': True, 'identity_before': 'same', 'identity_after': 'same',
                   'service_before': 'same', 'service_after': 'same'}
        helper.bounded.side_effect = lambda *a, **k: {'returncode': 0, 'stdout': json.dumps(capture), 'stderr': ''}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name, value in files.items(): d.write(directory/name, value)
            d.write(directory/'inspection.tar', raw)
            if mutate_input: (directory/'helper.py').write_bytes(b'changed')
            with patch.object(d, 'load_helper', return_value=helper) as loader:
                if mutate_input:
                    with self.assertRaises(ValueError): d.execute(directory, d.sha(raw))
                    loader.assert_not_called(); return helper
                result = d.execute(directory, d.sha(raw)); self.assertTrue(result['capture_complete'])
                with self.assertRaises(FileExistsError): d.execute(directory, d.sha(raw))
        return helper

    def test_ntp_two_planned_family_sessions_and_exclusive_receipt(self):
        helper = self.execute_fixture('ntp')
        self.assertEqual(helper.bounded.call_count, 2)
        for call, family in zip(helper.bounded.call_args_list, (4, 6)):
            argv = call.args[0]
            self.assertIn('-'+str(family), argv); self.assertIn('StrictHostKeyChecking=yes', argv)
            self.assertIn('HostKeyAlias=10.1.0.137', argv)
            self.assertEqual(argv[-2], 'ama@'+d.ADDRESSES[family == 6])

    def test_dns_node_does_not_progress_to_peer(self):
        helper = self.execute_fixture('dns54')
        self.assertEqual(helper.bounded.call_count, 1)
        self.assertEqual(helper.bounded.call_args.args[0][-2], 'pi@10.1.0.54')

    def test_altered_helper_rejected_before_import_or_ssh(self):
        helper = self.execute_fixture('dns53', mutate_input=True)
        helper.bounded.assert_not_called()

    def test_dns_transport_timeout_consumes_receipt_without_contacting_peer(self):
        raw, files, _ = self.bundle('dns53')
        helper = MagicMock(); helper.bounded.return_value = {'returncode': None, 'error': 'command deadline exceeded', 'stdout': '', 'stderr': ''}
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            for name, value in files.items(): d.write(directory/name, value)
            d.write(directory/'inspection.tar', raw)
            with patch.object(d, 'load_helper', return_value=helper):
                self.assertFalse(d.execute(directory, d.sha(raw))['capture_complete'])
                with self.assertRaises(FileExistsError): d.execute(directory, d.sha(raw))
        self.assertEqual(helper.bounded.call_count, 1)

    def test_sync_hints_never_export_configuration_secret_values(self):
        raw = b'password=DO_NOT_EXPORT\nsource=/etc/unbound\n'
        with patch.object(d, 'read_file', return_value=(raw, {'sha256': d.sha(raw)})), patch.object(d, 'probe', return_value={'returncode': 0, 'stdout': '', 'stderr': ''}):
            result = d.sync_projection()
        self.assertNotIn('DO_NOT_EXPORT', json.dumps(result))
        self.assertFalse(result['complete_writer_proof'])

    def test_queries_are_exact_fixed_records_transports_and_single_attempt(self):
        with patch.object(d, 'probe', return_value={}) as probe:
            d.dns_queries(d.TARGETS['dns53']['addresses'])
        self.assertEqual(probe.call_count, 24)
        for call in probe.call_args_list:
            argv = call.args[0]
            self.assertIn('+tries=1', argv); self.assertIn('+ignore', argv)
            self.assertIn(argv[5], (d.NAME, *( __import__('ipaddress').ip_address(a).reverse_pointer+'.' for a in d.ADDRESSES)))

    def dns_fixture(self, vip_change=False):
        def read(path):
            if str(path) == d.FRAGMENT: return BASE, {'size': len(BASE), 'sha256': d.sha(BASE)}
            raise FileNotFoundError()
        proposed = d.ntp_candidate(BASE)[0]
        graph = (BASE, {d.FRAGMENT: {'metadata': read(d.FRAGMENT)[1]}}, [{'parent': '/etc/unbound/unbound.conf', 'child': d.FRAGMENT}])
        after = json.dumps([{'addr_info': [{'local': d.VIPS[0]}]}]) if vip_change else '[]'
        with patch.object(d, 'unit', return_value='ActiveState=active\n'), patch.object(d, 'required', side_effect=['[]', after]), patch.object(d, 'read_file', side_effect=read), patch.object(d, 'config_graph', side_effect=[graph, (proposed, graph[1], graph[2]), graph]), patch.object(d, 'probe', return_value={'returncode': 0, 'stdout': '', 'stderr': ''}) as probe, patch.object(d, 'dns_queries', return_value=[]), patch.object(d, 'sync_projection', return_value={'complete_writer_proof': False}):
            result = {'findings': []}
            if vip_change:
                with self.assertRaisesRegex(ValueError, 'VIP ownership drift'):
                    d.collect_dns({'target': d.TARGETS['dns53']}, result)
            else:
                d.collect_dns({'target': d.TARGETS['dns53']}, result)
        validation = [call for call in probe.call_args_list if call.args[0] == ['/usr/sbin/unbound-checkconf', '/dev/stdin']]
        self.assertEqual(validation[0].kwargs['payload'], proposed)
        self.assertNotIn(b'::83', validation[0].kwargs['payload'])

    def test_native_candidate_validation_uses_live_fragment_not_whole_repo_candidate(self):
        self.dns_fixture()

    def test_vip_change_stops_capture_even_when_service_pids_are_stable(self):
        self.dns_fixture(vip_change=True)

    def test_trusted_key_selection_uses_local_file_and_rejects_multiple_keys(self):
        for output, success in ((b'alias ssh-ed25519 AAAA\n', True),
                                (b'alias ssh-ed25519 AAAA\nalias ssh-ed25519 BBBB\n', False)):
            row = subprocess.CompletedProcess([], 0, output, b'')
            with patch.object(d.subprocess, 'run', return_value=row) as run:
                if success: self.assertIn(b'ssh-ed25519', d.trusted_key(Path('/local/known_hosts'), 'alias'))
                else:
                    with self.assertRaises(ValueError): d.trusted_key(Path('/local/known_hosts'), 'alias')
                self.assertEqual(run.call_args.args[0][:2], ['/usr/bin/ssh-keygen', '-F'])


if __name__ == '__main__':
    unittest.main()
