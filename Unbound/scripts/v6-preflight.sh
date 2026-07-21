#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

[[ $# -eq 1 ]] || die "usage: ${0##*/} BUNDLE_DIRECTORY"
readonly bundle_dir=$1

require_root
load_release_env
assert_bookworm_arm64
require_commands gpg sha256sum dpkg-deb pihole-FTL dig ss timedatectl
verify_bundle "$bundle_dir"

pihole_version=$(pihole-FTL -v 2>&1 || true)
[[ $pihole_version == *"v6."* || $pihole_version == *"version 6."* ]] ||
  die "Pi-hole FTL v6 is required; found: $pihole_version"
systemctl is-active --quiet pihole-FTL || die "Pi-hole FTL is not healthy"

if [[ -n $(ss -H -lntu '( sport = :5335 )') ]]; then
  die "port 5335 is already in use"
fi
[[ $(timedatectl show -p NTPSynchronized --value) == yes ]] || die "system time is not synchronized"

for transport in udp tcp; do
  dig_arguments=(@198.41.0.4 . NS +norecurse +comments +time=5 +tries=1)
  [[ $transport == tcp ]] && dig_arguments+=(+tcp)
  root_response=$(dig "${dig_arguments[@]}") || die "root DNS $transport test failed"
  [[ $root_response == *"status: NOERROR"* && $root_response == *"flags: qr aa"* ]] ||
    die "root DNS $transport response is blocked, proxied, or non-authoritative"
done

log "clean-target preflight passed: signed bundle, Pi-hole v6, root DNS, time, and port 5335"
