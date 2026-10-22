"""Atomic single-node zone transaction; the controller gates both nodes separately."""
import base64
import hashlib
import json
import os
import re
import ipaddress
import fcntl
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import time

POLICY = 'atomic-zone-full-restart-v2'
VIPS = {'10.1.0.55', 'fd36:5aa8:6971:1::55'}
LINKED_VIPS = VIPS | {'10.1.0.56', 'fd36:5aa8:6971:1::56'}
SERVICES = ('unbound', 'pihole-FTL', 'keepalived')
ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def command(argv, timeout=20):
    row = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=ENV)
    if row.returncode:
        raise RuntimeError('command_failed: '+argv[0]+': '+row.stderr[:1000])
    return row.stdout


def event(kind, **values):
    print(json.dumps({'event': kind, 'epoch': time.time(), **values}), flush=True)


def sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def install(path, data, uid, gid, mode, expected=None):
    """Same-directory file fsync, atomic rename, then parent directory fsync."""
    fd, name = tempfile.mkstemp(prefix='.zone-stage-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchown(stream.fileno(), uid, gid)
            os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if expected is not None:
            verify_file(path, expected['sha256'])
            live = path.lstat()
            if (live.st_uid, live.st_gid, stat.S_IMODE(live.st_mode)) != (expected['uid'], expected['gid'], expected['mode']):
                raise RuntimeError('replacement_metadata_drift')
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def verify_file(path, digest):
    p = Path(path)
    try:
        fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise RuntimeError('unsafe_file: '+str(path)) from error
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > 8388608:
            raise RuntimeError('unsafe_file: '+str(path))
        raw = stream.read(8388609)
        after = os.fstat(stream.fileno())
    keys = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns', 'st_uid', 'st_gid', 'st_mode')
    if sha(raw) != digest or any(getattr(info, k) != getattr(after, k) or
            getattr(after, k) != getattr(p.lstat(), k) for k in keys):
        raise RuntimeError('file_drift: '+str(path))
    return raw


def journal_cursor(text):
    cursors = [line[len('-- cursor: '):] for line in text.splitlines() if line.startswith('-- cursor: ')]
    if len(cursors) != 1 or not cursors[0]:
        raise RuntimeError('missing_or_ambiguous_journal_cursor')
    return cursors[0]


def sample(deadline=None):
    def read(argv):
        remaining = 5 if deadline is None else min(5, deadline-time.monotonic())
        if remaining <= 0:
            raise RuntimeError('health_sample_deadline')
        return command(argv, timeout=remaining)
    states = {}
    for unit in SERVICES:
        raw = read(['systemctl', 'show', unit, '-p', 'Id,ActiveState,SubState,MainPID,Result'])
        states[unit] = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    addresses = json.loads(read(['ip', '-json', 'address']))
    return {'services': states, 'vips': sorted({a['local'] for row in addresses
            for a in row.get('addr_info', [])} & VIPS),
            'linked_vips': sorted({a['local'] for row in addresses for a in row.get('addr_info', [])} & LINKED_VIPS)}


def running(states):
    return all(v.get('ActiveState') == 'active' and v.get('SubState') == 'running'
        and v.get('Result') == 'success' and v.get('MainPID', '').isdigit()
        and int(v['MainPID']) > 1 for v in states.values()) and set(states) == set(SERVICES)


def health(node, settle=False):
    """Local gate allows coherent HA movement; only a paired gate proves VIP safety."""
    deadline = time.monotonic()+(30 if settle else 20)
    stable = 0
    while time.monotonic() < deadline:
        row = sample(deadline)
        if time.monotonic() >= deadline:
            raise RuntimeError('health_sample_deadline')
        event('service_sample', settlement=settle, **row)
        if any(v.get('ActiveState') == 'failed' for v in row['services'].values()):
            raise RuntimeError('service_failed')
        good = running(row['services']) and set(row['vips']) in (set(), VIPS)
        if not settle and not good:
            raise RuntimeError('service_or_local_vip_unhealthy')
        stable = stable+1 if good else 0
        if stable >= (2 if settle else 1):
            return row
        time.sleep(min(1, max(0, deadline-time.monotonic())))
    raise RuntimeError('service_or_local_vip_convergence_timeout')


def cluster_gate(rows, required_vips=None):
    """Controller passes two authenticated current snapshots, never a node's success alone."""
    if len(rows) != 2 or len({r['hostname'] for r in rows}) != 2:
        raise RuntimeError('two_distinct_nodes_required')
    if any(not running(r['services']) or not r.get('dns_passed') for r in rows):
        raise RuntimeError('cluster_service_or_dns_unhealthy')
    required = VIPS if required_vips is None else set(required_vips)
    if required_vips is not None and required != LINKED_VIPS:
        raise RuntimeError('coupled_vip_group_mismatch')
    if required_vips is not None and any(not r.get('caddy_healthy') for r in rows):
        raise RuntimeError('linked_caddy_service_unhealthy')
    owners = [set(r['vips'] if required_vips is None else r['linked_vips']) for r in rows]
    if not ((owners[0] == required and not owners[1]) or (owners[1] == required and not owners[0])):
        raise RuntimeError('cluster_vip_split_duplicate_or_missing')
    return rows[0]['hostname'] if owners[0] else rows[1]['hostname']


def restart_services(node, restoring=False):
    command(['systemctl', 'restart', 'unbound.service'])
    # Establish resolver health before restarting its Pi-hole consumer.
    raw = command(['systemctl', 'show', 'unbound', '-p', 'ActiveState,SubState,MainPID,Result'])
    state = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    if not running({k: state for k in SERVICES}):
        raise RuntimeError('unbound_not_running_after_restart')
    # Exact direct resolver checks are frozen per node; no public arbitrary shell.
    checks = node['before_checks' if restoring else 'candidate_checks']
    for check in checks:
        if check['argv'][1] in ('@127.0.0.1', '@::1'):
            check_dns(check, {'127.0.0.1', '::1'})
    command(['/usr/local/bin/pihole', 'restartdns'])
    return health(node, settle=True)


def check_dns(check, allowed_servers, timeout=20):
    argv, expected = check['argv'], check['expected']
    if (not isinstance(argv, list) or len(argv) != 6 or argv[0] != '/usr/bin/dig'
            or argv[1] not in {'@'+a for a in allowed_servers}
            or argv[2] != '-p' or argv[3] not in ('53', '5335')
            or argv[5] not in ('A', 'AAAA', 'PTR') or not argv[4].endswith('.')
            or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,254}', argv[4])
            or expected.get('rcode') not in ('NOERROR', 'NXDOMAIN')):
        raise RuntimeError('invalid_dns_check')
    text = command([*argv, '+time=2', '+tries=1', '+ignore', '+nosearch', '+nocookie',
                    '+noall', '+comments', '+answer'], timeout=timeout)
    statuses = re.findall(r'status: ([A-Z]+),', text)
    answers = []
    for line in text.splitlines():
        if not line or line.startswith(';'):
            continue
        fields = line.split()
        if len(fields) != 5 or fields[2] != 'IN' or not fields[1].isdigit():
            raise RuntimeError('invalid_dns_answer')
        owner, _, _, kind, value = fields
        if kind in ('A', 'AAAA'):
            value = str(ipaddress.ip_address(value))
        else:
            value = value.lower()
        answers.append([owner.lower(), kind, value])
    if statuses != [expected['rcode']] or sorted(answers) != sorted(expected['answers']):
        raise RuntimeError('dns_answer_or_rcode_mismatch')


def check_public_dns(server, port, name):
    ipaddress.ip_address(server)
    if port not in ('53', '5335') or name != 'example.org.':
        raise RuntimeError('unreviewed_public_probe')
    text = command(['/usr/bin/dig', '@'+server, '-p', port, name, 'A', '+time=2',
                    '+tries=1', '+ignore', '+nosearch', '+nocookie', '+noall', '+comments', '+answer'])
    if re.findall(r'status: ([A-Z]+),', text) != ['NOERROR'] or not any(
            len(parts := line.split()) == 5 and parts[2:4] == ['IN', 'A']
            for line in text.splitlines() if line and not line.startswith(';')):
        raise RuntimeError('public_resolution_unhealthy')


def inspect_node(node, dest, expected_hash, checks):
    verify_file(dest, expected_hash)
    row = health(node)
    def caddy_state():
        raw = command(['systemctl', 'show', 'caddy.service', '-p', 'ActiveState,SubState,MainPID,Result'])
        return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
    before_caddy = caddy_state() if node.get('coupled_vips') else None
    for check in checks:
        check_dns(check, {'127.0.0.1', '::1', *node['addresses']})
    if node.get('public_health_name'):
        for server, port in [('127.0.0.1', '5335'), ('::1', '5335'), *[(a, '53') for a in node['addresses']]]:
            check_public_dns(server, port, node['public_health_name'])
    verify_file(dest, expected_hash)
    final = sample()
    if row != final:
        raise RuntimeError('snapshot_service_or_vip_drift')
    if before_caddy is not None:
        after_caddy = caddy_state()
        if before_caddy != after_caddy or not running({u: after_caddy for u in SERVICES}):
            raise RuntimeError('caddy_service_unhealthy_or_changed')
        final.update(caddy_healthy=True, caddy_state=after_caddy)
    return dict(final, hostname=node['hostname'], boot_id=node['boot_id'],
                dns_passed=True, zone_sha256=expected_hash)


def durable_file(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    sync_directory(path.parent)


def state_write(backup, value):
    install(backup/'state.json', (json.dumps(value, sort_keys=True)+'\n').encode(), 0, 0, 0o600)


def backup_check(backup):
    info = backup.lstat()
    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != 0:
        raise RuntimeError('unsafe_backup')


def restore(node, dest, backup, before, candidate_hash):
    backup_check(backup)
    original = verify_file(backup/'original.conf', before['sha256'])
    record = json.loads(verify_file(backup/'before.json', node['before_record_sha256']))
    if record != before:
        raise RuntimeError('backup_metadata_mismatch')
    current = dest.lstat()
    if not stat.S_ISREG(current.st_mode):
        raise RuntimeError('unsafe_destination')
    current_hash = sha(dest.read_bytes())
    if current_hash not in (before['sha256'], candidate_hash):
        raise RuntimeError('rollback_destination_drift')
    if (current.st_uid, current.st_gid, stat.S_IMODE(current.st_mode)) != (before['uid'], before['gid'], before['mode']):
        raise RuntimeError('rollback_metadata_drift')
    state_write(backup, {'phase': 'restore_intent', 'before': before['sha256'], 'candidate': candidate_hash})
    install(dest, original, before['uid'], before['gid'], before['mode'], expected=dict(before, sha256=current_hash))
    command(['unbound-checkconf', '/etc/unbound/unbound.conf'])
    restart_services(node, restoring=True)
    verify_file(dest, before['sha256'])
    state_write(backup, {'phase': 'restored_requires_cluster_dns_gate', 'before': before['sha256'], 'candidate': candidate_hash})
    event('rollback_verified_file_and_services', dns_verification_pending=True)


def transaction(payload):
    os.umask(0o077)
    op = payload['operation']
    if op.get('policy') != POLICY:
        raise RuntimeError('new_restart_and_ha_policy_required')
    node = dict(op['nodes'][payload['node']])
    dest = Path(op['target_path'])
    backup = Path(node['backup_directory'])
    before = node['files'][str(dest)]
    # Record hash is bound by the new operation, not by mutable local backup state.
    node['before_record_sha256'] = sha((json.dumps(before, sort_keys=True)+'\n').encode())
    phase = payload['phase']
    if os.geteuid() != 0 or command(['hostname']).strip() != node['hostname']:
        raise RuntimeError('identity_mismatch')
    boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    if boot != node['boot_id']:
        raise RuntimeError('boot_identity_mismatch')
    for _, binary in node['binaries'].items():
        verify_file(binary['path'], binary['sha256'])
    actual = {str(p) for p in Path('/etc/unbound/unbound.conf.d').glob('*.conf')} | {'/etc/unbound/unbound.conf'}
    if actual != set(node['files']):
        raise RuntimeError('include_set_changed')
    for path, record in node['files'].items():
        if path != str(dest):
            verify_file(path, record['sha256'])
    for kind in ('before_checks', 'candidate_checks'):
        if not node.get(kind) or not all(any(check['argv'][1] == '@'+a and
                check['argv'][3] == '5335' for check in node[kind]) for a in ('127.0.0.1', '::1')):
            raise RuntimeError('both_family_direct_unbound_checks_required')
    if phase == 'inspect':
        desired = payload['expected_state']
        if desired not in ('before', 'candidate'):
            raise RuntimeError('invalid_expected_state')
        digest = before['sha256'] if desired == 'before' else op['candidate_sha256']
        return inspect_node(node, dest, digest, node[desired+'_checks'])
    if phase == 'rollback':
        restore(node, dest, backup, before, op['candidate_sha256'])
        return {'result': 'restored_requires_cluster_dns_gate'}
    if phase != 'apply':
        raise RuntimeError('unknown_phase')
    candidate = base64.b64decode(payload['candidate'], validate=True)
    expanded = base64.b64decode(payload['expanded'], validate=True)
    if sha(candidate) != op['candidate_sha256'] or sha(expanded) != node['expanded_sha256']:
        raise RuntimeError('candidate_hash')
    health(node)
    original = verify_file(dest, before['sha256'])
    info = dest.lstat()
    if (info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode)) != (before['uid'], before['gid'], before['mode']):
        raise RuntimeError('metadata_drift')
    command(['unbound-checkconf', '/etc/unbound/unbound.conf'])
    row = subprocess.run(['unbound-checkconf', '/dev/stdin'], input=expanded,
                         capture_output=True, timeout=20, env=ENV)
    if row.returncode:
        raise RuntimeError('candidate_validation_failed')
    backup.mkdir(mode=0o700, exist_ok=False)
    sync_directory(backup.parent)
    durable_file(backup/'original.conf', original)
    durable_file(backup/'before.json', (json.dumps(before, sort_keys=True)+'\n').encode())
    durable_file(backup/'journal-cursor.txt', (journal_cursor(command(
        ['journalctl', '-n', '0', '--show-cursor', '--no-pager']))+'\n').encode())
    state_write(backup, {'phase': 'prepared', 'before': before['sha256'], 'candidate': op['candidate_sha256']})
    try:
        verify_file(dest, before['sha256'])
        state_write(backup, {'phase': 'write_intent', 'before': before['sha256'], 'candidate': op['candidate_sha256']})
        install(dest, candidate, before['uid'], before['gid'], before['mode'], expected=before)
        state_write(backup, {'phase': 'installed', 'before': before['sha256'], 'candidate': op['candidate_sha256']})
        command(['unbound-checkconf', '/etc/unbound/unbound.conf'])
        restart_services(node)
        verify_file(dest, op['candidate_sha256'])
        state_write(backup, {'phase': 'applied_requires_cluster_dns_gate', 'before': before['sha256'], 'candidate': op['candidate_sha256']})
        return {'result': 'applied_requires_cluster_dns_gate', 'backup': str(backup), 'sha256': op['candidate_sha256']}
    except Exception as error:
        event('apply_failed', error=str(error))
        try:
            restore(node, dest, backup, before, op['candidate_sha256'])
        except Exception as recovery_error:
            event('manual_intervention', apply_error=str(error), rollback_error=str(recovery_error))
            raise RuntimeError('rollback_unverified') from recovery_error
        raise


def main(payload):
    op = payload['operation']
    if op.get('policy') != POLICY:
        raise RuntimeError('new_restart_and_ha_policy_required')
    if payload['phase'] == 'inspect':
        return transaction(payload)
    if os.geteuid() != 0:
        raise RuntimeError('root_required')
    lock = Path(op['target_path']).parent/'.zone-deployment.lock'
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600:
            raise RuntimeError('unsafe_deployment_lock')
        return transaction(payload)
    finally:
        os.close(fd)


if __name__ == '__main__':
    print(json.dumps(main(json.loads(sys.stdin.read(1048576)))))
