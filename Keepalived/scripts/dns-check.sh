#!/usr/bin/env bash

set -Eeuo pipefail
set +x

readonly dns_name=pihole.local.theama.co
readonly expected_ipv4=10.1.0.55
readonly expected_ipv6=fd36:5aa8:6971:1::55
readonly dig_command=${DNS_CHECK_DIG_COMMAND:-/usr/bin/dig}
readonly systemctl_command=${DNS_CHECK_SYSTEMCTL_COMMAND:-/usr/bin/systemctl}

check_service() {
  "$systemctl_command" is-active --quiet "$1"
}

check_answer() {
  local dns_check_server=$1
  local dns_check_port=$2
  local dns_check_type=$3
  local dns_check_expected=$4
  local dns_check_output=$5
  local dns_check_status=$6

  if "$dig_command" "@$dns_check_server" -p "$dns_check_port" "$dns_name" \
    "$dns_check_type" +short +time=1 +tries=1 >"$dns_check_output" 2>&1; then
    printf '0\n' >"$dns_check_status"
  else
    printf '%s\n' "$?" >"$dns_check_status"
  fi
  [[ "$(wc -l <"$dns_check_output")" -eq 1 ]] || return 1
  grep -Fxq -- "$dns_check_expected" "$dns_check_output"
}

check_service pihole-FTL.service
check_service unbound.service

capture_root=$(mktemp -d /tmp/check-dns.XXXXXX)
readonly capture_root
trap 'rm -rf -- "$capture_root"' EXIT

declare -a pids=()
declare -a labels=()
for dns_check_server in 127.0.0.1 ::1; do
  for dns_check_port in 53 5335; do
    for dns_check_type in A AAAA; do
      dns_check_expected=$expected_ipv4
      [[ "$dns_check_type" = A ]] || dns_check_expected=$expected_ipv6
      dns_check_label=${dns_check_server//[:.]/_}_${dns_check_port}_${dns_check_type}
      labels+=("$dns_check_label")
      check_answer "$dns_check_server" "$dns_check_port" "$dns_check_type" \
        "$dns_check_expected" "$capture_root/$dns_check_label.out" \
        "$capture_root/$dns_check_label.status" &
      pids+=("$!")
    done
  done
done

dns_check_failed=0
for dns_check_index in "${!pids[@]}"; do
  if ! wait "${pids[$dns_check_index]}"; then
    dns_check_failed=1
  fi
done

for dns_check_label in "${labels[@]}"; do
  dns_check_status=$(<"$capture_root/$dns_check_label.status")
  dns_check_answer=invalid
  if [[ "$(wc -c <"$capture_root/$dns_check_label.out")" -le 64 &&
  "$(wc -l <"$capture_root/$dns_check_label.out")" -eq 1 ]]; then
    dns_check_observed=$(<"$capture_root/$dns_check_label.out")
    if [[ "$dns_check_observed" =~ ^[0-9A-Fa-f:.]+$ ]]; then
      dns_check_answer=$dns_check_observed
    fi
  fi
  printf 'check=%s status=%s answer=%s\n' \
    "$dns_check_label" "$dns_check_status" "$dns_check_answer"
done

exit "$dns_check_failed"
