"""Offline atomic replacement and hash-gate tests; no host contact."""
import importlib.util,os,tempfile,unittest,hashlib,subprocess,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('records',ROOT/'scripts/apply-host-records.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class Records(unittest.TestCase):
 def test_atomic_install_preserves_requested_metadata(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'config';p.write_bytes(b'original');m.install(p,b'candidate',os.getuid(),os.getgid(),0o640)
   self.assertEqual(p.read_bytes(),b'candidate');self.assertEqual(p.stat().st_mode&0o777,0o640)
   self.assertEqual(list(Path(d).iterdir()),[p])
 def test_failed_replace_preserves_original_and_removes_temp(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'config';p.write_bytes(b'original')
   with patch.object(m.os,'replace',side_effect=OSError('injected')):
    with self.assertRaises(OSError):m.install(p,b'candidate',os.getuid(),os.getgid(),0o600)
   self.assertEqual(p.read_bytes(),b'original');self.assertEqual(list(Path(d).iterdir()),[p])
 def test_drift_and_symlink_rejected(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'config';p.write_bytes(b'original');q=Path(d)/'link';q.symlink_to(p)
   with self.assertRaises(RuntimeError):m.verify_file(str(p),'0'*64)
   with self.assertRaises(RuntimeError):m.verify_file(str(q),m.sha(b'original'))
 def test_dispatch_rejects_wrong_authorization_before_ssh(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'dispatch.py').write_bytes((ROOT/'scripts/dispatch-host-records.py').read_bytes());(p/'SHA256SUMS').write_text('')
   r=subprocess.run([sys.executable,str(p/'dispatch.py'),'0'*64,'secondary','apply'],capture_output=True,text=True)
   self.assertNotEqual(r.returncode,0);self.assertIn('authorization_hash_mismatch',r.stderr)
class Settlement(unittest.TestCase):
 def run_health(self, sequence, settle=True, bad_peer=False, vip=False):
  clock=[0];samples=[0]
  def run(argv,**kwargs):
   if argv[0]=='ip':
    addresses=[{'addr_info':[{'local':'10.1.0.55'}]}] if vip else []
    return subprocess.CompletedProcess(argv,0,m.json.dumps(addresses),'')
   unit=argv[2]
   if unit=='unbound':samples[0]+=1
   state=sequence[min(samples[0]-1,len(sequence)-1)] if unit=='unbound' else ('failed' if bad_peer else 'active')
   return subprocess.CompletedProcess(argv,0,'Id='+unit+'.service\nActiveState='+state+'\nSubState='+('running' if state=='active' else 'reload')+'\nMainPID=123\nResult=success\n','')
  def sleep(seconds):clock[0]+=seconds
  with patch.object(m.subprocess,'run',side_effect=run),patch.object(m.time,'monotonic',side_effect=lambda:clock[0]),patch.object(m.time,'sleep',side_effect=sleep),patch.object(m,'event') as events:
   m.health({'owns_dns_vips':False},settle=settle)
   self.assertGreaterEqual(events.call_count,1)
  return samples[0],clock[0]
 def test_reload_then_two_active_samples(self):
  count,elapsed=self.run_health(['reloading','active','active'])
  self.assertEqual(count,3);self.assertEqual(elapsed,2)
 def test_flapping_restarts_stability_count(self):
  count,_=self.run_health(['active','reloading','active','active'])
  self.assertEqual(count,4)
 def test_permanent_reload_times_out(self):
  with self.assertRaisesRegex(RuntimeError,'deadline|timeout'):self.run_health(['reloading'])
 def test_failed_or_inactive_service_is_not_tolerated(self):
  for state in ['failed','inactive','activating','deactivating']:
   with self.subTest(state=state),self.assertRaisesRegex(RuntimeError,'service_unhealthy'):self.run_health([state])
 def test_peer_failure_and_vip_change_stop(self):
  with self.assertRaisesRegex(RuntimeError,'service_unhealthy'):self.run_health(['reloading'],bad_peer=True)
  with self.assertRaisesRegex(RuntimeError,'vip_role_changed'):self.run_health(['active'],vip=True)
 def test_preflight_does_not_allow_reload(self):
  with self.assertRaisesRegex(RuntimeError,'service_unhealthy'):self.run_health(['reloading'],settle=False)
 def test_cursor_banner_and_missing_cursor(self):
  self.assertEqual(m.journal_cursor('-- No entries --\n-- cursor: s=abc;i=1\n'),'s=abc;i=1')
  for text in ['-- No entries --','-- cursor: a\n-- cursor: b','-- cursor: ']:
   with self.assertRaises(RuntimeError):m.journal_cursor(text)
 def test_restore_verifies_backup_and_waits_for_reload(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);backup=p/'backup';backup.mkdir(mode=0o700);(backup/'original.conf').write_bytes(b'old');dest=p/'live';dest.write_bytes(b'new')
   before={'sha256':m.sha(b'old'),'uid':os.getuid(),'gid':os.getgid(),'mode':0o644}
   with patch.object(m,'command'),patch.object(m,'event'),patch.object(m,'health') as health:
    m.restore({},dest,backup,before,m.sha(b'new'));health.assert_called_once_with({},settle=True)
   self.assertEqual(dest.read_bytes(),b'old')
   dest.write_bytes(b'new')
   with patch.object(m,'command'),patch.object(m,'event'),patch.object(m,'health',side_effect=RuntimeError('settlement_failed')):
    with self.assertRaisesRegex(RuntimeError,'settlement_failed'):m.restore({},dest,backup,before,m.sha(b'new'))
   self.assertEqual(dest.read_bytes(),b'old')
   dest.write_bytes(b'third-party')
   with self.assertRaisesRegex(RuntimeError,'destination_drift'):m.restore({},dest,backup,before,m.sha(b'new'))
 def test_restore_reload_failure_is_not_success(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);backup=p/'backup';backup.mkdir(mode=0o700);(backup/'original.conf').write_bytes(b'old');dest=p/'live';dest.write_bytes(b'new')
   before={'sha256':m.sha(b'old'),'uid':os.getuid(),'gid':os.getgid(),'mode':0o644}
   with patch.object(m,'command',side_effect=['',RuntimeError('reload_failed')]),patch.object(m,'health') as health:
    with self.assertRaisesRegex(RuntimeError,'reload_failed'):m.restore({},dest,backup,before,m.sha(b'new'))
    health.assert_not_called()
   self.assertEqual(dest.read_bytes(),b'old')

class Transaction(unittest.TestCase):
 def test_apply_failure_restores_and_retains_recovery_failure(self):
  for recovery_fails in [False,True]:
   with self.subTest(recovery_fails=recovery_fails),tempfile.TemporaryDirectory() as d:
    root=Path(d);dest=root/'live';dest.write_bytes(b'old');dest.chmod(0o644);backup=root/'backup'
    metadata={'sha256':m.sha(b'old'),'uid':os.getuid(),'gid':os.getgid(),'mode':0o644}
    node={'hostname':'fixture','backup_directory':str(backup),'binaries':{},'sync_hashes':{},'owns_dns_vips':False,'files':{str(dest):metadata,'/etc/unbound/unbound.conf':{'sha256':'unused'}}}
    payload={'operation':{'nodes':{'secondary':node},'target_path':str(dest),'candidate_sha256':m.sha(b'new')},'node':'secondary','candidate':m.base64.b64encode(b'new').decode(),'expanded':m.base64.b64encode(b'fixture').decode(),'phase':'apply'}
    original_verify=m.verify_file
    def verify(path,digest):
     if path!='/etc/unbound/unbound.conf':original_verify(path,digest)
    def cmd(argv):
     if argv==['hostname']:return 'fixture'
     if argv[0]=='journalctl':return '-- No entries --\n-- cursor: s=fixture\n'
     return ''
    states=[None,RuntimeError('apply_settlement_failed'),RuntimeError('recovery_settlement_failed') if recovery_fails else None]
    with patch.object(m.os,'geteuid',return_value=0),patch.object(m.Path,'glob',return_value=[dest]),patch.object(m,'verify_file',side_effect=verify),patch.object(m,'command',side_effect=cmd),patch.object(m.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'',b'')),patch.object(m,'health',side_effect=states),patch.object(m,'event') as events:
     with self.assertRaisesRegex(RuntimeError,'rollback_unverified' if recovery_fails else 'apply_settlement_failed'):m.main(payload)
     names=[c.args[0] for c in events.call_args_list]
     self.assertIn('apply_failed',names)
     self.assertIn('manual_intervention' if recovery_fails else 'rollback_verified_file_and_services',names)
    self.assertEqual(dest.read_bytes(),b'old');self.assertEqual((backup/'original.conf').read_bytes(),b'old')
    self.assertEqual((backup/'journal-cursor.txt').read_text(),'s=fixture\n')

if __name__=='__main__':unittest.main()
