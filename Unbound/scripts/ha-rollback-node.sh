#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

[[ $# -ge 1 && $# -le 2 ]] || die "usage: ${0##*/} BACKUP_DIRECTORY [VIP_ADDRESS]"
readonly backup_dir=$1
readonly vip_address=${2:-10.1.0.55}

require_root
require_commands apt-get systemctl unbound-checkconf dig ip tar find
[[ -f $backup_dir/unbound-configuration.tgz && -d $backup_dir/packages ]] || die "invalid rollback backup"
if ip -brief address | awk -v vip="$vip_address" '$0 ~ vip { found=1 } END { exit !found }'; then
  die "move $vip_address to the known-good peer before rollback"
fi

mapfile -d '' rollback_packages < <(find "$backup_dir/packages" -maxdepth 1 -type f -name '*.deb' -print0)
((${#rollback_packages[@]} > 0)) || die "no cached Bookworm packages found"

systemctl stop unbound
DEBIAN_FRONTEND=noninteractive apt-get install -y --allow-downgrades \
  -o Dpkg::Options::=--force-confold "${rollback_packages[@]}"
tar -C / -xzf "$backup_dir/unbound-configuration.tgz"
if [[ -d $backup_dir/host-files ]]; then
  cp -a "$backup_dir/host-files/." /
fi
unbound-checkconf /etc/unbound/unbound.conf
systemctl restart unbound
systemctl is-active --quiet unbound
dig @127.0.0.1 -p 5335 dnssec.works A +time=5 +tries=1
log "rollback is healthy; validate Pi-hole before returning this node to keepalived"
