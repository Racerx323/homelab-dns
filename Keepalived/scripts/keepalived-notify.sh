#!/usr/bin/env bash

set -Eeuo pipefail
set +x
PATH=/usr/bin:/bin
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
readonly state_root=${KEEPALIVED_NOTIFY_STATE_ROOT:-/run/caddy-serving-health/keepalived}

[[ "$type" =~ ^[A-Z_]{1,32}$ ]] || exit 0
[[ "$name" =~ ^[A-Za-z0-9_-]{1,64}$ ]] || exit 0
[[ "$state" =~ ^[A-Z_]{1,32}$ ]] || exit 0

"$logger_command" -t keepalived-notify "Instance ${name} (${type}) changed to state: ${state}"

short_hostname=$("$hostname_command" -s 2>/dev/null || printf unknown)
local_role=unknown
peer_role=unknown
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
state_file=$state_root/$name
previous_state=unknown
if [[ -f "$state_file" && ! -L "$state_file" &&
  "$(wc -l <"$state_file")" -eq 1 ]]; then
  previous_state=$(<"$state_file")
  [[ "$previous_state" =~ ^[A-Z_]{1,32}$ ]] || previous_state=unknown
fi
if [[ -d "$state_root" && ! -L "$state_root" ]]; then
  state_temporary=$(mktemp "$state_root/.${name}.XXXXXX" 2>/dev/null || true)
  if [[ -n "$state_temporary" ]]; then
    if printf '%s\n' "$state" >"$state_temporary" &&
      chmod 0644 "$state_temporary"; then
      mv -fT -- "$state_temporary" "$state_file" || rm -f -- "$state_temporary"
    else
      rm -f -- "$state_temporary"
    fi
  fi
fi
local_vip_count=unknown
if address_inventory=$("$ip_command" -o address show dev eth0 2>/dev/null); then
  local_vip_count=0
  for vip in 10.1.0.55/22 10.1.0.56/22 \
    fd36:5aa8:6971:1::55/128 fd36:5aa8:6971:1::56/128; do
    grep -Fq " $vip " <<<"$address_inventory" && local_vip_count=$((local_vip_count + 1))
  done
fi

application=DNS
component='Keepalived PIHOLE_DUALSTACK'
check_name=ownership-state
event_name='state-transition'
severity=warning
state_transition="$previous_state -> $state"
impact='DNS and Proxy ownership state changed'
failure_class='state-transition'
network_context='DNS VIPs 10.1.0.55 and fd36:5aa8:6971:1::55; Proxy VIPs 10.1.0.56 and fd36:5aa8:6971:1::56'
failover_occurred=no
ha_context="group=$name type=$type local_state=$state local_vips=$local_vip_count local_role=$local_role peer_role=$peer_role failover=$failover_occurred"
bounded_status="keepalived_state=$state"
first_check='systemctl status keepalived.service'

case "$state" in
  MASTER)
    severity=success
    event_name=recovery
    if [[ "$local_role" = standby-node-b ]]; then
      event_name=failover
      failover_occurred=yes
    fi
    impact='Node owns all DNS and Proxy VIPs and serves both applications'
    failure_class=none
    ;;
  BACKUP)
    severity=info
    event_name=standby
    impact='Node owns no shared VIPs and remains available as standby'
    failure_class=none
    ;;
  FAULT)
    severity=failure
    event_name=failure
    impact='Node is ineligible; coupled DNS and Proxy VIPs must move to the healthy peer'
    failure_class=eligibility-fault-unclassified
    failover_occurred=pending-peer-convergence
    first_check='journalctl -u keepalived.service -n 50 --no-pager'
    ;;
esac

ha_context="group=$name type=$type local_state=$state local_vips=$local_vip_count local_role=$local_role peer_role=$peer_role failover=$failover_occurred"

observed_at=$("$date_command" -u +%Y-%m-%dT%H:%M:%SZ)
correlation="${type}-${name}-${state}-$("$date_command" -u +%Y%m%dT%H%M)"

if "$apprise_enqueue" \
  --source keepalived \
  --severity "$severity" \
  --event-key "${type}:${name}:${state}:${component}:${check_name}" \
  --stable-id "$correlation" \
  --application "$application" \
  --component "$component" \
  --check "$check_name" \
  --event "$event_name" \
  --state "$state_transition" \
  --impact "$impact" \
  --failure-class "$failure_class" \
  --network-context "$network_context" \
  --ha-context "$ha_context" \
  --status "$bounded_status" \
  --timing "observed: $observed_at" \
  --correlation "$correlation" \
  --evidence 'journalctl -u keepalived.service -t keepalived-notify' \
  --first-check "$first_check"; then
  "$logger_command" -t keepalived-notify \
    "Apprise notification queued for ${name} (${type}) state ${state}"
else
  enqueue_status=$?
  "$logger_command" -t keepalived-notify \
    "Apprise notification enqueue failed for ${name} (${type}) state ${state}: status ${enqueue_status}"
fi

exit 0
