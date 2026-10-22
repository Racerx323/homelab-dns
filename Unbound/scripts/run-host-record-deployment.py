"""Verify a sealed DNS bundle and run one explicitly selected reviewed phase."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tarfile
import time

MEMBERS = {'runner.py', 'review.md', 'provenance.json', 'bundle/node.py',
    'bundle/dispatch.py', 'bundle/verify.py', 'bundle/operation.json',
    'bundle/candidate.conf', 'bundle/before.conf', 'bundle/known_hosts',
    'bundle/secondary-candidate-expanded.conf', 'bundle/primary-candidate-expanded.conf',
    'bundle/SHA256SUMS'}
PHASES = {'before': ('verify', 'before'), 'apply-secondary': ('dispatch', 'secondary', 'apply'),
    'after-secondary': ('verify', 'secondary'), 'apply-primary': ('dispatch', 'primary', 'apply'),
    'after-all': ('verify', 'all'), 'rollback-primary': ('dispatch', 'primary', 'rollback'),
    'rollback-secondary': ('dispatch', 'secondary', 'rollback'),
    'after-rollback-primary': ('verify', 'rollback-secondary'),
    'after-rollback-all': ('verify', 'rollback-all')}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def verify(directory, digest):
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError('private_owned_bundle_directory_required')
    raw = (directory/'deployment.tar').read_bytes()
    if len(raw) > 8388608 or sha(raw) != digest:
        raise ValueError('archive_hash_or_size_mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        entries = archive.getmembers()
        if (len(entries) != len(MEMBERS) or {m.name for m in entries} != MEMBERS
                or any(not m.isfile() or m.size > 1048576 for m in entries)):
            raise ValueError('closed_regular_archive_required')
        files = {m.name: archive.extractfile(m).read() for m in entries}
    for name, data in files.items():
        path = directory/name
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise ValueError('frozen_file_mismatch: '+name)
    if files['runner.py'] != Path(__file__).read_bytes():
        raise ValueError('frozen_runner_required')
    index = files['bundle/SHA256SUMS']
    expected = {name.removeprefix('bundle/'): sha(raw) for name, raw in files.items()
                if name.startswith('bundle/') and name != 'bundle/SHA256SUMS'}
    actual = {}
    for line in index.decode().splitlines():
        value, name = line.split('  ', 1)
        if name in actual:
            raise ValueError('duplicate_manifest_member')
        actual[name] = value
    if actual != expected:
        raise ValueError('index_binding_mismatch')
    operation = json.loads(files['bundle/operation.json'])
    if not operation['prepared_epoch'] <= time.time() < operation['expires_epoch']-300:
        raise ValueError('operation_expired_or_not_started')
    return operation, sha(index)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'step'))
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--phase', choices=PHASES)
    args = parser.parse_args()
    directory = args.directory.absolute()
    operation, index_sha = verify(directory, args.sha256)
    if args.action == 'check':
        print(json.dumps({'verified': True, 'target_contact': False, 'index_sha256': index_sha}))
        return
    if args.phase is None:
        parser.error('step requires --phase')
    if args.phase == 'apply-secondary':
        gate = json.loads((directory/'gate-before.json').read_text())
        if gate.get('owner') != operation['nodes']['primary']['hostname']:
            raise ValueError('initial_role_changed_stop_before_mutation')
    which, *arguments = PHASES[args.phase]
    argv = [sys.executable, '-I', '-B', str(directory/'bundle'/(which+'.py')), index_sha, *arguments]
    os.umask(0o077)
    with (directory/(args.phase+'-invocation.json')).open('x') as stream:
        json.dump({'archive_sha256': args.sha256, 'argv': argv, 'started_epoch': time.time()}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    with (directory/(args.phase+'-controller.log')).open('x') as log:
        row = subprocess.run(argv, stdout=log, stderr=subprocess.STDOUT)
    (directory/(args.phase+'-controller.exit')).write_text(str(row.returncode)+'\n')
    print(json.dumps({'phase': args.phase, 'exit': row.returncode,
                     'log': str(directory/(args.phase+'-controller.log'))}))
    raise SystemExit(row.returncode)


if __name__ == '__main__':
    main()
