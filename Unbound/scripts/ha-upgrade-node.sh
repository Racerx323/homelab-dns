#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

usage() {
  printf 'Usage: sudo %s BUNDLE_DIRECTORY BACKUP_DIRECTORY [VIP_ADDRESS]\n' "${0##*/}"
}

[[ $# -ge 2 && $# -le 3 ]] || {
  usage >&2
  exit 2
}
readonly bundle_dir=$1
readonly backup_dir=$2
readonly vip_address=${3:-10.1.0.55}

require_root
load_release_env
assert_bookworm_arm64
require_commands gpg sha256sum dpkg-deb dpkg-query apt-get systemctl unbound-checkconf \
  unbound-control ss ip sysctl find runuser grep
verify_bundle "$bundle_dir"
[[ -f $backup_dir/config.sha256 && -f $backup_dir/packages.tsv ]] || die "invalid preflight backup"

if ip -brief address | awk -v vip="$vip_address" '$0 ~ vip { found=1 } END { exit !found }'; then
  die "this node owns $vip_address; keep the VIP on the healthy peer"
fi
sha256sum --check "$backup_dir/config.sha256"
assert_sysctls

declare -A wanted=(
  [unbound]=1
  ["unbound-anchor"]=1
  [libunbound8]=1
)
while IFS=$'\t' read -r package_name _; do
  package_name=${package_name%:arm64}
  wanted[$package_name]=1
done <"$backup_dir/packages.tsv"

install_packages=()
while IFS= read -r -d '' package_file; do
  package_name=$(dpkg-deb -f "$package_file" Package)
  package_version=$(dpkg-deb -f "$package_file" Version)
  if [[ -v wanted[$package_name] ]]; then
    [[ $package_version == "$BACKPORT_VERSION" ]] || die "unexpected version in $package_file"
    install_packages+=("$package_file")
    unset 'wanted[$package_name]'
  fi
done < <(find "$bundle_dir/packages" -maxdepth 1 -type f -name '*.deb' -print0)

for package_name in unbound unbound-anchor libunbound8; do
  [[ ! -v wanted[$package_name] ]] || die "bundle is missing runtime package $package_name"
done

log "installing the verified package set while preserving administrator conffiles"
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  -o Dpkg::Options::=--force-confold "${install_packages[@]}"

systemctl disable --now unbound-resolvconf.service 2>/dev/null || true
systemctl mask unbound-resolvconf.service 2>/dev/null || true
rm -f /etc/unbound/unbound.conf.d/resolvconf_resolvers.conf

sha256sum --check "$backup_dir/config.sha256"
unbound-checkconf /etc/unbound/unbound.conf
if [[ $(systemctl show unbound.service -p ExecStartPre --value) != *unbound-checkconf* ]]; then
  die "Debian unbound.service does not provide the required unbound-checkconf pre-start gate"
fi
[[ -s /var/lib/unbound/root.key ]] || die "DNSSEC root trust anchor is missing"
[[ -d /run/unbound ]] || die "Unbound runtime directory is unavailable"
runuser -u unbound -- test -w /run/unbound || die "Unbound cannot write its runtime directory"

if [[ $(unbound-checkconf -o control-enable /etc/unbound/unbound.conf) == yes ]]; then
  for option in server-key-file server-cert-file control-key-file control-cert-file; do
    credential=$(unbound-checkconf -o "$option" /etc/unbound/unbound.conf)
    runuser -u unbound -- test -r "$credential" ||
      die "remote-control credential is not readable by Unbound: $credential"
  done
fi

log_file=$(unbound-checkconf -o logfile /etc/unbound/unbound.conf)
if [[ -n $log_file ]]; then
  [[ -d ${log_file%/*} ]] || die "log directory does not exist"
  runuser -u unbound -- test -w "${log_file%/*}" || die "log directory is not writable by Unbound"
  [[ -r /etc/logrotate.d/unbound ]] || die "file logging requires /etc/logrotate.d/unbound"
  [[ -r /etc/apparmor.d/local/usr.sbin.unbound ]] || die "file logging requires a local AppArmor rule"
  grep -Fq "$log_file" /etc/apparmor.d/local/usr.sbin.unbound ||
    die "local AppArmor policy does not name $log_file"
  grep -Eq 'create[[:space:]]+[0-7]{3,4}[[:space:]]+unbound[[:space:]]+unbound' /etc/logrotate.d/unbound ||
    die "logrotate must create the log with unbound ownership"
fi

systemctl restart unbound
systemctl is-active --quiet unbound
assert_loopback_listener
unbound-control status
if [[ -n $log_file ]]; then
  unbound-control log_reopen
fi
dig @127.0.0.1 -p 5335 dnssec.works A +dnssec +time=5 +tries=1
if dig @127.0.0.1 -p 5335 fail01.dnssec.works A +dnssec +time=5 +tries=1 | awk '/status: SERVFAIL/ { found=1 } END { exit !found }'; then
  log "broken DNSSEC domain correctly returned SERVFAIL"
else
  die "broken DNSSEC domain did not return SERVFAIL"
fi

log "node upgraded successfully; keep it out of VIP service until site A/PTR/SRV and Pi-hole tests pass"
