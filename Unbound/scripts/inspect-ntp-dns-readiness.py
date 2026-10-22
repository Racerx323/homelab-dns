"""Seal separate read-only NTP-address and DNS-node prerequisite captures."""
import argparse
import base64
from datetime import datetime
import glob
import hashlib
import importlib.util
import io
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import stat
import subprocess
import tarfile
import time
import types
from zoneinfo import ZoneInfo

NAME = 'ntp1.local.theama.co.'
ADDRESSES = ('10.1.0.51', 'fd36:5aa8:6971:1::51')
VIPS = ('10.1.0.55', 'fd36:5aa8:6971:1::55')
FRAGMENT = '/etc/unbound/unbound.conf.d/pihole-local-zone.conf'
TARGETS = {
    'ntp': {'hostname': 'j2-svntp1', 'user': 'ama', 'alias': '10.1.0.137',
            'addresses': list(ADDRESSES), 'boot_id': '1c92f323-b8c9-428a-87e1-9c1394be8d91'},
    'dns53': {'hostname': 'j1-svpihole0', 'user': 'pi', 'alias': 'pihole0.local.theama.co',
              'addresses': ['10.1.0.53', 'fd36:5aa8:6971:1::53'], 'boot_id': None},
    'dns54': {'hostname': 'j1-svpihole00', 'user': 'pi', 'alias': 'pihole00.local.theama.co',
              'addresses': ['10.1.0.54', 'fd36:5aa8:6971:1::54'], 'boot_id': None},
}
MEMBERS = {'runner.py', 'helper.py', 'tests.py', 'candidate.conf', 'known_hosts', 'spec.json', 'review.md'}
ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C'}
h = None


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True)+'\n').encode()


def write(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())


def read_file(path):
    """Stable bounded protected regular file, without links or writable ancestry."""
    path = Path(path)
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('unprotected file ancestry')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_uid != 0 or before.st_mode & 0o022 or before.st_size > 1048576:
            raise ValueError('protected bounded regular file required')
        raw = stream.read(1048577); after = os.fstat(stream.fileno())
    keys = ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    same = lambda info: tuple(getattr(info, k) for k in keys)
    if len(raw) > 1048576 or same(before) != same(after) or same(after) != same(path.lstat()):
        raise ValueError('file changed during read')
    return raw, {'sha256': sha(raw), 'uid': after.st_uid, 'gid': after.st_gid,
        'mode': stat.S_IMODE(after.st_mode), 'size': after.st_size, 'inode': after.st_ino,
        'device': after.st_dev, 'mtime_ns': after.st_mtime_ns}


def probe(argv, timeout=8, payload=None, limit=65536):
    try:
        return h.bounded(argv, timeout=timeout, limit=limit, payload=payload, env=ENV)
    except OSError as error:
        return {'argv': argv, 'returncode': None, 'error': type(error).__name__}


def required(argv):
    row = probe(argv)
    if row.get('returncode') != 0 or row.get('error'):
        raise ValueError('required read-only command unavailable')
    return row['stdout']


def unit(name):
    return required(['/usr/bin/systemctl', 'show', name,
        '--property=LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts,FragmentPath,DropInPaths'])


def properties(raw):
    return dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)


def host_identity(spec):
    actual = {'hostname': socket.gethostname().split('.')[0],
              'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip()}
    target = spec['target']
    if os.geteuid() != 0 or actual['hostname'] != target['hostname'] or (target['boot_id'] and actual['boot_id'] != target['boot_id']):
        raise ValueError('root/hostname/boot identity mismatch')
    return actual


def address_checks(rows):
    entries = {a['local']: a for row in rows for a in row.get('addr_info', [])}
    return {str(version): (address in entries and entries[address].get('prefixlen') == prefix
            and not entries[address].get('tentative') and not entries[address].get('dadfailed')
            and (version != 6 or not (entries[address].get('dynamic') or entries[address].get('temporary'))))
            for version, address, prefix in ((4, ADDRESSES[0], 22), (6, ADDRESSES[1], 64))}


def collect_ntp(spec, result):
    before = unit('timeservice.service')
    result['service_before'] = before
    result['addresses'] = json.loads(required(['/usr/sbin/ip', '-j', 'address', 'show', 'dev', 'eth0']))
    result['address_checks'] = address_checks(result['addresses'])
    result['routes'] = {str(family): probe(['/usr/sbin/ip', '-'+str(family), '-j', 'route', 'get', address])
                        for family, address in zip((4, 6), VIPS)}
    result['default_routes'] = {str(family): probe(['/usr/sbin/ip', '-'+str(family), '-j', 'route', 'show', 'default', 'dev', 'eth0'])
                                for family in (4, 6)}
    result['ntp_listeners'] = probe(['/usr/bin/ss', '-H', '-lun', '( sport = :123 )'])
    active = required(['/usr/bin/nmcli', '-t', '-f', 'UUID,DEVICE', 'connection', 'show', '--active'])
    selected = [line.partition(':')[0] for line in active.splitlines() if line.endswith(':eth0')]
    if len(selected) != 1 or not re.fullmatch(r'[0-9a-f-]{36}', selected[0]):
        raise ValueError('one active Ethernet UUID required')
    result['profile_address_settings'] = probe(['/usr/bin/nmcli', '-m', 'multiline', '-f',
        'connection.uuid,connection.interface-name,ipv4.method,ipv4.addresses,ipv6.method,ipv6.addresses',
        'connection', 'show', selected[0]])
    filenames = required(['/usr/bin/nmcli', '-t', '-f', 'UUID,FILENAME', 'connection', 'show'])
    selected_files = [line.partition(':')[2] for line in filenames.splitlines() if line.partition(':')[0] == selected[0]]
    if len(selected_files) != 1 or not re.fullmatch(r'/etc/NetworkManager/system-connections/[^/\r\n]{1,160}\.nmconnection', selected_files[0]):
        raise ValueError('protected persistent Ethernet profile required')
    result['profile_metadata'] = {'path': selected_files[0], 'metadata': read_file(selected_files[0])[1]}
    result['ntp_config_metadata'] = read_file('/etc/ntp.conf')[1]
    result['service_after'] = unit('timeservice.service')
    if (before != result['service_after']
            or read_file(selected_files[0])[1] != result['profile_metadata']['metadata']):
        raise ValueError('time-service identity changed during read-only capture')
    result['service_active'] = properties(before).get('ActiveState') == 'active'
    result['address_readiness_observed'] = all(result['address_checks'].values()) and result['service_active']


def ntp_candidate(raw):
    """Require an isolated server/local-record fragment; append only absent NTP records."""
    text = raw.decode()
    forward, reverse = {}, {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or stripped == 'server:':
            continue
        if re.fullmatch(r'local-zone:\s+"[a-zA-Z0-9_.-]+"\s+(?:static|transparent)', stripped):
            continue
        if re.fullmatch(r'(?:private-domain|domain-insecure):\s+"[a-zA-Z0-9_.-]+"', stripped):
            continue
        match = re.fullmatch(r'local-data:\s+"([^"\r\n]+)"', stripped)
        ptr = re.fullmatch(r'local-data-ptr:\s+"([^"\r\n]+)"', stripped)
        if match:
            fields = match[1].split()
            if 'IN' not in fields or fields.index('IN') not in (1, 2) or fields[fields.index('IN')+1:fields.index('IN')+2] not in (
                    ['A'], ['AAAA'], ['CNAME'], ['PTR'], ['SRV'], ['MX'], ['NS']):
                raise ValueError('unsupported local record type; no full fragment export')
            if NAME in fields:
                if len(fields) != 4 or fields[0] != NAME or fields[1] != 'IN' or fields[2] not in ('A', 'AAAA'):
                    raise ValueError('unexpected NTP forward record form')
                forward.setdefault(fields[2], []).append(fields[3])
        elif ptr:
            fields = ptr[1].split()
            if fields and fields[0] in ADDRESSES:
                reverse.setdefault(fields[0], []).append(fields[1:] if len(fields) != 2 else fields[1])
        else:
            raise ValueError('local-zone fragment has unsupported directives')
    if forward.get('A') != [ADDRESSES[0]] or reverse.get(ADDRESSES[0]) != [NAME]:
        raise ValueError('preserved NTP IPv4 baseline is not exact')
    additions = []
    for values, expected, line in (
            (forward.get('AAAA', []), ADDRESSES[1], '    local-data: "'+NAME+' IN AAAA '+ADDRESSES[1]+'"'),
            (reverse.get(ADDRESSES[1], []), NAME, '    local-data-ptr: "'+ADDRESSES[1]+' '+NAME+'"')):
        if values and values != [expected]:
            raise ValueError('conflicting or duplicate NTP IPv6 record')
        if not values:
            additions.append(line)
    candidate = raw
    if additions:
        candidate += (b'\n' if raw and not raw.endswith(b'\n') else b'')+('\n'.join(additions)+'\n').encode()
    return candidate, additions


def config_graph(root=Path('/etc/unbound/unbound.conf'), replacement=None):
    """Expand only protected includes beneath /etc/unbound; refuse unresolved graphs."""
    files, edges, stack = {}, [], set()
    def visit(path):
        path = Path(os.path.abspath(path))
        if not path.is_relative_to('/etc/unbound') or path.suffix != '.conf' or path in stack or len(files) >= 64:
            raise ValueError('include root, cycle or file-count bound')
        raw, meta = read_file(path)
        if b'PRIVATE KEY' in raw:
            raise ValueError('private key material is not configuration input')
        if sum(row['metadata']['size'] for row in files.values())+len(raw) > 4194304:
            raise ValueError('include byte bound')
        files[str(path)] = {'metadata': meta}
        stack.add(path)
        output = []
        lines = raw.decode().splitlines(keepends=True)
        pure_root_includes = path == root and all(not line.strip() or line.lstrip().startswith('#')
            or re.match(r'^\s*include(?:-toplevel)?:', line) for line in lines)
        for line in lines:
            if re.match(r'^\s*include(?:-toplevel)?:', line):
                match = re.fullmatch(r'\s*(include(?:-toplevel)?):\s*"([^"\r\n]+)"\s*(?:#[^\r\n]*)?\s*', line)
                if (not match or not match[2].startswith('/etc/unbound/')
                        or (match[1] == 'include-toplevel' and not pure_root_includes)):
                    raise ValueError('unsupported include syntax/context')
                paths = sorted(glob.glob(match[2]))
                if not paths or len(paths) > 64:
                    raise ValueError('include absent or exceeds bound')
                for name in paths:
                    edges.append({'parent': str(path), 'child': name})
                    content = visit(name)
                    if match[1] == 'include-toplevel':
                        first = next((item.strip() for item in content.splitlines() if item.strip() and not item.lstrip().startswith('#')), '')
                        if first and not re.fullmatch(r'(?:server|remote-control|forward-zone|stub-zone|auth-zone|view|python|dynlib|cachedb|dnscrypt|dnstap|rpz):', first):
                            raise ValueError('top-level include must start a section')
                    output.append(content)
            else:
                output.append(line)
        stack.remove(path)
        return replacement.decode() if replacement is not None and str(path) == FRAGMENT else ''.join(output)
    expanded = visit(root).encode()
    if len(expanded) > 4194304:
        raise ValueError('expanded configuration byte bound')
    return expanded, files, edges


def sync_projection():
    """Bounded writer hints; never claim this projection proves no other writers."""
    result = {'complete_writer_proof': False, 'files': {}, 'units': {}}
    for name in ('/etc/lsyncd/lsyncd.conf.lua', '/etc/lsyncd/caddy.lua', '/etc/gravity-sync/gravity-sync.conf', '/etc/crontab'):
        try:
            raw, meta = read_file(name)
            result['files'][name] = {'metadata': meta, 'mentions': [term for term in
                ('/etc/unbound', 'pihole-local-zone.conf', '/etc/pihole', 'gravity-sync', 'rsync', 'lsyncd') if term.encode() in raw]}
        except (OSError, ValueError) as error:
            result['files'][name] = {'unavailable': type(error).__name__}
    listing = probe(['/usr/bin/systemctl', 'list-unit-files', '--no-legend', '--no-pager'])
    names = sorted({line.split()[0] for line in listing.get('stdout', '').splitlines()
                    if line.split() and re.fullmatch(r'[a-zA-Z0-9@_.-]+\.(?:service|timer|path)', line.split()[0])
                    and re.search(r'lsyncd|gravity-sync|pihole.*sync|sync.*dns|unbound.*sync', line.split()[0], re.I)})
    if len(names) > 16:
        raise ValueError('synchronization unit bound')
    for name in names:
        result['units'][name] = probe(['/usr/bin/systemctl', 'show', name,
            '--property=LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts,FragmentPath,DropInPaths'])
    result['unit_listing_status'] = {k: v for k, v in listing.items() if k not in ('stdout', 'stderr')}
    return result


def dns_queries(addresses):
    rows = []
    endpoints = [('127.0.0.1', '5335'), ('::1', '5335')]+[(a, '53') for a in (*addresses, *VIPS)]
    for server, port in endpoints:
        for query, kind in ((NAME, 'A'), (NAME, 'AAAA'),
                            (ipaddress.ip_address(ADDRESSES[0]).reverse_pointer+'.', 'PTR'),
                            (ipaddress.ip_address(ADDRESSES[1]).reverse_pointer+'.', 'PTR')):
            rows.append(probe(['/usr/bin/dig', '-r', '@'+server, '-p', port, query, kind,
                '+time=2', '+tries=1', '+ignore', '+nosearch', '+nocookie', '+noall', '+comments', '+answer', '+stats'], timeout=3))
    return rows


def collect_dns(spec, result):
    services = ('unbound.service', 'pihole-FTL.service', 'keepalived.service')
    result['services_before'] = {name: unit(name) for name in services}
    addresses = json.loads(required(['/usr/sbin/ip', '-j', 'address', 'show']))
    current = {a['local'] for row in addresses for a in row.get('addr_info', [])}
    result['addresses'] = addresses
    result['vip_ownership'] = {a: a in current for a in VIPS}
    result['mixed_vip_ownership'] = len(set(result['vip_ownership'].values())) != 1
    raw, meta = read_file(FRAGMENT)
    candidate, additions = ntp_candidate(raw)
    result['fragment'] = {'metadata': meta, 'base64': base64.b64encode(raw).decode()}
    result['candidate_additions'] = additions
    expanded, files, edges = config_graph()
    proposed, candidate_files, candidate_edges = config_graph(replacement=candidate)
    if (files != candidate_files or edges != candidate_edges or FRAGMENT not in files
            or sum(edge['child'] == FRAGMENT for edge in edges) != 1):
        raise ValueError('effective include graph drift or missing fragment')
    # A relevant record elsewhere may conflict; preserve selected lines for review.
    relevant = {}
    for name in files:
        text = read_file(name)[0].decode()
        selected = [line.strip() for line in text.splitlines() if re.match(r'^\s*local-(?:data|data-ptr|zone):', line)
                    and any(term in line for term in ('ntp1.local.theama.co', *ADDRESSES, 'local.theama.co'))]
        relevant[name] = selected
    result.update(config_files=files, include_edges=edges, relevant_records=relevant,
        effective_sha256=sha(expanded), candidate_effective_sha256=sha(proposed))
    result['native_validation'] = {'original': probe(['/usr/sbin/unbound-checkconf', '/etc/unbound/unbound.conf']),
                                   'candidate_in_memory': probe(['/usr/sbin/unbound-checkconf', '/dev/stdin'], payload=proposed)}
    result['version'] = probe(['/usr/sbin/unbound', '-V'])
    result['control_help'] = probe(['/usr/sbin/unbound-control', '-h'])
    reload_row = probe(['/usr/bin/systemctl', 'show', 'unbound.service', '--property=ExecReload'])
    reload_text = reload_row.get('stdout', '')
    result['reload_projection'] = {'returncode': reload_row.get('returncode'), 'sha256': sha(reload_text.encode()),
        'mentions_unbound_control_reload': 'unbound-control' in reload_text and 'reload' in reload_text}
    result['pihole_source'] = {}
    for name in ('/usr/local/bin/pihole', '/opt/pihole/pihole', '/etc/pihole/versions'):
        try:
            source, info = read_file(name)
            result['pihole_source'][name] = {'metadata': info,
                'restartdns_mentioned': b'restartdns' in source, 'restartDNS_mentioned': b'restartDNS' in source}
            if name.endswith('/versions'):
                result['pihole_source'][name]['selected_versions'] = [line for line in source.decode().splitlines()
                    if re.fullmatch(r'(?:CORE|WEB|FTL)_(?:VERSION|BRANCH|HASH)=[a-zA-Z0-9_.v/=-]{1,160}', line)]
        except (OSError, ValueError) as error:
            result['pihole_source'][name] = {'unavailable': type(error).__name__}
    result['pihole_git'] = {label: probe(['/usr/bin/git', '--no-optional-locks', '--no-pager',
        '-c', 'core.fsmonitor=false', '-C', '/etc/.pihole', *argv]) for label, argv in
        (('commit', ['rev-parse', '--verify', 'HEAD']), ('tag', ['describe', '--tags', '--exact-match', 'HEAD']))}
    result['synchronization'] = sync_projection()
    result['dns_queries'] = dns_queries(spec['target']['addresses'])
    result['services_after'] = {name: unit(name) for name in services}
    if result['services_before'] != result['services_after']:
        raise ValueError('DNS service identity drift during capture')
    after_addresses = json.loads(required(['/usr/sbin/ip', '-j', 'address', 'show']))
    after_local = {a['local'] for row in after_addresses for a in row.get('addr_info', [])}
    result['vip_ownership_after'] = {a: a in after_local for a in VIPS}
    if result['vip_ownership_after'] != result['vip_ownership']:
        raise ValueError('DNS VIP ownership drift during capture')
    if result['mixed_vip_ownership']:
        result['findings'].append('Mixed DNS VIP ownership requires a hold before deployment.')
    for name, record in files.items():
        if read_file(name)[1] != record['metadata']:
            raise ValueError('effective configuration file drift during capture')
    final_expanded, final_files, final_edges = config_graph()
    if final_files != files or final_edges != edges or final_expanded != expanded:
        raise ValueError('effective include graph changed during capture')
    result['findings'].extend(['Synchronization projection is incomplete; establish all writers before deployment.',
        'Restartdns token/version evidence requires supported full restart-path qualification before deployment.',
        'Other effective includes and current answers require conflict review; no deployment is authorized.'])


# Qualification reads are a separate sealed scope; never execute inspected code.
CONTROL_BOOTS = {'dns53': '9b60a085-23f0-4cf1-b5a7-5248b6a75441',
                 'dns54': '09926606-ef4a-400c-b097-d5b8f222c1b5'}
CONTROL_ROOTS = ('/opt/pihole', '/opt/gravity-sync')
CONTROL_FILES = ('/usr/local/bin/pihole', '/usr/local/bin/gravity-sync',
                 '/etc/gravity-sync/gravity-sync.conf', '/etc/pihole/versions',
                 '/etc/lsyncd/lsyncd.conf.lua', '/etc/lsyncd/caddy.lua',
                 '/usr/lib/unbound/package-helper', '/etc/init.d/unbound', '/etc/init.d/pihole-FTL',
                 '/etc/crontab', '/var/spool/cron/crontabs/root', '/var/spool/cron/crontabs/pi')


def expected_target(mode, qualification=False):
    target = dict(TARGETS[mode])
    if qualification:
        if mode not in CONTROL_BOOTS:
            raise ValueError('qualification is DNS-only')
        target['boot_id'] = CONTROL_BOOTS[mode]
    return target


def control_read(path):
    """Bounded read allowing the named pi owner; no writable-by-others ancestry."""
    import pwd
    path = Path(path)
    lexical = str(path)
    if not (lexical in CONTROL_FILES or any(lexical.startswith(r+'/') for r in
            (*CONTROL_ROOTS, '/etc/cron.d', '/etc/cron.daily', '/etc/cron.hourly',
             '/etc/cron.weekly', '/etc/cron.monthly'))):
        raise ValueError('outside qualification file scope')
    allowed = {0, pwd.getpwnam('pi').pw_uid}
    # A single explicit launcher link may resolve only into its code tree.
    if path.is_symlink():
        resolved = path.resolve(strict=True)
        if lexical not in ('/usr/local/bin/pihole', '/usr/local/bin/gravity-sync') or not any(
                str(resolved).startswith(r+'/') for r in CONTROL_ROOTS):
            raise ValueError('unsupported qualification symlink')
        path = resolved
    for parent in path.parents:
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid not in allowed or info.st_mode & 0o022:
            raise ValueError('unsafe qualification ancestry')
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_uid not in allowed or before.st_mode & 0o022 or before.st_size > 1048576:
            raise ValueError('unsafe qualification regular file')
        raw = stream.read(1048577); after = os.fstat(stream.fileno())
    fields = ('st_dev', 'st_ino', 'st_uid', 'st_gid', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    if len(raw) > 1048576 or any(getattr(before, k) != getattr(after, k) or
            getattr(after, k) != getattr(path.lstat(), k) for k in fields):
        raise ValueError('qualification file changed')
    return raw, {'resolved_path': str(path), 'sha256': sha(raw), 'uid': after.st_uid,
                 'gid': after.st_gid, 'mode': stat.S_IMODE(after.st_mode), 'size': len(raw)}


def control_projection(raw, code=False):
    """Export code with sensitive lines redacted; configs expose only bounded path tokens."""
    text = raw.decode('utf-8')
    paths = sorted(set(re.findall(r'/(?:etc|opt|usr|var)/(?:[A-Za-z0-9_.*/-]+)', text)))
    result = {'paths': [p for p in paths if not re.search(r'key|secret|password|token|credential', p, re.I)],
              'features': [term for term in ('restartdns', 'restartDNS', 'pihole-FTL', 'unbound',
                 'reload', 'restart', 'rsync', 'lsyncd', 'gravity-sync', '--exclude', '--delete',
                 'push', 'pull', 'sudo', 'systemctl', 'service') if term in text]}
    result['rsync_options'] = sorted(set(re.findall(r'--(?:exclude|include|delete|delete-excluded|archive|recursive|links|perms|owner|group|times|compress|dry-run)(?:[= ](?:/etc/(?:unbound|pihole)[A-Za-z0-9_./*-]*))?', text)))
    result['schedule_prefixes'] = [{'line': n, 'schedule': m[0]} for n, line in enumerate(text.splitlines(), 1)
        if not line.lstrip().startswith('#') and (m := re.match(r'(?:@[a-z]+|(?:[0-9*/,-]+[ \t]+){4}[0-9*/,-]+)', line))]
    # Only named non-secret sync fields; never return arbitrary config lines.
    result['selected_settings'] = []
    for number, line in enumerate(text.splitlines(), 1):
        if re.fullmatch(r'\s*(?:GS_SYNC_CUSTOM|GS_SYNC_AD_LIST|GS_SYNC_REGEX|GS_SYNC_EXACT|GS_SYNC_CLIENTS|GS_SYNC_DNS|GS_SYNC_DHCP|GS_SYNC_PIHOLE|GS_SYNC_GRAVITY|GS_SYNC_RELOAD|GS_SYNC_RESTART|SKIP_CUSTOM|SKIP_LOCAL_DNS|SKIP_DHCP|SKIP_RESTART|SKIP_FTL|SKIP_GRAVITY|INCLUDE_GRAVITY|REMOTE_USER|REMOTE_IP|REMOTE_HOST|REMOTE_PORT|GS_REMOTE_USER|GS_REMOTE_HOST|CORE_VERSION|WEB_VERSION|FTL_VERSION|CORE_HASH|WEB_HASH|FTL_HASH)=[\"\x27]?[A-Za-z0-9_.:/-]{1,160}[\"\x27]?\s*', line):
            result['selected_settings'].append({'line': number, 'text': line.strip()})
    if code:
        result['source_lines'] = [{'line': number, 'text': '[REDACTED]' if re.search(
            r'password|passwd|secret|token|credential|private.?key|https?://|Environment(?:File)?=|(?:^|\s)(?:export\s+)?[A-Z_]*(?:PASS|KEY)[A-Z_]*=', line, re.I) else line}
            for number, line in enumerate(text.splitlines(), 1)]
    return result


def collect_controls(spec, result):
    services = ('unbound.service', 'pihole-FTL.service', 'keepalived.service')
    result['services_before'] = {name: unit(name) for name in services}
    addresses = required(['/usr/sbin/ip', '-j', 'address', 'show'])
    result['addresses_before'] = json.loads(addresses)
    raw, metadata = read_file(FRAGMENT)
    result['fragment_metadata'] = metadata
    expanded, config_files, edges = config_graph()
    result['effective_config'] = {'sha256': sha(expanded), 'files': config_files, 'include_edges': edges}
    result['remote_control_settings'] = [line.strip() for line in expanded.decode().splitlines()
        if re.fullmatch(r'\s*(?:control-enable|control-interface|control-port|control-use-cert):\s*[a-zA-Z0-9:./_-]+\s*', line)]
    try:
        result['unbound_control_binary'] = {'metadata': read_file('/usr/sbin/unbound-control')[1]}
    except (OSError, ValueError) as error:
        # This optional binary hash must not discard unrelated control-path reads.
        diagnostic = {'unavailable': type(error).__name__}
        try:
            info = Path('/usr/sbin/unbound-control').lstat()
            diagnostic['lstat'] = {'uid': info.st_uid, 'gid': info.st_gid,
                'mode': stat.S_IMODE(info.st_mode), 'size': info.st_size,
                'regular': stat.S_ISREG(info.st_mode), 'symlink': stat.S_ISLNK(info.st_mode)}
        except OSError as stat_error:
            diagnostic['lstat_unavailable'] = type(stat_error).__name__
        result['unbound_control_binary'] = diagnostic
        result['findings'].append('Unbound-control binary hash unavailable under protected-file policy; metadata is diagnostic only. Control-path qualification remains subject to review.')
    result['control_units'] = {}
    result['sync_unit_discovery'] = sync_projection()
    units = sorted(set((*services, 'gravity-sync.service', 'gravity-sync.timer', 'lsyncd.service', 'lsyncd-caddy.service', *result['sync_unit_discovery']['units'])))
    for name in units:
        row = probe(['/usr/bin/systemctl', 'cat', '--no-pager', name])
        result['control_units'][name] = {'returncode': row.get('returncode'), 'error': row.get('error'),
            'projection': control_projection(row.get('stdout', '').encode(), code=True)}
        result['control_units'][name]['state'] = probe(['/usr/bin/systemctl', 'show', name,
            '--property=LoadState,ActiveState,SubState,MainPID,InvocationID,NRestarts,FragmentPath,DropInPaths,LastTriggerUSec,NextElapseUSecRealtime'])
    paths = set(CONTROL_FILES)
    for root in CONTROL_ROOTS:
        for pattern in ('*.sh', '*/*.sh'):
            paths.update(glob.glob(root+'/'+pattern))
    for root in ('/etc/cron.d', '/etc/cron.daily', '/etc/cron.hourly', '/etc/cron.weekly', '/etc/cron.monthly'):
        paths.update(glob.glob(root+'/*'))
    if len(paths) > 128:
        raise ValueError('qualification file count bound')
    result['control_files'] = {}; total = 0; captured = {}
    for name in sorted(paths):
        try:
            raw, meta = control_read(name); total += len(raw)
            if total > 8388608:
                raise RuntimeError('qualification aggregate byte bound')
            code = (name in ('/usr/local/bin/pihole', '/usr/local/bin/gravity-sync') or
                    name.endswith('.sh') or name.startswith('/etc/init.d/') or name == '/usr/lib/unbound/package-helper' or '/cron' in name or name.endswith('.lua'))
            # Never export full cron/Lua configuration: path/feature projections only.
            code = code and not ('/cron' in name or name.endswith('.lua'))
            result['control_files'][name] = {'metadata': meta, 'projection': control_projection(raw, code)}
            captured[name] = meta
        except (OSError, ValueError, UnicodeError) as error:
            info = None
            try:
                st = Path(name).lstat()
                info = {'uid': st.st_uid, 'gid': st.st_gid, 'mode': stat.S_IMODE(st.st_mode),
                        'symlink': stat.S_ISLNK(st.st_mode), 'size': st.st_size}
            except OSError:
                pass
            result['control_files'][name] = {'unavailable': type(error).__name__, 'metadata': info}
    for name in units:
        row = probe(['/usr/bin/systemctl', 'cat', '--no-pager', name])
        projection = control_projection(row.get('stdout', '').encode(), code=True)
        if row.get('returncode') != result['control_units'][name]['returncode'] or row.get('error') != result['control_units'][name]['error'] or projection != result['control_units'][name]['projection']:
            raise ValueError('unit source changed during qualification')
    result['services_after'] = {name: unit(name) for name in services}
    result['addresses_after'] = json.loads(required(['/usr/sbin/ip', '-j', 'address', 'show']))
    if result['services_before'] != result['services_after']:
        raise ValueError('DNS service identity drift')
    owned = lambda rows: sorted(a['local'] for row in rows for a in row.get('addr_info', []) if a['local'] in VIPS)
    if owned(result['addresses_before']) != owned(result['addresses_after']):
        raise ValueError('DNS VIP ownership drift')
    result['vip_ownership'] = {a: a in owned(result['addresses_after']) for a in VIPS}
    if read_file(FRAGMENT)[1] != metadata:
        raise ValueError('DNS fragment drift')
    final_expanded, final_config_files, final_edges = config_graph()
    if expanded != final_expanded or config_files != final_config_files or edges != final_edges:
        raise ValueError('effective configuration drift')
    for name, meta in captured.items():
        if control_read(name)[1] != meta:
            raise ValueError('qualification source drift')
    result['findings'].append('Human code-path review required; redacted, unavailable, dynamic or unenumerated inputs remain holds. No control was invoked; no runtime restart/reload or comprehensive writer isolation is accepted.')


def controls_review(spec):
    t = spec['target']
    return f'''# Read-only DNS control and synchronization qualification

Operation `{spec['operation_id']}`; archive SHA-256 is in sealing.json.
Expires {datetime.fromtimestamp(spec['expires_epoch'], ZoneInfo('America/Chicago')).isoformat()}.
Target: {t['user']}@{t['addresses'][0]}, pinned alias {t['alias']},
hostname {t['hostname']}, boot {t['boot_id']}.
One IPv4 SSH capture to this node only; no peer progression or automatic retry.

Read current Unbound/Pi-hole/Keepalived identities and VIP ownership before/after;
read local-zone/effective include graph hash/metadata with stability checks and
selected non-secret control-enable/interface/port/use-cert values. Read only
unbound-control binary hash/metadata; do not invoke it or read control keys.
If its protected bounded read is unavailable, record the error and lstat-only
type/owner/mode/size (no link following) and continue independent reads. This
does not waive protection or accept the binary; unresolved findings hold deployment. Read systemctl cat
and selected show properties for those units and gravity-sync service/timer,
lsyncd and lsyncd-caddy, plus at most 16 discovered synchronization service/timer/path
units matching the existing bounded name filter. Compare sanitized unit source
before/after. Unit source is sanitized before export: environment,
credential, URL and sensitive lines are redacted. Never read referenced keys,
EnvironmentFiles, setupVars or arbitrary executable dependencies.

Read fixed Pi-hole/Gravity Sync launchers and shell source up to one directory
below /opt/pihole and /opt/gravity-sync, /usr/lib/unbound/package-helper and
/etc/init.d/unbound and /etc/init.d/pihole-FTL; no execution, sourcing or shell tracing.
Inspect /etc/gravity-sync/gravity-sync.conf, /etc/pihole/versions, fixed lsyncd
configs, /etc/crontab, root/pi crontabs and immediate entries under cron.d,
cron.daily/hourly/weekly/monthly. Configs and schedules export path/feature tokens
schedule prefixes, selected rsync options and explicitly allowlisted non-secret settings only; no raw config values or
cron commands. Shell code exports line-numbered source with sensitive lines
redacted. No SSH keys, control keys, passwords or arbitrary home directories.

Files must be regular, bounded and root/pi-owned with ancestry not writable by
others. Only the two explicit launcher symlinks may resolve into the approved
code roots. Unsupported ownership, links, redactions and dynamic dependencies
remain findings, not missing-file assumptions or writer-isolation acceptance.
Up to 128 paths, 1 MiB/file, 8 MiB aggregate; commands eight seconds/64 KiB per
stream; remote deadline 240 seconds, controller 270 seconds/16 MiB streams.
Strict established Ed25519 key, no TOFU/proxy/forwarding/connection sharing.
Private frozen archive/member/hash/expiry checks and exclusive one-use receipt
precede contact. Partial results remain private; a consumed receipt cannot replay.

Assess actual Unbound reload implementation and Pi-hole full restart chain,
sync push/pull/defaults/custom DNS exclusions and affected paths/schedulers.
Both node results must be reviewed together. Source evidence alone does not
exercise runtime controls or prove all writers absent. Unresolved code paths,
redacted arguments, source drift or serial-change isolation hold deployment.
The local-zone guide and DNS AGENTS.md require Unbound validation/reload then
full Pi-hole DNS restart after every deployment and rollback; cache-only reload
is insufficient. Runtime testing belongs to a separately approved deployment.

No reload, restart, status control request, sync run/pause, configuration write,
DNS query, native checker, package action, failover, notification or cleanup.
SSH/sudo can write normal audit logs. No target staging; Python runs in memory
with isolated imports and bytecode disabled. No restoration is necessary.
Historical capture data supplies identities only; frozen helper source comes
from homelab-ntp/ntpsec/scripts/run-production-inspection.py.

After approval of this exact archive hash:

```bash
python3 -I -B DIRECTORY/runner.py execute --directory DIRECTORY --sha256 APPROVED_SHA256
```

Preparation authorizes no target contact. Execution requires separate exact-hash
approval under the DNS prerequisite review and staged-operation governance.
'''


def collect(spec):
    result = {'operation_id': spec['operation_id'], 'spec_sha256': sha(encoded(spec)),
              'capture_complete': False, 'target_mutation': False, 'deployment_accepted': False, 'findings': []}
    try:
        result['identity_before'] = host_identity(spec)
        if spec.get('qualification'):
            collect_controls(spec, result)
        elif spec['mode'] == 'ntp':
            collect_ntp(spec, result)
        else:
            collect_dns(spec, result)
        result['identity_after'] = host_identity(spec)
        if result['identity_before'] != result['identity_after']:
            raise ValueError('host/boot changed during capture')
        result['capture_complete'] = True
    except Exception as error:
        result['error_type'] = type(error).__name__
        result['error'] = str(error) if isinstance(error, ValueError) else 'required capture input unavailable'
    except h.CaptureDeadline:
        result['error'] = 'remote capture deadline exceeded'
    return result


def review(spec):
    if spec.get('qualification'):
        return controls_review(spec)
    target = spec['target']
    role = 'NTP address' if spec['mode'] == 'ntp' else 'DNS node'
    return f'''# Read-only {role} readiness inspection

Operation `{spec['operation_id']}`; expires
{datetime.fromtimestamp(spec['expires_epoch'], ZoneInfo('America/Chicago')).isoformat()}
(America/Chicago), Unix epoch {spec['expires_epoch']}.
Target {target['user']}@{target['addresses'][0]}, expected hostname {target['hostname']},
pinned Ed25519 alias {target['alias']}. Fixed inputs are archive members; no target
contact occurs while sealing. DNS hostnames come from retained September 21
identity evidence, not an assumption about current VIP roles. Drift stops capture.

NTP scope: two independent planned SSH captures, first IPv4 .51 then native ::51,
using the accepted old-address key alias 10.1.0.137, not DNS or TOFU. Pin boot
{TARGETS['ntp']['boot_id']}. Read eth0 address/DAD flags, VIP routes/defaults,
UDP/123 listeners, ntp.conf hash/metadata and time-service identity before/after.
Read the selected active eth0 profile's address settings and persistent filename/
hash/metadata; no profile contents are exported. Reject transient-only profiles.
No clock, GPS, RTC, NTP control, interface activation or service change. Both
authenticated family captures must complete with the same host/boot/service.
Only the NTP-mode bundle contacts the NTP node; DNS modes never do so.

DNS scope: one IPv4 SSH capture on this bundle's DNS node only. Read current
service identities, addresses/VIP roles, protected /etc/unbound configuration
include graph (64 files, 4 MiB aggregate), fragment bytes/metadata, selected NTP
records, installed version/control help and reload projection.
Recheck VIP ownership after queries; changed ownership fails capture and mixed
ownership remains a deployment hold even with unchanged service identities.
Refuse include cycles, unsupported include contexts, paths outside /etc/unbound and unsafe
files. Never retrieve control keys or credentials. Only the exact local-zone
fragment is exported in full; other include contents remain in memory with
hash/metadata and selected record projections exported.
Only .conf include paths and A/AAAA/CNAME/PTR/SRV/MX/NS record forms are in scope;
unexpected record types or private-key material hold without full-fragment export.
Support include-toplevel only in a root consisting of includes/comments, with
included text starting a top-level section; otherwise hold without flattening
ambiguous parser context. Compare the full expanded graph before/after capture.

Validate the original using installed unbound-checkconf, and an expanded
in-memory candidate through /dev/stdin with only absent ntp1 AAAA ::51 and
canonical IPv6 PTR additions. Do not copy the repository candidate wholesale;
it includes separately pending Munin/svmf records. Preserve unrelated live data.
Identical records are not duplicated; conflicting/duplicate NTP records hold.
No staging or target file write. Unsupported include graphs fail without a
fallback or broader traversal.

Read metadata/feature tokens of fixed Pi-hole script/version paths, local Git
commit/tag only, selected synchronization-unit identity and fixed sync-config
hash/path hints. Do not invoke Pi-hole restart, sync jobs or unbound-control
status/reload. These projections leave full restart and writer qualification
explicitly open; they do not prove no other writers exist. Do not read setupVars,
FTL credentials, key files, environments or arbitrary home directories.

DNS queries: 24 dig queries on this node: ntp1 A/AAAA and .51/::51 PTR through
loopback Unbound 5335 on IPv4/IPv6, this node's two port-53 addresses and the two
DNS VIPs. Absolute names, no search or digrc, one two-second UDP attempt, three-
second process limit, no TCP fallback. Missing tools/negative answers remain
evidence, not successful DNS acceptance. No cache flush or fixed sleeps.

Commands are bounded to eight seconds/65536 bytes per stream unless specifically
three-second dig or one-MiB file reads. Remote deadline is 90 seconds for NTP and
240 seconds for DNS; controller deadline per SSH capture is 120/270 seconds,
with 16-MiB streams. Retain partial output/status privately. Strict host keys,
no proxy, forwarding, connection sharing, startup files or automatic retry.
The one-use local receipt is consumed before first contact. Only planned NTP
family captures may follow each other; there is no DNS-peer progression.

No network/profile/NSS/DNS record change, package action, reload, restart, reboot,
notification or cleanup. Native checker activity is read-only; SSH/sudo/DNS
queries may produce normal logs/caches. No restoration is needed. Capture
completion does not accept DNS deployment or NTP timing production readiness.

After exact archive-hash approval, run the frozen runner:

```bash
python3 -I -B DIRECTORY/runner.py execute --directory DIRECTORY --sha256 APPROVED_SHA256
```

The transport helper is frozen from the explicitly supplied repository-owned
homelab-ntp/ntpsec/scripts/run-production-inspection.py. Historical evidence is
identity/data provenance only; no historical executable is imported. Separate
target-stage approval is required by homelab-ntp/AGENTS.md and the DNS-owner
readiness review. The NTP, dns53 and dns54 archives have distinct hashes.
'''


def unpack(raw, digest):
    if len(raw) > 8388608 or sha(raw) != digest:
        raise ValueError('archive hash/size mismatch')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        entries = archive.getmembers()
        if len(entries) != len(MEMBERS) or {e.name for e in entries} != MEMBERS or any(not e.isfile() or e.size > 1048576 for e in entries):
            raise ValueError('closed flat regular member set required')
        files = {e.name: archive.extractfile(e).read() for e in entries}
    spec = json.loads(files['spec.json'])
    if (spec.get('mode') not in TARGETS or spec.get('target') != expected_target(spec['mode'], spec.get('qualification', False))
            or not re.fullmatch(r'ntp1-(?:address|dns53|dns54)-(?:readiness|controls-qualification)-\d{8}-v\d{1,2}', spec['operation_id'])
            or not spec['operation_id'].startswith('ntp1-'+('address' if spec['mode'] == 'ntp' else spec['mode'])+('-controls-qualification-' if spec.get('qualification') else '-readiness-'))
            or spec['expires_epoch']-spec['prepared_epoch'] != 86400
            or not spec['prepared_epoch'] <= time.time() < spec['expires_epoch']-300
            or spec['members'] != {n: sha(v) for n, v in files.items() if n not in ('spec.json', 'review.md')}
            or files['review.md'] != review(spec).encode()):
        raise ValueError('scope, expiry, review or member binding mismatch')
    candidate, additions = ntp_candidate(files['candidate.conf'])
    if additions or candidate != files['candidate.conf']:
        raise ValueError('repository candidate lacks exact reviewed NTP additions')
    return spec, files


def trusted_key(path, alias):
    row = subprocess.run(['/usr/bin/ssh-keygen', '-F', alias, '-f', str(path)],
                         capture_output=True, check=True, timeout=5)
    keys = {tuple(line.split()[1:3]) for line in row.stdout.decode().splitlines()
            if not line.startswith('#') and len(line.split()) >= 3 and line.split()[1] == 'ssh-ed25519'}
    if len(keys) != 1:
        raise ValueError('one established Ed25519 key required; no network key discovery')
    kind, key = keys.pop()
    return (alias+' '+kind+' '+key+'\n').encode()


def seal(args):
    now = int(time.time())
    qualification = getattr(args, 'qualification', False)
    if qualification and args.mode not in CONTROL_BOOTS:
        raise ValueError('qualification is DNS-only')
    files = {'runner.py': Path(__file__).read_bytes(), 'helper.py': args.helper.read_bytes(),
        'tests.py': Path(__file__).resolve().parents[1].joinpath('tests/test_ntp_dns_readiness.py').read_bytes(),
        'candidate.conf': args.candidate.read_bytes(), 'known_hosts': trusted_key(args.known_hosts, TARGETS[args.mode]['alias'])}
    spec = {'mode': args.mode, 'target': expected_target(args.mode, qualification), 'qualification': qualification, 'operation_id': args.output.name,
        'prepared_epoch': now, 'expires_epoch': now+86400,
        'helper_provenance': 'homelab-ntp/ntpsec/scripts/run-production-inspection.py',
        'members': {n: sha(v) for n, v in files.items()}}
    files.update({'spec.json': encoded(spec), 'review.md': review(spec).encode()})
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, data in sorted(files.items()):
            entry = tarfile.TarInfo(name); entry.size = len(data); entry.mode = 0o600
            archive.addfile(entry, io.BytesIO(data))
    raw = buffer.getvalue(); digest = sha(raw); unpack(raw, digest)
    os.umask(0o077); args.output.mkdir(mode=0o700)
    for name, data in files.items():
        write(args.output/name, data)
    write(args.output/'inspection.tar', raw)
    write(args.output/'sealing.json', encoded({'sha256': digest, 'expires_epoch': now+86400, 'target_contact': False}))
    return {'sha256': digest, 'target_contact': False}


def ssh_argv(spec, directory, family):
    target = spec['target']; address = target['addresses'][family == 6]
    options = ['BatchMode=yes', 'StrictHostKeyChecking=yes', 'HostKeyAlgorithms=ssh-ed25519',
        'UpdateHostKeys=no', 'ProxyCommand=none', 'ProxyJump=none', 'ControlMaster=no', 'ControlPath=none',
        'ControlPersist=no', 'PermitLocalCommand=no', 'ClearAllForwardings=yes', 'ForwardAgent=no', 'ForwardX11=no',
        'GlobalKnownHostsFile=/dev/null', 'UserKnownHostsFile='+str(directory/'known_hosts'),
        'HostKeyAlias='+target['alias'], 'ConnectTimeout=10', 'ServerAliveInterval=10', 'ServerAliveCountMax=2']
    return ['/usr/bin/ssh', '-F', '/dev/null', '-T', '-'+str(family),
        *[v for option in options for v in ('-o', option)], target['user']+'@'+address,
        'cd / && /usr/bin/sudo -n /usr/bin/python3 -I -B -']


def load_helper(path):
    loader = importlib.util.spec_from_file_location('bounded_transport', path)
    module = importlib.util.module_from_spec(loader); loader.loader.exec_module(module)
    return module


def execute(directory, digest):
    os.umask(0o077)
    if directory.is_symlink() or directory.stat().st_uid != os.geteuid() or directory.stat().st_mode & 0o077:
        raise ValueError('private local execution directory required')
    spec, files = unpack((directory/'inspection.tar').read_bytes(), digest)
    if files['runner.py'] != Path(__file__).read_bytes() or any((directory/n).read_bytes() != files[n] for n in ('helper.py', 'known_hosts', 'review.md', 'spec.json')):
        raise ValueError('frozen local execution inputs required')
    helper = load_helper(directory/'helper.py')
    remote_seconds = 90 if spec['mode'] == 'ntp' else 240
    payload = (b"__name__='sealed_readiness'\n__file__='/sealed/runner.py'\n"+files['runner.py']
        +b"\nns={'__name__':'helper','__file__':'/sealed/helper.py'}\nexec("+repr(files['helper.py']).encode()
        +b",ns)\nh=types.SimpleNamespace(**ns)\nsignal.signal(signal.SIGALRM,h.expired)\nsignal.alarm("
        +str(remote_seconds).encode()+b")\nprint(json.dumps(collect("+repr(spec).encode()+b")))\n")
    families = (4, 6) if spec['mode'] == 'ntp' else (4,)
    write(directory/'execution.json', encoded({'sha256': digest, 'epoch': time.time(), 'families': families,
        'payload_sha256': sha(payload), 'argv': [ssh_argv(spec, directory, f) for f in families]}))
    captures = []
    for family in families:
        transport = helper.bounded(ssh_argv(spec, directory, family), timeout=remote_seconds+30,
            limit=16777216, payload=payload, env=os.environ.copy())
        for stream in ('stdout', 'stderr'):
            write(directory/(str(family)+'-'+stream+'.txt'), transport.pop(stream, '').encode())
        row = {'family': family, 'transport': transport, 'capture_complete': False}
        if transport.get('returncode') == 0 and not transport.get('error'):
            capture = json.loads((directory/(str(family)+'-stdout.txt')).read_bytes())
            if capture.get('operation_id') != spec['operation_id'] or capture.get('spec_sha256') != sha(encoded(spec)):
                raise ValueError('capture binding mismatch; consumed operation cannot replay')
            row['capture_complete'] = capture.get('capture_complete') is True
            row['capture'] = capture
        captures.append(row)
        write(directory/('transport-'+str(family)+'.json'), encoded(row))
    complete = all(row['capture_complete'] for row in captures)
    if spec['mode'] == 'ntp' and complete:
        complete = all(captures[0]['capture'][key] == captures[1]['capture'][key] for key in
                       ('identity_before', 'identity_after', 'service_before', 'service_after'))
    result = {'sha256': digest, 'capture_complete': complete, 'captures': captures, 'deployment_accepted': False}
    write(directory/'result.json', encoded(result))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    prepare = sub.add_parser('seal')
    prepare.add_argument('--mode', choices=TARGETS, required=True)
    prepare.add_argument('--qualification', action='store_true')
    for option in ('helper', 'candidate', 'known-hosts', 'output'):
        prepare.add_argument('--'+option, type=Path, required=True)
    run = sub.add_parser('execute'); run.add_argument('--directory', type=Path, required=True); run.add_argument('--sha256', required=True)
    args = parser.parse_args()
    result = seal(args) if args.action == 'seal' else execute(args.directory.absolute(), args.sha256)
    print(json.dumps(result))
    if args.action == 'execute' and not result['capture_complete']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
