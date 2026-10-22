"""One-use hash-gated node mutation, requiring fresh paired acceptance first."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main(root, digest, label, phase):
    if label not in ('secondary', 'primary') or phase not in ('apply', 'rollback'):
        raise RuntimeError('invalid_phase_or_node')
    index = (root/'SHA256SUMS').read_bytes()
    if hashlib.sha256(index).hexdigest() != digest:
        raise RuntimeError('authorization_hash_mismatch')
    names = set()
    for line in index.decode().splitlines():
        expected, name = line.split('  ', 1)
        if Path(name).name != name or name in names or hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('bundle_input_mismatch')
        names.add(name)
    if not {'node.py', 'dispatch.py', 'verify.py', 'operation.json', 'known_hosts'}.issubset(names):
        raise RuntimeError('missing_bound_inputs')
    op = json.loads((root/'operation.json').read_text())
    if op.get('policy') != 'atomic-zone-full-restart-v2' or not op['prepared_epoch'] <= time.time() < op['expires_epoch']-300:
        raise RuntimeError('new_policy_or_expiry_required')
    if phase == 'apply':
        gate_name = 'before' if label == 'secondary' else 'secondary'
        gate = json.loads((root.parent/('gate-'+gate_name+'.json')).read_text())
        if (not gate.get('accepted') or gate.get('sha256') != digest or
                not 0 <= time.time()-gate['recorded_epoch'] <= 120):
            raise RuntimeError('fresh_paired_gate_required')
    os.umask(0o077)
    invocation = root.parent/(label+'-'+phase+'-receipt.json')
    with invocation.open('x') as stream:
        json.dump({'sha256': digest, 'node': label, 'phase': phase, 'started_epoch': time.time()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    payload = {'operation': op, 'node': label, 'phase': phase}
    if phase == 'apply':
        import base64
        payload.update(candidate=base64.b64encode((root/'candidate.conf').read_bytes()).decode(),
                       expanded=base64.b64encode((root/(label+'-candidate-expanded.conf')).read_bytes()).decode())
    node = op['nodes'][label]
    options = ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
        'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no',
        'ControlPath=none', 'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no',
        'PermitLocalCommand=no', 'ConnectTimeout=8', 'GlobalKnownHostsFile=/dev/null',
        'UserKnownHostsFile='+str(root/'known_hosts'), 'HostKeyAlias='+node['host_key_alias']]
    argv = ['ssh', '-F', '/dev/null', '-T', '-4', *[v for o in options for v in ('-o', o)],
            node['ssh'], 'cd / && sudo -n python3 -I -B -']
    wire = b"__name__='zone_transaction'\n"+(root/'node.py').read_bytes()+b'\nprint(json.dumps(main('+repr(payload).encode()+b')))\n'
    with (root.parent/(label+'-'+phase+'.stdout')).open('xb') as stdout, (root.parent/(label+'-'+phase+'.stderr')).open('xb') as stderr:
        try:
            row = subprocess.run(argv, input=wire, stdout=stdout, stderr=stderr, timeout=300)
            status = row.returncode
        except subprocess.TimeoutExpired:
            status = 124
    (root.parent/(label+'-'+phase+'.status')).write_text(str(status)+'\n')
    return status


if __name__ == '__main__':
    if len(sys.argv) != 4:
        raise SystemExit('usage: dispatch.py APPROVED_SHA256 secondary|primary apply|rollback')
    raise SystemExit(main(Path(__file__).resolve().parent, *sys.argv[1:]))
