#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

usage() {
  printf 'Usage: sudo %s --new-checkconf PATH [--vip ADDRESS] [--backup-dir PATH]\n' "${0##*/}"
}

new_checkconf=
vip_address=10.1.0.55
backup_dir="/var/backups/unbound-upgrade-$(date -u +%Y%m%dT%H%M%SZ)"
while (($#)); do
  case $1 in
    --new-checkconf)
      new_checkconf=${2:-}
      shift 2
      ;;
    --vip)
      vip_address=${2:-}
      shift 2
      ;;
    --backup-dir)
      backup_dir=${2:-}
      shift 2
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      exit 2
      ;;
  esac
done

require_root
load_release_env
assert_bookworm_arm64
require_commands "$new_checkconf" unbound-checkconf unbound dpkg-query apt-get tar sha256sum \
  systemctl ss ip sysctl nc find
[[ -x $new_checkconf ]] || die "new unbound-checkconf is not executable"
[[ $backup_dir == /var/backups/unbound-upgrade-* ]] || die "backup path must be under /var/backups/unbound-upgrade-*"
[[ ! -e $backup_dir ]] || die "backup directory already exists"

if ip -brief address | awk -v vip="$vip_address" '$0 ~ vip { found=1 } END { exit !found }'; then
  die "this node owns $vip_address; move the VIP to the healthy peer first"
fi

install -d -m 0700 "$backup_dir/packages" "$backup_dir/host-files"

log "capturing host, resolver, Pi-hole, HA, and security inventory"
{
  hostnamectl || true
  printf '\nArchitecture and OS\n'
  dpkg --print-architecture
  cat /etc/os-release
  printf '\nUnbound packages and build\n'
  dpkg-query -W 'unbound*' 'libunbound*' 'python3-unbound' 2>/dev/null || true
  unbound -V
  printf '\nPi-hole\n'
  pihole -v 2>/dev/null || true
  pihole-FTL --config dns.upstreams 2>/dev/null || true
  printf '\nServices and overrides\n'
  systemctl status unbound keepalived pihole-FTL --no-pager || true
  systemctl cat unbound || true
  printf '\nAppArmor\n'
  aa-status 2>/dev/null || true
  printf '\nKernel, listeners, addresses, and firewall\n'
  sysctl net.core.rmem_max net.core.wmem_max
  ss -lntup
  ip -brief address
  nft list ruleset 2>/dev/null || iptables-save 2>/dev/null || true
} >"$backup_dir/inventory.txt" 2>&1

tar -C / -czf "$backup_dir/unbound-configuration.tgz" etc/unbound var/lib/unbound
tar -C / -czf "$backup_dir/pihole-configuration.tgz" etc/pihole
for optional_path in \
  /etc/apparmor.d/usr.sbin.unbound \
  /etc/apparmor.d/local/usr.sbin.unbound \
  /etc/sysctl.d/unbound-socket-buffers.conf \
  /etc/systemd/system/unbound.service.d; do
  if [[ -e $optional_path ]]; then
    cp -a --parents "$optional_path" "$backup_dir/host-files"
  fi
done

find /etc/unbound -type f -print0 | sort -z | xargs -0 sha256sum >"$backup_dir/config.sha256"
while IFS= read -r -d '' config_file; do
  dpkg-query -S "$config_file" 2>&1 || printf 'unowned: %s\n' "$config_file"
done < <(find /etc/unbound -type f -print0 | sort -z) >"$backup_dir/config-ownership.txt"

dpkg-query -W -f='${binary:Package}\t${Version}\n' 'unbound*' 'libunbound*' 'python3-unbound' \
  2>/dev/null >"$backup_dir/packages.tsv" || true
while IFS=$'\t' read -r package_name package_version; do
  [[ -n $package_name && -n $package_version ]] || continue
  (cd "$backup_dir/packages" && apt-get download "$package_name=$package_version")
done <"$backup_dir/packages.tsv"

log "validating the live configuration with both installed and candidate binaries"
unbound-checkconf /etc/unbound/unbound.conf
"$new_checkconf" /etc/unbound/unbound.conf

mapfile -t forward_addresses < <(unbound-checkconf -o forward-addr /etc/unbound/unbound.conf | sed '/^$/d')
((${#forward_addresses[@]} > 0)) || die "no Cloudflare forward-addr is configured"
for forward_address in "${forward_addresses[@]}"; do
  endpoint=${forward_address%%#*}
  endpoint=${endpoint%@*}
  endpoint=${endpoint#[}
  endpoint=${endpoint%]}
  log "checking configured DoT endpoint $endpoint over TCP 853"
  nc -z -w 5 "$endpoint" 853 || die "cannot connect to $endpoint:853"
done

assert_sysctls
log "preflight complete; immutable evidence and rollback packages: $backup_dir"
