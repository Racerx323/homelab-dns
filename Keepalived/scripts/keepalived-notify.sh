#!/usr/bin/env bash

set -u

# Arguments passed by Keepalived: $1=TYPE, $2=NAME, $3=STATE
TYPE=${1:-UNKNOWN}
NAME=${2:-UNKNOWN}
STATE=${3:-UNKNOWN}

# --- Apprise Configuration Variables ---
APPRISE_URL="http://10.1.3.83:8000"
APPRISE_KEY="apprise"
APPRISE_ENDPOINT="${APPRISE_URL}/notify/${APPRISE_KEY}"

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

# Keep notification delivery asynchronous so an Apprise outage cannot block a
# VRRP transition. Log JSON, transport, and HTTP errors to the system journal.
(
  if ! PAYLOAD=$(jq -n \
    --arg title "$TITLE" \
    --arg body "$BODY" \
    --arg type "$NOTIFY_TYPE" \
    '{title: $title, body: $body, type: $type, format: "text"}'); then
    logger -t keepalived-notify \
      "Unable to build Apprise payload for ${NAME} (${TYPE}) state ${STATE}"
    exit 1
  fi

  if RESPONSE=$(curl \
    --silent \
    --show-error \
    --fail-with-body \
    --connect-timeout 2 \
    --max-time 5 \
    --request POST "$APPRISE_ENDPOINT" \
    --header "Content-Type: application/json" \
    --data "$PAYLOAD" 2>&1); then
    logger -t keepalived-notify \
      "Apprise notification delivered for ${NAME} (${TYPE}) state ${STATE}"
  else
    CURL_STATUS=$?
    logger -t keepalived-notify \
      "Apprise notification failed for ${NAME} (${TYPE}) state ${STATE}: curl exit ${CURL_STATUS}: ${RESPONSE}"
  fi
) &

exit 0
