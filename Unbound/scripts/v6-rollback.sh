#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

usage() {
  printf 'Usage: sudo %s BACKUP_DIRECTORY [--install-bookworm]\n' "${0##*/}"
}

[[ $# -ge 1 && $# -le 2 ]] || {
  usage >&2
  exit 2
}
readonly backup_dir=$1
install_bookworm=false
if [[ ${2:-} == --install-bookworm ]]; then
  install_bookworm=true
elif [[ -n ${2:-} ]]; then
  usage >&2
  exit 2
fi

require_root
require_commands pihole-FTL systemctl dig apt-get
[[ -s $backup_dir/dns.upstreams && -s $backup_dir/dns.dnssec ]] || die "invalid Pi-hole rollback state"

previous_upstreams=$(<"$backup_dir/dns.upstreams")
previous_dnssec=$(<"$backup_dir/dns.dnssec")
[[ -n $previous_upstreams ]] || die "refusing rollback to an empty Pi-hole upstream list"
pihole-FTL --config dns.upstreams "$previous_upstreams"
pihole-FTL --config dns.dnssec "$previous_dnssec"
systemctl restart pihole-FTL
systemctl is-active --quiet pihole-FTL
dig @127.0.0.1 dnssec.works A +time=10 +tries=1

systemctl stop unbound
DEBIAN_FRONTEND=noninteractive apt-get remove -y unbound-pihole-profile unbound
if [[ $install_bookworm == true ]]; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y unbound
fi

log "Pi-hole upstreams were restored before Unbound removal; modified conffiles were not purged"
