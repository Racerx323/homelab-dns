#!/usr/bin/env bash

set -Eeuo pipefail

unbound_root=$(cd "$(dirname "$0")/.." && pwd)
readonly unbound_root
readonly profile_root="$unbound_root/packaging/unbound-pihole-profile"
readonly profile_conf="$profile_root/etc/unbound/unbound.conf.d/pihole.conf"

fail() {
  printf 'FAIL: %s\n' "$*" >&2
  exit 1
}

assert_contains() {
  local expected=$1
  local file=$2
  grep -Fq -- "$expected" "$file" || fail "$file is missing: $expected"
}

assert_absent() {
  local unexpected=$1
  local file=$2
  if grep -Fq -- "$unexpected" "$file"; then
    fail "$file unexpectedly contains: $unexpected"
  fi
}

printf 'Checking shell syntax...\n'
while IFS= read -r -d '' script_file; do
  bash -n "$script_file"
done < <(find "$unbound_root/scripts" "$unbound_root/tests" -type f -name '*.sh' -print0)
sh -n "$profile_root/debian/tests/smoke"

if command -v shellcheck >/dev/null 2>&1; then
  mapfile -d '' scripts < <(find "$unbound_root/scripts" "$unbound_root/tests" -type f -name '*.sh' -print0)
  shellcheck "${scripts[@]}" "$profile_root/debian/tests/smoke"
fi

printf 'Checking pinned versions and package metadata...\n'
assert_contains 'UPSTREAM_VERSION=1.25.1' "$unbound_root/packaging/release.env"
assert_contains 'BACKPORT_VERSION=1.25.1-1~bookworm1' "$unbound_root/packaging/release.env"
assert_contains 'TARGET_SUITE=bookworm' "$unbound_root/packaging/release.env"
assert_contains 'TARGET_ARCH=arm64' "$unbound_root/packaging/release.env"
assert_contains 'Architecture: all' "$profile_root/debian/control"
assert_contains 'unbound (>= 1.25.1-1~bookworm1)' "$profile_root/debian/control"

printf 'Checking generic resolver profile invariants...\n'
for directive in \
  'interface: 127.0.0.1' \
  'interface: ::1' \
  'port: 5335' \
  'do-ip4: yes' \
  'do-ip6: yes' \
  'do-udp: yes' \
  'do-tcp: yes' \
  'qname-minimisation: yes' \
  'edns-buffer-size: 1232' \
  'dnstap-enable: no' \
  'use-syslog: yes'; do
  assert_contains "$directive" "$profile_conf"
done
for forbidden in 'forward-zone:' 'forward-addr:' 'local-zone:' 'local-data:' 'logfile:'; do
  assert_absent "$forbidden" "$profile_conf"
done

printf 'Checking package side-effect boundary...\n'
for maintainer_script in postinst preinst prerm postrm triggers; do
  [[ ! -e $profile_root/debian/$maintainer_script ]] ||
    fail "profile must not ship maintainer script: $maintainer_script"
done
for forbidden in '/etc/pihole' '/etc/keepalived' '/etc/resolv.conf' 'nft ' 'iptables'; do
  if grep -R -Fq -- "$forbidden" "$profile_root/debian" "$profile_root/etc" "$profile_root/usr"; then
    fail "profile package payload contains forbidden side effect target: $forbidden"
  fi
done

if command -v dpkg-parsechangelog >/dev/null 2>&1; then
  profile_version=$(dpkg-parsechangelog -l"$profile_root/debian/changelog" -SVersion)
  [[ $profile_version == 1.0.0 ]] || fail "unexpected profile version: $profile_version"
fi

if command -v unbound-checkconf >/dev/null 2>&1; then
  unbound-checkconf "$profile_conf"
else
  printf 'SKIP: unbound-checkconf is not installed on this development host.\n'
fi

printf 'All repository tests passed.\n'
