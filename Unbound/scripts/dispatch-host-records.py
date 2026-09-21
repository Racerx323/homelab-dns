"""Hash-gated single-node dispatcher. Never advances automatically to the peer."""
import base64,hashlib,json,os,shlex,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
if len(sys.argv)!=4:raise SystemExit('usage: dispatch.py BUNDLE_SHA256 secondary|primary apply|rollback')
authorized,node,phase=sys.argv[1:]
index=(root/'SHA256SUMS').read_bytes()
if hashlib.sha256(index).hexdigest()!=authorized:raise SystemExit('authorization_hash_mismatch')
for line in index.decode().splitlines():
 digest,name=line.split('  ',1)
 if Path(name).name!=name or hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:raise SystemExit('bundle_input_mismatch')
if node not in ['secondary','primary'] or phase not in ['apply','rollback']:raise SystemExit('invalid phase/node')
op=json.loads((root/'operation.json').read_text())
payload={'operation':op,'node':node,'phase':phase,'candidate':base64.b64encode((root/'candidate.conf').read_bytes()).decode(),'expanded':base64.b64encode((root/(node+'-candidate-expanded.conf')).read_bytes()).decode()}
# Executable code is quoted separately; configuration travels only on stdin.
argv=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-o','ConnectTimeout=6',op['nodes'][node]['ssh'],'cd / && sudo -n python3 -c '+shlex.quote((root/'node.py').read_text())]
os.umask(0o077)
import time
name=str(int(time.time()))+'-'+node+'-'+phase
out=root.parent/(name+'.stdout');err=root.parent/(name+'.stderr')
with out.open('xb') as stdout,err.open('xb') as stderr:
 try:r=subprocess.run(argv,input=json.dumps(payload).encode(),stdout=stdout,stderr=stderr,timeout=300);status=r.returncode
 except subprocess.TimeoutExpired:status=124
(root.parent/(name+'.status')).write_text(str(status)+'\n')
print('status',status,'evidence',name)
if status:print('Stop. Read evidence; remote outcome may need manual recovery. Do not advance to peer.')
raise SystemExit(status)
