#!/usr/bin/env bash

set -u
set +x
PATH=/usr/bin:/bin
export PATH
readonly PATH

readonly dns_name=pihole.local.theama.co
readonly expected_ipv4=10.1.0.55
readonly expected_ipv6=fd36:5aa8:6971:1::55
readonly dig_command=${DNS_CHECK_DIG_COMMAND:-/usr/bin/dig}
readonly systemctl_command=${DNS_CHECK_SYSTEMCTL_COMMAND:-/usr/bin/systemctl}

# Keep SIGTERM at its default disposition; Keepalived signals the full process group.

"$systemctl_command" is-active --quiet pihole-FTL.service || exit 1
"$systemctl_command" is-active --quiet unbound.service || exit 1

check_answer() {
  local health_server=$1
  local health_port=$2
  local health_type=$3
  local health_expected=$4
  local health_answer

  health_answer=$("$dig_command" "@$health_server" -p "$health_port" \
    "$dns_name" "$health_type" +short +time=1 +tries=1 2>/dev/null) || return 1
  [[ "$health_answer" = "$health_expected" ]]
}

health_pids=()
for health_server in 127.0.0.1 ::1; do
  for health_port in 53 5335; do
    check_answer "$health_server" "$health_port" A "$expected_ipv4" &
    health_pids+=("$!")
    check_answer "$health_server" "$health_port" AAAA "$expected_ipv6" &
    health_pids+=("$!")
  done
done

health_result=0
for health_pid in "${health_pids[@]}"; do
  wait "$health_pid" || health_result=1
done

exit "$health_result"
