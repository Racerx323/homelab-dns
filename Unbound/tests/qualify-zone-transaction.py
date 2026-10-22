"""Isolated native systemd/Unbound qualification; no production network access."""
import base64
import copy
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'localhost/ntp-zone-transaction:bookworm'
BASE = b'''server:
    local-zone: "local.theama.co." static
    local-zone: "ip6.arpa." static
    local-data: "ntp1.local.theama.co. IN A 10.1.0.51"
    local-data-ptr: "10.1.0.51 ntp1.local.theama.co."
'''
CANDIDATE = BASE+b'''    local-data: "ntp1.local.theama.co. IN AAAA fd36:5aa8:6971:1::51"
    local-data-ptr: "fd36:5aa8:6971:1::51 ntp1.local.theama.co."
'''
MAIN = b'''server:
    interface: 127.0.0.1
    interface: ::1
    port: 5335
    username: ""
    chroot: ""
    directory: "/etc/unbound"
    pidfile: "/run/unbound.pid"
    use-syslog: no
    do-daemonize: no
    module-config: "iterator"
include: "/etc/unbound/unbound.conf.d/pihole-local-zone.conf"
'''
DEST = '/etc/unbound/unbound.conf.d/pihole-local-zone.conf'


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/'scripts'/file)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def sha(raw): return hashlib.sha256(raw).hexdigest()


class Fixture:
    def __init__(self, out):
        self.out = out; self.index = 0; self.containers = {}; self.results = []
        self.operation = None

    def run(self, argv, data=None, check=True, timeout=120):
        self.index += 1
        prefix = self.out/f'{self.index:04d}'
        with (self.out/'commands.jsonl').open('a') as stream:
            stream.write(json.dumps({'index': self.index, 'argv': argv, 'stdin_sha256': sha(data) if data else None, 'timeout': timeout})+'\n')
        row = subprocess.run(argv, input=data, capture_output=True, timeout=timeout)
        prefix.with_suffix('.stdout').write_bytes(row.stdout); prefix.with_suffix('.stderr').write_bytes(row.stderr)
        prefix.with_suffix('.exit').write_text(str(row.returncode)+'\n')
        if check and row.returncode:
            raise RuntimeError(f'fixture command {self.index} failed; retained output {prefix}')
        return row

    def inside(self, label, argv, data=None, check=True):
        return self.run(['podman', 'exec', '-i', self.containers[label], *argv], data, check)

    def python(self, label, code):
        return self.inside(label, ['python3', '-I', '-B', '-'], code.encode())

    def setup(self):
        image = self.run(['podman', 'image', 'inspect', IMAGE, '--format', '{{.Id}}']).stdout.decode().strip()
        (self.out/'image-id.txt').write_text(image+'\n')
        for label, suffix in [('secondary', '54'), ('primary', '53')]:
            name = 'zone-qualification-'+suffix+'-'+str(os.getpid())
            self.containers[label] = name
            (self.out/'containers.json').write_text(json.dumps(self.containers)+'\n')
            self.run(['podman', 'run', '--detach', '--name', name, '--hostname', name, '--network=none',
                '--systemd=always', '--cap-add=NET_ADMIN', '--tmpfs', '/run', '--tmpfs', '/tmp',
                '--volume', str(ROOT)+':/payload:ro', IMAGE])
            # systemd readiness is bounded; each command/log is retained.
            for attempt in range(30):
                row = self.inside(label, ['systemctl', 'show', '-p', 'SystemState', '--value'], check=False)
                if row.returncode == 0 and row.stdout.strip() in (b'running', b'degraded'): break
                time.sleep(1)
            else: raise RuntimeError('fixture systemd readiness timeout')
            script = '''from pathlib import Path
import subprocess
p=Path('/etc/unbound/unbound.conf.d')
for f in p.glob('*.conf'):f.unlink()
Path('/etc/unbound/unbound.conf').write_bytes(MAIN)
Path(DEST).write_bytes(BASE)
Path('/var/lib/zone-test').mkdir(mode=0o700,exist_ok=True)
units={
'unbound.service': '[Unit]\\nDescription=Native Unbound qualification\\n[Service]\\nType=simple\\nExecStartPre=/usr/local/sbin/unbound-failure-hook\\nExecStart=/usr/sbin/unbound -d -c /etc/unbound/unbound.conf\\n',
'pihole-FTL.service': '[Unit]\\nDescription=dnsmasq Pi-hole service boundary stand-in\\n[Service]\\nType=simple\\nExecStart=/usr/sbin/dnsmasq --no-daemon --no-resolv --conf-file=/dev/null --server=127.0.0.1#5335 --cache-size=100 --user=root\\n',
'keepalived.service': '[Unit]\\nDescription=HA service identity sentinel, not VRRP qualification\\n[Service]\\nType=simple\\nExecStart=/bin/sleep infinity\\n'}
for name,text in units.items():Path('/etc/systemd/system',name).write_text(text)
Path('/usr/local/bin/pihole').write_text('#!/bin/sh\\n[ "$#" -eq 1 ] && [ "$1" = restartdns ] || exit 91\\nif [ -e /run/fail-pihole-once ]; then rm /run/fail-pihole-once; exit 42; fi\\nexec /bin/systemctl restart pihole-FTL.service\\n')
Path('/usr/local/bin/pihole').chmod(0o755)
Path('/usr/local/sbin/unbound-failure-hook').write_text('#!/bin/sh\\nif [ -e /run/fail-unbound-once ]; then rm /run/fail-unbound-once; exit 42; fi\\n')
Path('/usr/local/sbin/unbound-failure-hook').chmod(0o755)
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','restart','unbound','pihole-FTL','keepalived'],check=True)
'''
            self.python(label, 'MAIN='+repr(MAIN)+'\nBASE='+repr(BASE)+'\nDEST='+repr(DEST)+'\n'+script)
            self.inside(label, ['ip', 'addr', 'add', '10.1.0.'+suffix+'/32', 'dev', 'lo'])
            self.inside(label, ['ip', '-6', 'addr', 'add', 'fd36:5aa8:6971:1::'+suffix+'/128', 'dev', 'lo', 'nodad'])
            self.inside(label, ['dpkg-query', '-W', 'unbound', 'dnsmasq-base', 'systemd', 'dnsutils'])
        self.move_owner('primary')

    def move_owner(self, owner):
        for label in self.containers:
            for family, address in [('4', '10.1.0.55/32'), ('6', 'fd36:5aa8:6971:1::55/128')]:
                self.inside(label, ['ip', '-'+family, 'addr', 'del', address, 'dev', 'lo'], check=False)
                if label == owner:
                    self.inside(label, ['ip', '-'+family, 'addr', 'add', address, 'dev', 'lo', *(['nodad'] if family == '6' else [])])
        self.owner = owner

    def checks(self, suffix, candidate, servers=None):
        checks = []
        queries = [('ntp1.local.theama.co.', 'A', '10.1.0.51'),
                   ('ntp1.local.theama.co.', 'AAAA', 'fd36:5aa8:6971:1::51' if candidate else None),
                   (ipaddress.ip_address('10.1.0.51').reverse_pointer+'.', 'PTR', 'ntp1.local.theama.co.'),
                   (ipaddress.ip_address('fd36:5aa8:6971:1::51').reverse_pointer+'.', 'PTR', 'ntp1.local.theama.co.' if candidate else None)]
        for server, port in servers or [('127.0.0.1', '5335'), ('::1', '5335'), ('10.1.0.'+suffix, '53'), ('fd36:5aa8:6971:1::'+suffix, '53')]:
            for name, kind, value in queries:
                checks.append({'argv': ['/usr/bin/dig', '@'+server, '-p', port, name, kind],
                    'expected': {'rcode': 'NXDOMAIN' if not value and kind == 'PTR' else 'NOERROR',
                                 'answers': [[name, kind, value]] if value else []}})
        return checks

    def prepare(self, case):
        nodes = {}
        for label, suffix in [('secondary', '54'), ('primary', '53')]:
            self.python(label, 'from pathlib import Path\nimport subprocess\nPath('+repr(DEST)+').write_bytes('+repr(BASE)+')\nsubprocess.run(["systemctl","restart","unbound","pihole-FTL"],check=True)\n')
            script = '''import json,hashlib,socket
from pathlib import Path
paths=['/etc/unbound/unbound.conf',DEST]
files={p:{'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest(),'uid':Path(p).stat().st_uid,'gid':Path(p).stat().st_gid,'mode':Path(p).stat().st_mode&0o777} for p in paths}
print(json.dumps({'hostname':socket.gethostname(),'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip(),'files':files}))
'''
            node = json.loads(self.python(label, 'DEST='+repr(DEST)+'\n'+script).stdout)
            node.update(backup_directory='/var/lib/zone-test/'+case, binaries={}, addresses=['10.1.0.'+suffix, 'fd36:5aa8:6971:1::'+suffix],
                before_checks=self.checks(suffix, False), candidate_checks=self.checks(suffix, True), expanded_sha256=sha(MAIN.replace(b'include: "/etc/unbound/unbound.conf.d/pihole-local-zone.conf"', CANDIDATE)))
            nodes[label] = node
        self.operation = {'policy': 'atomic-zone-full-restart-v2', 'target_path': DEST, 'candidate_sha256': sha(CANDIDATE), 'nodes': nodes,
            'vip_before_checks': self.checks('', False, [('10.1.0.55','53'),('fd36:5aa8:6971:1::55','53')]),
            'vip_candidate_checks': self.checks('', True, [('10.1.0.55','53'),('fd36:5aa8:6971:1::55','53')])}
        self.move_owner('primary')

    def action(self, label, phase, expected_state=None, check=True):
        payload = {'operation': self.operation, 'node': label, 'phase': phase}
        if phase == 'apply':
            payload.update(candidate=base64.b64encode(CANDIDATE).decode(), expanded=base64.b64encode(MAIN.replace(b'include: "/etc/unbound/unbound.conf.d/pihole-local-zone.conf"', CANDIDATE)).decode())
        if expected_state: payload['expected_state'] = expected_state
        row = self.inside(label, ['python3','-I','-B','/payload/scripts/apply-host-records.py'], json.dumps(payload).encode(), check)
        return row

    def paired(self, states):
        verifier = load('native_verifier', 'verify-host-records.py'); module = load('native_node', 'apply-host-records.py')
        def fetch(root, operation, label, desired, timeout):
            return json.loads(self.action(label, 'inspect', desired).stdout.splitlines()[-1])
        def vip_check(check, servers, timeout=20):
            code = 'import importlib.util\ns=importlib.util.spec_from_file_location("n","/payload/scripts/apply-host-records.py")\nn=importlib.util.module_from_spec(s);s.loader.exec_module(n)\nn.check_dns('+repr(check)+','+repr(servers)+')\n'
            self.python(self.owner, code)
        with patch.object(module, 'check_dns', side_effect=vip_check):
            return verifier.paired_gate(self.out, self.operation, module, states, fetch)

    def result(self, name):
        self.results.append({'case': name, 'passed': True})
        (self.out/'native-results.json').write_text(json.dumps(self.results, indent=2)+'\n')
        print(json.dumps(self.results[-1]), flush=True)

    def qualify(self):
        self.setup()
        self.prepare('commit-and-reverse-recovery')
        self.paired({'secondary':'before','primary':'before'})
        self.action('secondary','apply')
        self.paired({'secondary':'candidate','primary':'before'})
        # Explicit fixture VIP relocation exercises acceptance, not real Keepalived VRRP.
        self.move_owner('secondary')
        self.paired({'secondary':'candidate','primary':'before'})
        self.action('primary','apply'); self.paired({'secondary':'candidate','primary':'candidate'})
        self.action('primary','rollback'); self.paired({'secondary':'candidate','primary':'before'})
        self.move_owner('primary')
        self.action('secondary','rollback'); self.paired({'secondary':'before','primary':'before'})
        self.result('two-node-commit-coherent-vip-move-and-reverse-recovery')
        for marker in ('unbound','pihole'):
            self.prepare('failure-'+marker)
            self.python('secondary','from pathlib import Path\nPath("/run/fail-'+marker+'-once").touch()\n')
            row = self.action('secondary','apply',check=False)
            assert row.returncode != 0
            self.paired({'secondary':'before','primary':'before'})
            self.result(marker+'-restart-failure-restores-and-restarts-both')
        self.prepare('foreign-drift')
        self.action('secondary','apply')
        self.python('secondary','from pathlib import Path\nPath('+repr(DEST)+').write_bytes(b"# foreign drift\\n")\n')
        row = self.action('secondary','rollback',check=False)
        assert row.returncode != 0 and b'rollback_destination_drift' in row.stderr
        self.result('foreign-drift-preserved-and-recovery-held')
        for label in self.containers:self.inside(label,['systemctl','show','unbound','pihole-FTL','keepalived','-p','Id,ActiveState,SubState,MainPID,Result'])
        (self.out/'completed.json').write_text(json.dumps({'cases':len(self.results),'production_contact':False,'transport':'Podman exec fixture; pinned SSH tested offline','limits':'dnsmasq/Pi-hole CLI and sleep/Keepalived stand-ins; no physical HA, live ARM64 or real FTL acceptance'})+'\n')
        for name in self.containers.values():self.run(['podman','rm','--force',name])


if __name__ == '__main__':
    os.umask(0o077)
    out=Path(sys.argv[1]).resolve();out.mkdir(mode=0o700,exist_ok=False)
    (out/'input-revision.json').write_text(json.dumps({str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in [ROOT/'scripts/apply-host-records.py',ROOT/'scripts/verify-host-records.py',ROOT/'scripts/dispatch-host-records.py',Path(__file__)]},indent=2)+'\n')
    Fixture(out).qualify()
