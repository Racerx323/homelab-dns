"""Hash-gated paired DNS/HA acceptance. Never mutates nodes or advances a peer."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
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
    return operation, module


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
    row = subprocess.run(argv, input=wire, capture_output=True, timeout=timeout)
    if row.returncode or len(row.stdout) > 1048576 or len(row.stderr) > 65536:
        raise RuntimeError('snapshot_transport_failed')
    # Node emits health events before its final bound result.
    capture = json.loads(row.stdout.splitlines()[-1])
    expected_hash = node['files'][operation['target_path']]['sha256'] if desired == 'before' else operation['candidate_sha256']
    if (capture.get('hostname') != node['hostname'] or capture.get('boot_id') != node['boot_id']
            or capture.get('zone_sha256') != expected_hash):
        raise RuntimeError('snapshot_identity_or_state_mismatch')
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
                rows.append(fetch(root, operation, label, states[label], timeout=min(60, remaining)))
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
                return {'accepted': True, 'owner': owner, 'observations': observations}
            previous = signature
        except (RuntimeError, subprocess.TimeoutExpired) as error:
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
    result.update(sha256=sys.argv[1], recorded_epoch=time.time(), phase=phase)
    module.install(receipt, (json.dumps(result)+'\n').encode(), os.getuid(), os.getgid(), 0o600)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
