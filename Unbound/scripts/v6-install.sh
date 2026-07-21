#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

[[ $# -ge 1 && $# -le 2 ]] || die "usage: ${0##*/} BUNDLE_DIRECTORY [BACKUP_DIRECTORY]"
readonly bundle_dir=$1
readonly backup_dir=${2:-/var/backups/unbound-v6-install-$(date -u +%Y%m%dT%H%M%SZ)}

require_root
load_release_env
assert_bookworm_arm64
require_commands gpg sha256sum dpkg-deb apt-get systemctl sysctl unbound-checkconf \
  unbound-anchor unbound-control pihole-FTL dig ss find tar runuser
"$UNBOUND_ROOT/scripts/v6-preflight.sh" "$bundle_dir"
[[ $backup_dir == /var/backups/unbound-v6-install-* ]] || die "backup path must be under /var/backups/unbound-v6-install-*"
[[ ! -e $backup_dir ]] || die "backup directory already exists"
install -d -m 0700 "$backup_dir"

pihole-FTL --config dns.upstreams >"$backup_dir/dns.upstreams"
pihole-FTL --config dns.dnssec >"$backup_dir/dns.dnssec"
tar -C / -czf "$backup_dir/pihole-configuration.tgz" etc/pihole

declare -A wanted=(
  [unbound]=1
  ["unbound-anchor"]=1
  [libunbound8]=1
  ["unbound-pihole-profile"]=1
)
install_packages=()
while IFS= read -r -d '' package_file; do
  package_name=$(dpkg-deb -f "$package_file" Package)
  if [[ -v wanted[$package_name] ]]; then
    install_packages+=("$package_file")
    unset 'wanted[$package_name]'
  fi
done < <(find "$bundle_dir/packages" -maxdepth 1 -type f -name '*.deb' -print0)
((${#wanted[@]} == 0)) || die "bundle is missing a clean-target runtime package"

log "installing Unbound and the independent profile package"
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  -o Dpkg::Options::=--force-confold "${install_packages[@]}"
systemctl disable --now unbound-resolvconf.service 2>/dev/null || true
systemctl mask unbound-resolvconf.service 2>/dev/null || true
rm -f /etc/unbound/unbound.conf.d/resolvconf_resolvers.conf
if awk '$1 == "nameserver" && $2 == "127.0.0.1" { found=1 } END { exit !found }' /etc/resolv.conf; then
  die "/etc/resolv.conf points at loopback and cannot express port 5335"
fi

sysctl -p /usr/lib/sysctl.d/60-unbound-pihole-profile.conf
assert_sysctls
unbound-checkconf /etc/unbound/unbound.conf
install -d -o unbound -g unbound -m 0755 /var/lib/unbound
runuser -u unbound -- unbound-anchor -a /var/lib/unbound/root.key
[[ -s /var/lib/unbound/root.key ]] || die "root trust anchor initialization failed"

systemctl restart unbound
systemctl is-active --quiet unbound
assert_loopback_listener
unbound-control status
dig @127.0.0.1 -p 5335 dnssec.works A +dnssec +time=10 +tries=1
dig @::1 -p 5335 dnssec.works AAAA +dnssec +time=10 +tries=1
if ! dig @127.0.0.1 -p 5335 fail01.dnssec.works A +dnssec +time=10 +tries=1 |
  awk '/status: SERVFAIL/ { found=1 } END { exit !found }'; then
  die "Unbound did not reject the broken DNSSEC domain"
fi

log "direct resolver tests passed; switching Pi-hole to local Unbound"
pihole-FTL --config dns.upstreams '[ "127.0.0.1#5335", "::1#5335" ]'
pihole-FTL --config dns.dnssec false
systemctl restart pihole-FTL
systemctl is-active --quiet pihole-FTL
dig @127.0.0.1 dnssec.works A +dnssec +time=10 +tries=1

configured_upstreams=$(pihole-FTL --config dns.upstreams)
[[ $configured_upstreams == *"127.0.0.1#5335"* && $configured_upstreams == *"::1#5335"* ]] ||
  die "Pi-hole did not retain both local Unbound upstreams"
log "clean Pi-hole v6 installation passed; rollback state: $backup_dir"
