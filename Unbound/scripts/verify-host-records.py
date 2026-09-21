"""Bounded DNS gates. Success does not authorize the next mutation."""
import json,subprocess,sys,time,re,ipaddress
from pathlib import Path
root=Path(__file__).resolve().parent
phase=sys.argv[1] if len(sys.argv)==2 else ''
endpoints={'secondary':['10.1.0.54','fd36:5aa8:6971:1::54'],'primary':['10.1.0.53','fd36:5aa8:6971:1::53'],'all':['10.1.0.53','fd36:5aa8:6971:1::53','10.1.0.54','fd36:5aa8:6971:1::54','10.1.0.55','fd36:5aa8:6971:1::55']}
if phase not in endpoints:raise SystemExit('usage: verify.py secondary|primary|all')
queries=[(['j2-svpi4mf.local.theama.co.','A'],'A','10.1.2.170'),(['j2-svpi4mf.local.theama.co.','AAAA'],'AAAA','fd36:5aa8:6971:1::170'),(['-x','10.1.2.170'],'PTR','j2-svpi4mf.local.theama.co.'),(['-x','fd36:5aa8:6971:1::170'],'PTR','j2-svpi4mf.local.theama.co.')]
results=[]
for endpoint in endpoints[phase]:
 for q,kind,expected in queries:
  r=subprocess.run(['dig','@'+endpoint,'+time=3','+tries=1','+noall','+answer','+comments']+q,capture_output=True,text=True,timeout=10)
  lines=[l.split() for l in r.stdout.splitlines() if l and not l.startswith(';')]
  good=r.returncode==0 and 'status: NOERROR' in r.stdout and len(lines)==1 and len(lines[0])==5 and lines[0][3]==kind
  owner=(ipaddress.ip_address(q[1]).reverse_pointer+'.') if q[0]=='-x' else q[0]
  good=good and lines[0][0].lower()==owner.lower()
  if good:
   actual=lines[0][4];good=(ipaddress.ip_address(actual)==ipaddress.ip_address(expected)) if kind!='PTR' else actual.lower()==expected
  results.append({'endpoint':endpoint,'query':q,'rc':r.returncode,'stdout':r.stdout,'stderr':r.stderr,'passed':bool(good)})
p=root.parent/(str(int(time.time()))+'-dns-'+phase+'.json');p.write_text(json.dumps(results,indent=2));p.chmod(0o600)
print('DNS rows passed',sum(x['passed'] for x in results),'of',len(results),'evidence',p)
raise SystemExit(0 if all(x['passed'] for x in results) else 1)
