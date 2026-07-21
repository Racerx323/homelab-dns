#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

usage() {
  printf 'Usage: sudo %s ha|v6 [VIP_ADDRESS]\n' "${0##*/}"
}

[[ $# -ge 1 && $# -le 2 ]] || {
  usage >&2
  exit 2
}
readonly scenario=$1
readonly vip_address=${2:-10.1.0.55}
[[ $scenario == ha || $scenario == v6 ]] || die "scenario must be ha or v6"

require_root
load_release_env
assert_bookworm_arm64
require_commands dpkg-query unbound unbound-checkconf unbound-control systemctl dig ss sysctl
[[ $(dpkg-query -W -f='${Version}' unbound) == "$BACKPORT_VERSION" ]] || die "wrong Unbound package version"
[[ $(unbound -V) == *"Version $UPSTREAM_VERSION"* ]] || die "wrong Unbound binary version"
unbound-checkconf /etc/unbound/unbound.conf
systemctl is-active --quiet unbound
systemctl is-active --quiet pihole-FTL
assert_sysctls
assert_loopback_listener
unbound-control status

valid_response=$(dig @127.0.0.1 -p 5335 dnssec.works A +dnssec +comments +time=10 +tries=1)
[[ $valid_response == *"status: NOERROR"* && $valid_response == *"flags: qr rd ra ad"* ]] ||
  die "valid DNSSEC response is missing NOERROR or AD"
broken_response=$(dig @127.0.0.1 -p 5335 fail01.dnssec.works A +dnssec +comments +time=10 +tries=1 || true)
[[ $broken_response == *"status: SERVFAIL"* ]] || die "broken DNSSEC response is not SERVFAIL"

if [[ $scenario == ha ]]; then
  dig @127.0.0.1 -p 5335 pihole.local.theama.co A +time=5 +tries=1
  dig @127.0.0.1 -p 5335 _smtp._tcp.local.theama.co SRV +time=5 +tries=1
  dig @127.0.0.1 -p 5335 -x 10.1.0.1 +time=5 +tries=1
  dig @"$vip_address" pihole.local.theama.co A +time=5 +tries=1
else
  configured_upstreams=$(pihole-FTL --config dns.upstreams)
  [[ $configured_upstreams == *"127.0.0.1#5335"* && $configured_upstreams != *"1.1.1.1"* &&
    $configured_upstreams != *"8.8.8.8"* ]] || die "Pi-hole v6 upstream ownership is incorrect"
  [[ $(pihole-FTL --config dns.dnssec) == false ]] || die "Pi-hole DNSSEC must remain disabled"
  dig @127.0.0.1 dnssec.works A +time=10 +tries=1
fi

unbound-control reload
unbound-control stats_noreset >/dev/null
systemctl restart unbound
systemctl is-active --quiet unbound
log "$scenario acceptance gates passed"
