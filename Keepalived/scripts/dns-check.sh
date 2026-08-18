#!/usr/bin/env bash

set -Eeuo pipefail
set +x

readonly dns_name=pihole.local.theama.co
readonly expected_ipv4=10.1.0.55
readonly expected_ipv6=fd36:5aa8:6971:1::55
readonly dig_command=${DNS_CHECK_DIG_COMMAND:-/usr/bin/dig}
readonly systemctl_command=${DNS_CHECK_SYSTEMCTL_COMMAND:-/usr/bin/systemctl}
readonly status_file=${DNS_CHECK_STATUS_FILE:-/run/caddy-serving-health/dns/status}
readonly date_command=${DNS_CHECK_DATE_COMMAND:-/usr/bin/date}

write_status() {
  local dns_status_result=$1
  local dns_status_component=$2
  local dns_status_check=$3
  local dns_status_failure_class=$4
  local dns_status_network=$5
  local dns_status_value=$6
  local dns_status_directory=${status_file%/*}
  local dns_status_temporary

  [[ -d "$dns_status_directory" && ! -L "$dns_status_directory" ]] || return 0
  dns_status_temporary=$(mktemp "$dns_status_directory/.status.XXXXXX") || return 0
  printf 'schema=caddy-serving-health-status/v1\napplication=DNS\ncomponent=%s\ncheck=%s\nresult=%s\nfailure_class=%s\nnetwork=%s\nstatus=%s\nobserved_epoch=%s\n' \
    "$dns_status_component" "$dns_status_check" "$dns_status_result" \
    "$dns_status_failure_class" "$dns_status_network" "$dns_status_value" \
    "$($date_command +%s)" >"$dns_status_temporary" || {
    rm -f -- "$dns_status_temporary"
    return 0
  }
  chmod 0644 "$dns_status_temporary" || return 0
  mv -fT -- "$dns_status_temporary" "$status_file" || return 0
}

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

if ! check_service pihole-FTL.service; then
  write_status failed 'Pi-hole FTL' systemd-service service-inactive \
    'loopback port 53' 'unit=pihole-FTL.service state=inactive'
  exit 1
fi
if ! check_service unbound.service; then
  write_status failed Unbound systemd-service service-inactive \
    'loopback port 5335' 'unit=unbound.service state=inactive'
  exit 1
fi

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

if [[ "$dns_check_failed" -ne 0 ]]; then
  dns_failed_label=unknown
  dns_failed_status=unknown
  for dns_check_label in "${labels[@]}"; do
    dns_check_status=$(<"$capture_root/$dns_check_label.status")
    dns_check_lines=$(wc -l <"$capture_root/$dns_check_label.out")
    if [[ "$dns_check_status" != 0 || "$dns_check_lines" -ne 1 ]]; then
      dns_failed_label=$dns_check_label
      dns_failed_status=$dns_check_status
      break
    fi
    dns_check_expected=$expected_ipv4
    [[ "$dns_check_label" = *_AAAA ]] && dns_check_expected=$expected_ipv6
    if ! grep -Fxq -- "$dns_check_expected" "$capture_root/$dns_check_label.out"; then
      dns_failed_label=$dns_check_label
      dns_failed_status=answer-mismatch
      break
    fi
  done
  dns_failed_component='Pi-hole FTL'
  [[ "$dns_failed_label" = *_5335_* ]] && dns_failed_component=Unbound
  dns_failed_family=IPv4
  [[ "$dns_failed_label" = *_AAAA ]] && dns_failed_family=IPv6
  dns_failed_class=probe-failed
  [[ "$dns_failed_status" = answer-mismatch ]] && dns_failed_class=dns-answer-mismatch
  write_status failed "$dns_failed_component" local-answer "$dns_failed_class" \
    "$dns_failed_family check=$dns_failed_label" "status=$dns_failed_status"
  exit 1
fi

write_status healthy 'Pi-hole FTL and Unbound' local-answer none \
  'IPv4 and IPv6 over 127.0.0.1 and ::1 ports 53 and 5335' \
  'all eight answers exact'

exit 0
