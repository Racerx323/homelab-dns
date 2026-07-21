#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

usage() {
  printf 'Usage: sudo %s CANDIDATE_PACKAGE_DIRECTORY\n' "${0##*/}"
}

[[ $# -eq 1 ]] || {
  usage >&2
  exit 2
}
candidate_dir=$1
[[ -d $candidate_dir/packages ]] && candidate_dir="$candidate_dir/packages"

require_root
load_release_env
assert_bookworm_arm64
require_commands apt-get dpkg-query dpkg-deb unbound-checkconf systemctl sha256sum ss find

for production_package in pihole-FTL keepalived; do
  if dpkg-query -W -f='${Status}' "$production_package" 2>/dev/null | grep -Fq 'install ok installed'; then
    die "refusing destructive lifecycle test on a host with $production_package installed"
  fi
done

mapfile -d '' candidate_packages < <(find "$candidate_dir" -maxdepth 1 -type f -name '*.deb' -print0)
((${#candidate_packages[@]} > 0)) || die "no candidate packages found"

declare -A candidate_by_name=()
for package_file in "${candidate_packages[@]}"; do
  package_name=$(dpkg-deb -f "$package_file" Package)
  candidate_by_name[$package_name]=$package_file
done
for package_name in unbound unbound-anchor libunbound8 python3-unbound unbound-pihole-profile; do
  [[ -v candidate_by_name[$package_name] ]] || die "missing candidate package: $package_name"
done

log "installing the current Bookworm package as the upgrade baseline"
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y -t bookworm unbound python3-unbound
baseline_version=$(dpkg-query -W -f='${Version}' unbound)
[[ $baseline_version == 1.17.1-* ]] || die "expected a Bookworm 1.17.1 baseline, found $baseline_version"
baseline_enabled=$(systemctl is-enabled unbound 2>/dev/null || true)

install -d -m 0755 /etc/unbound/unbound.conf.d
cat >/etc/unbound/unbound.conf.d/pihole.conf <<'EOF'
server:
    interface: 127.0.0.1
    port: 5335
    do-ip6: no
EOF
before_hash=$(sha256sum /etc/unbound/unbound.conf.d/pihole.conf)
unbound-checkconf /etc/unbound/unbound.conf

runtime_candidates=()
for package_name in unbound unbound-anchor libunbound8 python3-unbound; do
  if [[ -v candidate_by_name[$package_name] ]]; then
    runtime_candidates+=("${candidate_by_name[$package_name]}")
  fi
done

log "testing noninteractive upgrade with administrator conffiles preserved"
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  -o Dpkg::Options::=--force-confold "${runtime_candidates[@]}"
[[ $(dpkg-query -W -f='${Version}' unbound) == "$BACKPORT_VERSION" ]] || die "upgrade version mismatch"
[[ $(sha256sum /etc/unbound/unbound.conf.d/pihole.conf) == "$before_hash" ]] || die "upgrade changed pihole.conf"
[[ $(systemctl is-enabled unbound 2>/dev/null || true) == "$baseline_enabled" ]] || die "upgrade changed service enablement"
unbound-checkconf /etc/unbound/unbound.conf
systemctl restart unbound
systemctl is-active --quiet unbound

log "testing package reinstall"
DEBIAN_FRONTEND=noninteractive apt-get install -y --reinstall \
  -o Dpkg::Options::=--force-confold "${runtime_candidates[@]}"
[[ $(sha256sum /etc/unbound/unbound.conf.d/pihole.conf) == "$before_hash" ]] || die "reinstall changed pihole.conf"

log "testing the independent profile package on a clean conffile path"
mv /etc/unbound/unbound.conf.d/pihole.conf /etc/unbound/unbound.conf.d/pihole.conf.lifecycle-test
DEBIAN_FRONTEND=noninteractive apt-get install -y "${candidate_by_name["unbound-pihole-profile"]}"
unbound-checkconf /etc/unbound/unbound.conf
DEBIAN_FRONTEND=noninteractive apt-get remove -y unbound-pihole-profile
[[ -e /etc/unbound/unbound.conf.d/pihole.conf ]] || die "profile conffile was not preserved on removal"
mv /etc/unbound/unbound.conf.d/pihole.conf.lifecycle-test /etc/unbound/unbound.conf.d/pihole.conf

log "testing removal and absence of an orphaned listener"
DEBIAN_FRONTEND=noninteractive apt-get remove -y unbound python3-unbound
if [[ -n $(ss -H -lntu '( sport = :5335 )') ]]; then
  die "port 5335 remains open after package removal"
fi

log "restoring the Bookworm package and validating rollback"
DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-downgrades -t bookworm \
  unbound unbound-anchor libunbound8 python3-unbound
[[ $(dpkg-query -W -f='${Version}' unbound) == 1.17.1-* ]] || die "Bookworm rollback failed"
[[ $(sha256sum /etc/unbound/unbound.conf.d/pihole.conf) == "$before_hash" ]] || die "rollback changed pihole.conf"
unbound-checkconf /etc/unbound/unbound.conf
systemctl restart unbound
systemctl is-active --quiet unbound

log "clean install, upgrade, reinstall, removal, and rollback lifecycle passed"
