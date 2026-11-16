"""Hash-gated paired DNS/HA acceptance. Never mutates nodes or advances a peer."""
import hashlib
import importlib.util
import json
import os
import copy
import stat
from pathlib import Path
import re
import subprocess
import sys
import time


def load_inputs(root, digest):
    index = (root/'SHA256SUMS').read_bytes()
    if hashlib.sha256(index).hexdigest() != digest:
        raise RuntimeError('authorization_hash_mismatch')
    names = set()
    for line in index.decode().splitlines():
        expected, name = line.split('  ', 1)
        if Path(name).name != name or name in names or hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('bundle_input_mismatch')
        names.add(name)
    if not {'node.py', 'verify.py', 'operation.json', 'known_hosts'}.issubset(names):
        raise RuntimeError('missing_bound_inputs')
    spec = importlib.util.spec_from_file_location('zone_node', root/'node.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    operation = json.loads((root/'operation.json').read_text())
    if not operation['prepared_epoch'] <= time.time() < operation['expires_epoch']-300:
        raise RuntimeError('operation_expired_or_not_started')
    if operation.get('policy') != module.POLICY or set(operation['nodes']) != {'secondary', 'primary'}:
        raise RuntimeError('new_policy_and_two_nodes_required')
    if operation.get('boot_policy') != module.BOOT_POLICY:
        raise RuntimeError('operation_boot_admission_policy_required')
    return operation, module


def admitted_operation(root, operation, digest):
    """Resume only the accepted initial gate's boot IDs, never historical pins."""
    path = root.parent/'gate-before.json'
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600 or info.st_size > 1048576):
            raise RuntimeError('unsafe_admission_receipt')
        gate = json.loads(stream.read(1048577))
    ids = gate.get('boot_ids', {})
    if (not gate.get('accepted') or gate.get('phase') != 'before'
            or gate.get('sha256') != digest or gate.get('operation_id') != operation['operation_id']
            or set(ids) != set(operation['nodes'])
            or not all(isinstance(x, str) and re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', x) for x in ids.values())):
        raise RuntimeError('bound_boot_admission_required')
    bound = copy.deepcopy(operation)
    for label, boot in ids.items():
        bound['nodes'][label]['boot_id'] = boot
    return bound


def snapshot_failure(label, kind, returncode=None, stdout=b'', stderr=b'', errno=None):
    """Report bounded metadata and allowlisted hints, never raw remote output."""
    stdout, stderr = stdout or b'', stderr or b''
    hints = {
        b'Host key verification failed': 'ssh-host-key',
        b'Permission denied (': 'ssh-authentication',
        b'Connection refused': 'connection-refused',
        b'No route to host': 'no-route',
        b'Connection timed out': 'connection-timeout',
        b'sudo: a password is required': 'sudo-password-required',
    }
    hint = next((value for key, value in hints.items() if key in stderr[:65536]), 'unknown')
    match = re.search(rb'^RuntimeError: ([a-z_]+)(?::|$)', stderr[:65536], re.M)
    if match and match[1] in {
            b'identity_mismatch', b'boot_identity_mismatch', b'include_set_changed',
            b'unsafe_file', b'file_drift', b'command_failed', b'service_failed',
            b'service_or_local_vip_unhealthy', b'service_or_local_vip_convergence_timeout',
            b'dns_answer_or_rcode_mismatch', b'public_resolution_unhealthy',
            b'snapshot_service_or_vip_drift', b'caddy_service_unhealthy_or_changed'}:
        hint = match[1].decode('ascii')
    return RuntimeError('snapshot_failed: '+json.dumps({
        'node': label if label in ('primary', 'secondary') else 'unknown',
        'kind': kind, 'expected_exit': 0, 'observed_exit': returncode,
        'stdout_bytes': len(stdout), 'stderr_bytes': len(stderr),
        'errno': errno, 'hint': hint}, sort_keys=True))


def snapshot(root, operation, label, desired, timeout=60):
    node = operation['nodes'][label]
    options = ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
        'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
        'ControlPath=none', 'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no',
        'PermitLocalCommand=no', 'ConnectTimeout=8', 'GlobalKnownHostsFile=/dev/null',
        'UserKnownHostsFile='+str(root/'known_hosts'), 'HostKeyAlias='+node['host_key_alias']]
    # Literal target and sealed key: resolver state is not SSH trust.
    argv = ['ssh', '-F', '/dev/null', '-T', '-4', *[v for o in options for v in ('-o', o)],
            node['ssh'], 'cd / && sudo -n python3 -I -B -']
    payload = {'operation': operation, 'node': label, 'phase': 'inspect', 'expected_state': desired}
    source = (root/'node.py').read_bytes()
    wire = b"__name__='zone_snapshot'\n"+source+b'\nprint(json.dumps(main('+repr(payload).encode()+b')))\n'
    try:
        row = subprocess.run(argv, input=wire, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise snapshot_failure(label, 'timeout', stdout=error.stdout, stderr=error.stderr) from None
    except OSError as error:
        raise snapshot_failure(label, 'launch', errno=error.errno) from None
    if len(row.stdout) > 1048576 or len(row.stderr) > 65536:
        raise snapshot_failure(label, 'output-limit', row.returncode, row.stdout, row.stderr)
    if row.returncode:
        raise snapshot_failure(label, 'command-exit', row.returncode, row.stdout, row.stderr)
    # Node emits health events before its final bound result.
    try:
        capture = json.loads(row.stdout.splitlines()[-1])
        if not isinstance(capture, dict):
            raise ValueError('object required')
    except (IndexError, ValueError, UnicodeError):
        raise snapshot_failure(label, 'invalid-result', row.returncode, row.stdout, row.stderr) from None
    expected_hash = node['files'][operation['target_path']]['sha256'] if desired == 'before' else operation['candidate_sha256']
    if node.get('boot_id') is not None and capture.get('boot_id') != node['boot_id']:
        raise RuntimeError('boot_identity_mismatch')
    if (capture.get('hostname') != node['hostname']
            or capture.get('zone_sha256') != expected_hash):
        raise RuntimeError('snapshot_identity_or_state_mismatch')
    if operation.get('boot_policy') == 'operation-admission-v1':
        boot = capture.get('boot_id')
        if not isinstance(boot, str) or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', boot):
            raise RuntimeError('invalid_observed_boot_id')
    return capture


def paired_gate(root, operation, module, states, fetch=snapshot):
    """Two coherent consecutive samples; re-evaluate VIP answers for the actual owner."""
    deadline = time.monotonic()+180
    previous = None
    observations = []
    while time.monotonic() < deadline:
        try:
            rows = []
            for label in ('secondary', 'primary'):
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('paired_deadline')
                row = fetch(root, operation, label, states[label], timeout=min(60, remaining))
                if operation.get('boot_policy') == 'operation-admission-v1':
                    expected = operation['nodes'][label].get('boot_id')
                    if expected is not None and row['boot_id'] != expected:
                        raise RuntimeError('boot_identity_mismatch')
                    operation['nodes'][label]['boot_id'] = row['boot_id']
                rows.append(row)
            owner = module.cluster_gate(rows, required_vips=operation['coupled_vips']) if operation.get('coupled_vips') else module.cluster_gate(rows)
            label = next(n for n, v in operation['nodes'].items() if v['hostname'] == owner)
            for check in operation['vip_'+states[label]+'_checks']:
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('paired_deadline')
                module.check_dns(check, module.VIPS, timeout=min(20, remaining))
            if operation.get('public_health_name'):
                for address in sorted(module.VIPS):
                    module.check_public_dns(address, '53', operation['public_health_name'])
            for address in operation.get('proxy_health_addresses', []):
                if address not in ('10.1.0.56', 'fd36:5aa8:6971:1::56'):
                    raise RuntimeError('unreviewed_proxy_address')
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('paired_deadline')
                literal = '['+address+']' if ':' in address else address
                status = module.command(['/usr/bin/curl', '--noproxy', '*', '--silent', '--show-error',
                    '--fail', '--connect-timeout', '2', '--max-time', '4', '--output', '/dev/null',
                    '--write-out', '%{http_code}', '--resolve', 'proxy.local.theama.co:443:'+literal,
                    'https://proxy.local.theama.co/'], timeout=min(5, remaining))
                if status.strip() != '204':
                    raise RuntimeError('linked_proxy_health_failed')
            signature = [(r['hostname'], r['linked_vips'] if operation.get('coupled_vips') else r['vips']) for r in rows]
            observations.append({'owner': owner, 'signature': signature})
            if signature == previous:
                return {'accepted': True, 'owner': owner, 'observations': observations,
                        'boot_ids': {label: node.get('boot_id') for label, node in operation['nodes'].items()}}
            previous = signature
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            if ('boot_identity_mismatch' in str(error)
                    or (operation.get('boot_policy') == 'operation-admission-v1'
                        and any(node.get('boot_id') is None for node in operation['nodes'].values()))):
                # Never discover a different initial boot after an incomplete sample.
                raise
            observations.append({'error': str(error)})
            previous = None
        time.sleep(1)
    raise RuntimeError('cluster_convergence_timeout: '+json.dumps(observations)[-4000:])


def main():
    if len(sys.argv) != 3 or sys.argv[2] not in ('before', 'secondary', 'all', 'rollback-secondary', 'rollback-all'):
        raise SystemExit('usage: verify.py APPROVED_SHA256 before|secondary|all|rollback-secondary|rollback-all')
    root = Path(__file__).resolve().parent
    operation, module = load_inputs(root, sys.argv[1])
    phase = sys.argv[2]
    if phase == 'before':
        for node in operation['nodes'].values():
            node['boot_id'] = None
    else:
        operation = admitted_operation(root, operation, sys.argv[1])
    states = {'secondary': 'candidate' if phase in ('secondary', 'all') else 'before',
              'primary': 'candidate' if phase == 'all' else 'before'}
    if phase == 'rollback-secondary':
        # First reverse-order restoration: primary is old, secondary still candidate.
        states = {'secondary': 'candidate', 'primary': 'before'}
    receipt = root.parent/('gate-'+phase+'.json')
    os.umask(0o077)
    with receipt.open('x') as stream:
        json.dump({'accepted': False, 'sha256': sys.argv[1], 'started_epoch': time.time()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    result = paired_gate(root, operation, module, states)
    result.update(sha256=sys.argv[1], recorded_epoch=time.time(), phase=phase, operation_id=operation['operation_id'])
    module.install(receipt, (json.dumps(result)+'\n').encode(), os.getuid(), os.getgid(), 0o600)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
