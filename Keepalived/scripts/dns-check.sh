#!/usr/bin/env bash

set -o pipefail

readonly DNS_NAME="pihole.local.theama.co"
readonly EXPECTED_IPV4="10.1.0.55"

check_dns_answer() {
  local port=$1
  local answers

  answers=$(dig @127.0.0.1 -p "$port" "$DNS_NAME" A \
    +short +time=1 +tries=1) || return 1

  grep -Fxq "$EXPECTED_IPV4" <<<"$answers"
}

# Verify systemd service status.
systemctl is-active --quiet pihole-FTL || exit 1
systemctl is-active --quiet unbound || exit 1

# Require the known local VIP record through Pi-hole.
check_dns_answer 53 || exit 1

# Require the same known local VIP record directly from Unbound.
check_dns_answer 5335 || exit 1

exit 0
