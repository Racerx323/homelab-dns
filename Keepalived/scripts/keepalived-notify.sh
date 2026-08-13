#!/usr/bin/env bash

set -u

# Arguments passed by Keepalived: $1=TYPE, $2=NAME, $3=STATE
TYPE=${1:-UNKNOWN}
NAME=${2:-UNKNOWN}
STATE=${3:-UNKNOWN}

readonly APPRISE_ENQUEUE=/usr/local/libexec/caddy-apprise-enqueue

# Log locally to the system journal
logger -t keepalived-notify "Instance ${NAME} (${TYPE}) changed to state: ${STATE}"

# Format the message content
HOSTNAME=$(hostname)
TITLE="[Failover Alert] Pi-hole DNS Cluster"

# Customize body based on state transitions
case "$STATE" in
  MASTER)
    NOTIFY_TYPE="success"
    BODY="⚠️ DNS Service has failed over! Node '${HOSTNAME}' has transitioned to MASTER and is now actively serving your network's DNS traffic on the Virtual IPs."
    ;;
  BACKUP)
    NOTIFY_TYPE="info"
    BODY="ℹ️ Node '${HOSTNAME}' has transitioned to BACKUP state and is now on standby."
    ;;
  FAULT)
    NOTIFY_TYPE="failure"
    BODY="🚨 CRITICAL: Node '${HOSTNAME}' has entered a FAULT state. The local Pi-hole or Unbound services failed health checks, triggering a DNS service failover!"
    ;;
  *)
    NOTIFY_TYPE="warning"
    BODY="⚠️ Node '${HOSTNAME}' has experienced an unexpected Keepalived state change to: ${STATE}."
    ;;
esac

# The Caddy-owned queue is the only delivery owner. Keepalived performs one
# bounded local enqueue and never waits on the Apprise network endpoint.
if "$APPRISE_ENQUEUE" \
  --source keepalived \
  --severity "$NOTIFY_TYPE" \
  --event-key "${TYPE}:${NAME}:${STATE}" \
  --title "$TITLE" \
  --body "$BODY"; then
  logger -t keepalived-notify \
    "Apprise notification queued for ${NAME} (${TYPE}) state ${STATE}"
else
  ENQUEUE_STATUS=$?
  logger -t keepalived-notify \
    "Apprise notification enqueue failed for ${NAME} (${TYPE}) state ${STATE}: status ${ENQUEUE_STATUS}"
fi

exit 0
