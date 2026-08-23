#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
readonly PATH

readonly type=${1:-UNKNOWN}
readonly name=${2:-UNKNOWN}
readonly state=${3:-UNKNOWN}
readonly apprise_enqueue=${KEEPALIVED_NOTIFY_ENQUEUE_COMMAND:-/usr/local/libexec/caddy-apprise-enqueue}
readonly logger_command=${KEEPALIVED_NOTIFY_LOGGER_COMMAND:-/usr/bin/logger}
readonly date_command=${KEEPALIVED_NOTIFY_DATE_COMMAND:-/usr/bin/date}
readonly ip_command=${KEEPALIVED_NOTIFY_IP_COMMAND:-/usr/sbin/ip}
readonly hostname_command=${KEEPALIVED_NOTIFY_HOSTNAME_COMMAND:-/usr/bin/hostname}
readonly journalctl_command=${KEEPALIVED_NOTIFY_JOURNALCTL_COMMAND:-/usr/bin/journalctl}
readonly state_root=${KEEPALIVED_NOTIFY_STATE_ROOT:-/var/lib/caddy-serving-health/keepalived-notify}
readonly maintenance_file=${KEEPALIVED_NOTIFY_MAINTENANCE_FILE:-/run/caddy-serving-health/planned-maintenance}
expected_state_owner=pi
expected_state_group=pi
if [[ "${KEEPALIVED_NOTIFY_TEST_MODE:-0}" = 1 ]]; then
  expected_state_owner=$(id -un)
  expected_state_group=$(id -gn)
fi
readonly expected_state_owner expected_state_group

[[ "$type" =~ ^[A-Z_]{1,32}$ ]] || exit 0
[[ "$name" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || exit 0
[[ "$state" =~ ^[A-Z_]{1,32}$ ]] || exit 0
[[ -d "$state_root" && ! -L "$state_root" &&
  "$(stat -c '%U:%G:%a' "$state_root")" = "$expected_state_owner:$expected_state_group:700" ]] || {
  "$logger_command" -t keepalived-notify 'persistent state root unavailable'
  exit 0
}

readonly state_file=$state_root/$name.state
readonly pending_file=$state_root/$name.pending
readonly lock_file=$state_root/$name.lock

safe_state_file() {
  local notify_path=$1

  [[ -f "$notify_path" && ! -L "$notify_path" ]] || return 1
  [[ "$(stat -c '%U:%G:%a' "$notify_path")" = "$expected_state_owner:$expected_state_group:600" ]] || return 1
  [[ "$(stat -c '%s' "$notify_path")" -le 512 ]] || return 1
  [[ "$(wc -l <"$notify_path")" -eq 1 ]]
}

safe_lock_file() {
  local notify_path=$1

  [[ -f "$notify_path" && ! -L "$notify_path" ]] || return 1
  [[ "$(stat -c '%U:%G:%a:%s' "$notify_path")" = "$expected_state_owner:$expected_state_group:600:0" ]]
}

if [[ -e "$state_file" || -L "$state_file" ]]; then
  safe_state_file "$state_file" || {
    "$logger_command" -t keepalived-notify 'unsafe acknowledged state retained'
    exit 0
  }
  [[ "$(<"$state_file")" =~ ^[A-Z_]{1,32}$ ]] || {
    "$logger_command" -t keepalived-notify 'malformed acknowledged state retained'
    exit 0
  }
fi
if [[ -e "$pending_file" || -L "$pending_file" ]]; then
  safe_state_file "$pending_file" || {
    "$logger_command" -t keepalived-notify 'unsafe pending transition retained'
    exit 0
  }
fi
if [[ -e "$lock_file" || -L "$lock_file" ]]; then
  safe_lock_file "$lock_file" || {
    "$logger_command" -t keepalived-notify 'unsafe lock retained'
    exit 0
  }
fi

atomic_line() {
  local notify_target=$1
  local notify_value=$2
  local notify_temporary
  notify_temporary=$(mktemp "$state_root/.${name}.XXXXXX") || return 1
  if printf '%s\n' "$notify_value" >"$notify_temporary" &&
    chmod 0600 "$notify_temporary" &&
    mv -fT -- "$notify_temporary" "$notify_target"; then
    return 0
  fi
  rm -f -- "$notify_temporary"
  return 1
}

read_acknowledged_state() {
  local notify_acknowledged=unknown
  if [[ -f "$state_file" ]]; then
    notify_acknowledged=$(<"$state_file")
    [[ "$notify_acknowledged" =~ ^[A-Z_]{1,32}$ ]] || notify_acknowledged=unknown
  fi
  printf '%s\n' "$notify_acknowledged"
}

failure_attribution() {
  local notify_journal notify_line notify_script notify_status
  local -a notify_matches=() notify_unique_results=()
  application=DNS
  component='Keepalived PIHOLE_DUALSTACK'
  check_name=ownership-state
  failure_class=eligibility-fault-unclassified
  bounded_status="keepalived_state=$current_state"
  first_check='journalctl -u keepalived.service -n 50 --no-pager'
  [[ "$current_state" = FAULT ]] || return 0
  notify_journal=$($journalctl_command --quiet --no-pager -u keepalived.service \
    --since '-10 seconds' -n 80 -o cat 2>/dev/null || :)
  mapfile -t notify_matches < <(grep -E \
    'VRRP_Script\(check-(dns|caddy)\) failed \(exited with status [0-9]+\)' \
    <<<"$notify_journal" || :)
  ((${#notify_matches[@]} > 0)) || return 0
  mapfile -t notify_unique_results < <(printf '%s\n' "${notify_matches[@]}" |
    sed -n 's/.*VRRP_Script(check-\(dns\|caddy\)) failed (exited with status \([0-9][0-9]*\)).*/\1:\2/p' |
    sort -u)
  ((${#notify_unique_results[@]} == 1)) || return 0
  notify_line=${notify_matches[-1]}
  notify_script=$(sed -n 's/.*VRRP_Script(check-\(dns\|caddy\)).*/\1/p' <<<"$notify_line")
  notify_status=$(sed -n 's/.*exited with status \([0-9][0-9]*\).*/\1/p' <<<"$notify_line")
  [[ "$notify_status" =~ ^([0-9]|[1-9][0-9]|1[0-9][0-9]|2[0-4][0-9]|25[0-5])$ ]] || return 0
  bounded_status="helper=check-$notify_script exit=$notify_status"
  case "$notify_script:$notify_status" in
    dns:10)
      component='Pi-hole FTL'
      check_name=systemd-unit
      failure_class=service-inactive
      ;;
    dns:11)
      component=Unbound
      check_name=systemd-unit
      failure_class=service-inactive
      ;;
    dns:2[0-7])
      component='Pi-hole FTL and Unbound'
      check_name=exact-dns-answer
      failure_class=dns-answer-mismatch
      ;;
    caddy:10)
      application=Proxy
      component=Caddy
      check_name=protected-environment
      failure_class=ownership-mismatch
      ;;
    caddy:11)
      application=Proxy
      component=Caddy
      check_name=systemd-unit
      failure_class=service-inactive
      ;;
    caddy:20)
      application=Proxy
      component=Caddy
      check_name=ipv4-trusted-https
      failure_class=https-probe-failed
      ;;
    caddy:21)
      application=Proxy
      component=Caddy
      check_name=ipv6-trusted-https
      failure_class=https-probe-failed
      ;;
    *) return 0 ;;
  esac
  first_check="sudo -u keepalived_script /usr/local/libexec/check-$notify_script.sh"
}

planned_maintenance_context() {
  planned_maintenance=no
  maintenance_id=none
  [[ -f "$maintenance_file" && ! -L "$maintenance_file" ]] || return 0
  [[ "$(stat -c '%U:%G:%a' "$maintenance_file")" = root:root:644 ]] || return 0
  [[ "$(wc -l <"$maintenance_file")" -eq 1 ]] || return 0
  IFS=$'\t' read -r maintenance_schema maintenance_id maintenance_expiry <"$maintenance_file"
  [[ "$maintenance_schema" = caddy-planned-maintenance/v1 ]] || return 0
  [[ "$maintenance_id" =~ ^[A-Za-z0-9._:-]{1,128}$ ]] || return 0
  [[ "$maintenance_expiry" =~ ^[0-9]{10}$ ]] || return 0
  if ((maintenance_expiry >= $($date_command +%s))); then
    planned_maintenance=yes
  else
    maintenance_id=none
  fi
}

enqueue_transition() {
  local previous_state=$1
  current_state=$2
  local stable_id=$3
  local observed_at=$4
  local short_hostname local_role=unknown peer_role=unknown
  local local_vip_count address_inventory vip
  local event_name=state-transition severity=warning
  local impact='DNS and Proxy ownership state changed'
  local failover_occurred=no
  local network_context='DNS VIPs 10.1.0.55 and fd36:5aa8:6971:1::55; Proxy VIPs 10.1.0.56 and fd36:5aa8:6971:1::56'
  local ha_context
  short_hostname=$($hostname_command -s 2>/dev/null || printf unknown)
  case "$short_hostname" in
    j1-svpihole0)
      local_role=preferred-node-a
      peer_role=standby-node-b
      ;;
    j1-svpihole00)
      local_role=standby-node-b
      peer_role=preferred-node-a
      ;;
  esac
  if address_inventory=$($ip_command -o address show dev eth0 2>/dev/null); then
    local_vip_count=0
    for vip in 10.1.0.55/22 10.1.0.56/22 \
      fd36:5aa8:6971:1::55/128 fd36:5aa8:6971:1::56/128; do
      grep -Fq " $vip " <<<"$address_inventory" && local_vip_count=$((local_vip_count + 1))
    done
  else
    local_vip_count=unknown
  fi
  failure_attribution
  planned_maintenance_context
  case "$current_state" in
    MASTER)
      severity=success
      event_name=recovery
      failure_class=none
      impact='Node owns all DNS and Proxy VIPs and serves both applications'
      if [[ "$local_role" = standby-node-b ]]; then
        event_name=failover
        failover_occurred=yes
      fi
      ;;
    BACKUP)
      severity=info
      event_name=standby
      failure_class=none
      impact='Node owns no shared VIPs and remains available as standby'
      ;;
    FAULT)
      severity=failure
      event_name=failure
      failover_occurred=pending-peer-convergence
      impact='Node is ineligible; coupled DNS and Proxy VIPs must move to the healthy peer'
      ;;
    STOP)
      if [[ "$planned_maintenance" = yes ]]; then
        severity=info
        event_name=planned-maintenance
        failure_class=none
        impact="Authorized maintenance $maintenance_id stopped local VIP ownership"
      fi
      ;;
  esac
  ha_context="group=$name type=$type local_state=$current_state local_vips=$local_vip_count local_role=$local_role peer_role=$peer_role failover=$failover_occurred maintenance=$planned_maintenance"
  "$apprise_enqueue" --source keepalived --severity "$severity" \
    --event-key "${type}:${name}:${current_state}:${component}:${check_name}" \
    --stable-id "$stable_id" --application "$application" --component "$component" \
    --check "$check_name" --event "$event_name" --state "$previous_state -> $current_state" \
    --impact "$impact" --failure-class "$failure_class" --network-context "$network_context" \
    --ha-context "$ha_context" --status "$bounded_status" --timing "observed: $observed_at" \
    --correlation "$stable_id" --evidence 'journalctl -u keepalived.service -t keepalived-notify' \
    --first-check "$first_check"
}

exec 9>"$lock_file"
chmod 0600 "$lock_file"
flock -x 9 || exit 0
if [[ -e "$pending_file" || -L "$pending_file" ]]; then
  IFS=$'\t' read -r pending_previous pending_current pending_id pending_observed <"$pending_file"
  if [[ ! "$pending_previous" =~ ^[A-Z_]{1,32}$ ||
    ! "$pending_current" =~ ^[A-Z_]{1,32}$ || ! "$pending_id" =~ ^[0-9a-f]{64}$ ||
    ! "$pending_observed" =~ ^[0-9TZ:-]{20}$ ]]; then
    "$logger_command" -t keepalived-notify 'malformed pending transition retained'
    exit 0
  fi
  if [[ "$pending_previous" != "$(read_acknowledged_state)" ]]; then
    "$logger_command" -t keepalived-notify 'contradictory pending transition retained'
    exit 0
  fi
  if enqueue_transition "$pending_previous" "$pending_current" "$pending_id" "$pending_observed"; then
    atomic_line "$state_file" "$pending_current" || exit 0
    rm -f -- "$pending_file"
    "$logger_command" -t keepalived-notify "pending transition acknowledged: $pending_previous -> $pending_current"
  else
    "$logger_command" -t keepalived-notify "pending transition enqueue retry failed: $pending_previous -> $pending_current"
    exit 0
  fi
  [[ "$pending_current" = "$state" ]] && exit 0
fi

previous_state=$(read_acknowledged_state)
observed_at=$($date_command -u +%Y-%m-%dT%H:%M:%SZ)
stable_id=$(printf '%s\0%s\0%s\0%s\0%s\0%s' "$type" "$name" "$previous_state" "$state" \
  "$observed_at" "$$" | sha256sum | awk '{ print $1 }')
atomic_line "$pending_file" "$previous_state"$'\t'"$state"$'\t'"$stable_id"$'\t'"$observed_at" || exit 0
"$logger_command" -t keepalived-notify "Instance ${name} (${type}) changed: ${previous_state} -> ${state}"
if enqueue_transition "$previous_state" "$state" "$stable_id" "$observed_at"; then
  atomic_line "$state_file" "$state" || exit 0
  rm -f -- "$pending_file"
  "$logger_command" -t keepalived-notify "Apprise notification acknowledged for ${name} (${type}) state ${state}"
else
  "$logger_command" -t keepalived-notify "Apprise notification enqueue failed for ${name} (${type}) state ${state}"
fi
exit 0
