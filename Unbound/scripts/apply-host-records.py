"""Single-node transaction; controller must gate peer progression and global rollback."""
import base64,hashlib,json,os,stat,subprocess,sys,tempfile,time
from pathlib import Path

def sha(b):return hashlib.sha256(b).hexdigest()
def command(argv):
 p=subprocess.run(argv,capture_output=True,text=True,timeout=20)
 if p.returncode:raise RuntimeError('command_failed: '+argv[0]+': '+p.stderr[:1000])
 return p.stdout

def install(path,data,uid,gid,mode):
 fd,name=tempfile.mkstemp(prefix='.nautobot-dns-',dir=path.parent)
 try:
  with os.fdopen(fd,'wb') as f:
   os.fchown(f.fileno(),uid,gid);os.fchmod(f.fileno(),mode);f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(name,path)
 finally:
  if os.path.exists(name):os.unlink(name)

def verify_file(path,digest):
 p=Path(path)
 if not stat.S_ISREG(p.lstat().st_mode) or sha(p.read_bytes())!=digest:raise RuntimeError('file_drift: '+path)

def event(kind, **values):
 print(json.dumps({'event':kind,'epoch':time.time(),**values}),flush=True)

def journal_cursor(text):
 cursors=[line[len('-- cursor: '):] for line in text.splitlines() if line.startswith('-- cursor: ')]
 if len(cursors)!=1 or not cursors[0]:raise RuntimeError('missing_or_ambiguous_journal_cursor')
 return cursors[0]

def health(node, settle=False):
 deadline=time.monotonic()+(30 if settle else 20)
 stable=0
 while True:
  states={}
  for unit in ['unbound','pihole-FTL','keepalived']:
   remaining=deadline-time.monotonic()
   if remaining<=0:raise RuntimeError('health_deadline_exceeded')
   r=subprocess.run(['systemctl','show',unit,'-p','Id,ActiveState,SubState,MainPID,Result'],
                    capture_output=True,text=True,timeout=min(5,remaining))
   values=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
   states[unit]={'rc':r.returncode,**values}
  event('service_sample',settlement=settle,states=states)
  for unit,v in states.items():
   active=v.get('ActiveState');sub=v.get('SubState')
   running=active=='active' and sub=='running'
   transition=settle and unit=='unbound' and active=='reloading'
   if v['rc'] or not (running or transition) or not v.get('MainPID','0').isdigit() or int(v.get('MainPID','0'))<2 or v.get('Result')!='success':
    raise RuntimeError('service_unhealthy: '+unit+': '+json.dumps(v))
  remaining=deadline-time.monotonic()
  if remaining<=0:raise RuntimeError('health_deadline_exceeded')
  r=subprocess.run(['ip','-json','address'],capture_output=True,text=True,timeout=min(5,remaining))
  if r.returncode:raise RuntimeError('address_read_failed')
  addresses=json.loads(r.stdout)
  owned={a['local'] for i in addresses for a in i['addr_info']} & {'10.1.0.55','fd36:5aa8:6971:1::55'}
  expected={'10.1.0.55','fd36:5aa8:6971:1::55'} if node['owns_dns_vips'] else set()
  if owned!=expected:raise RuntimeError('vip_role_changed')
  stable=stable+1 if all(v.get('ActiveState')=='active' for v in states.values()) else 0
  if time.monotonic()>=deadline:raise RuntimeError('reload_settlement_timeout')
  if stable >= (2 if settle else 1):return
  time.sleep(min(1,max(0,deadline-time.monotonic())))

def restore(node,dest,backup,before,candidate_hash):
 if not backup.is_dir() or backup.is_symlink() or stat.S_IMODE(backup.stat().st_mode)!=0o700:raise RuntimeError('unsafe_backup')
 verify_file(str(backup/'original.conf'),before['sha256'])
 if not stat.S_ISREG(dest.lstat().st_mode):raise RuntimeError('unsafe_destination')
 if sha(dest.read_bytes()) not in [before['sha256'],candidate_hash]:raise RuntimeError('rollback_destination_drift')
 install(dest,(backup/'original.conf').read_bytes(),before['uid'],before['gid'],before['mode'])
 command(['unbound-checkconf','/etc/unbound/unbound.conf'])
 command(['unbound-control','reload'])
 health(node,settle=True)
 verify_file(str(dest),before['sha256'])
 event('rollback_verified_file_and_services',dns_verification_pending=True)

def main(payload):
 os.umask(0o077)
 op=payload['operation'];node=op['nodes'][payload['node']];dest=Path(op['target_path']);backup=Path(node['backup_directory']);before=node['files'][str(dest)];candidate=base64.b64decode(payload['candidate']);expanded=base64.b64decode(payload['expanded']);phase=payload['phase']
 if os.geteuid()!=0 or command(['hostname']).strip()!=node['hostname']:raise RuntimeError('identity_mismatch')
 if sha(candidate)!=op['candidate_sha256']:raise RuntimeError('candidate_hash')
 for f,v in node['binaries'].items():verify_file(v['path'],v['sha256'])
 for path,digest in node['sync_hashes'].items():verify_file(path,digest)
 actual={str(p) for p in Path('/etc/unbound/unbound.conf.d').glob('*.conf')}|{'/etc/unbound/unbound.conf'}
 if actual!=set(node['files']):raise RuntimeError('include_set_changed')
 for path,v in node['files'].items():
  if path!=str(dest):verify_file(path,v['sha256'])
 if phase=='rollback':
  restore(node,dest,backup,before,op['candidate_sha256'])
  print(json.dumps({'result':'rollback_applied_requires_DNS_verification','sha256':sha(dest.read_bytes())}));return
 if phase!='apply':raise RuntimeError('unknown_phase')
 health(node)
 command(['unbound-control','status'])
 verify_file(str(dest),before['sha256']);s=dest.stat()
 if (s.st_uid,s.st_gid,stat.S_IMODE(s.st_mode))!=(before['uid'],before['gid'],before['mode']):raise RuntimeError('metadata_drift')
 command(['unbound-checkconf','/etc/unbound/unbound.conf'])
 p=subprocess.run(['unbound-checkconf','/dev/stdin'],input=expanded,capture_output=True,timeout=20)
 if p.returncode:raise RuntimeError('candidate_validation_failed')
 backup.mkdir(mode=0o700,exist_ok=False)
 (backup/'original.conf').write_bytes(dest.read_bytes());os.chmod(backup/'original.conf',0o600)
 (backup/'before.json').write_text(json.dumps(before))
 (backup/'journal-cursor.txt').write_text(journal_cursor(command(['journalctl','-n','0','--show-cursor','--no-pager']))+'\n')
 changed=False
 try:
  verify_file(str(dest),before['sha256']);changed=True
  install(dest,candidate,before['uid'],before['gid'],before['mode'])
  command(['unbound-checkconf','/etc/unbound/unbound.conf']);command(['unbound-control','reload']);health(node,settle=True)
  verify_file(str(dest),op['candidate_sha256'])
  print(json.dumps({'result':'applied_requires_DNS_verification','backup':str(backup),'sha256':sha(dest.read_bytes())}))
 except Exception as original_error:
  event('apply_failed',error=str(original_error),mutation_attempted=changed)
  if changed:
   try:restore(node,dest,backup,before,op['candidate_sha256'])
   except Exception as rollback_error:
    event('manual_intervention',apply_error=str(original_error),rollback_error=str(rollback_error))
    raise RuntimeError('rollback_unverified') from rollback_error
  raise

if __name__=='__main__':main(json.loads(sys.stdin.read(1048576)))
