# Uptime Kuma DNS onboarding

Status: sealed local candidate; no execution authority. The application
[plan and ledger](../../../homelab-monitoring-observability/changes/2026-11-09-uptime-kuma/WORK.md)
own the combined change. This review owns only the DNS operation.

## Candidate and provenance

Append six records to each node's existing local-zone file: dashboard A/AAAA
for `uptime.local.theama.co` to Proxy VIPs `10.1.0.56` and
`fd36:5aa8:6971:1::56`; host A/AAAA for `j2-svpi3bmf.local.theama.co` to
`10.1.3.75` and `fd36:5aa8:6971:1::75`; and the two host PTR records. Proxy
PTRs and all unrelated records remain unchanged.

The November 9 observations on both nodes match the October 21 accepted owner
candidate byte for byte. The proposed addition matches the previously validated
Unbound candidate retained by the application change. The node transaction,
dispatcher and paired gate are byte-identical to the accepted owner bundle.
Reuse that qualification; no new DNS fixtures or simulated failover are required.

Boot identity, non-zone configuration hashes, the Pi-hole executable and SSH
host-key pins retain their earlier owner provenance. They are expected inputs,
not new observations. Exact preflight must reject drift before mutation. An
expired operation or changed input requires review, not an automatic refresh.

## Execution boundary

Require accepted Caddy onboarding before publishing the dashboard DNS records.
Use the existing [owner transaction](host-record-deployment.md), selected by
`atomic-zone-full-restart-v2`, on `pi@10.1.0.54` before `pi@10.1.0.53`. The
initial paired gate must confirm that .53 owns the coupled VIP group; otherwise
stop before mutation rather than silently changing the reviewed node order.

On each node: verify bound inputs and stage the native configuration check;
atomically replace only the zone file; fully restart Unbound and establish its
health; then fully restart Pi-hole DNS. Gate the first node before advancing.
Require exact answers over both families, existing local/public DNS controls,
healthy services, and coherent ownership of all four linked DNS/Proxy VIPs.
Normal cluster-driven movement is permitted; forced failover and Caddy edits
or restarts are excluded.

Run phases once in this order: `before`, `apply-secondary`, `after-secondary`,
`apply-primary`, `after-all`. A phase failure stops progression. Dispatchers and
gates retain one-use receipts; no phase may be replayed to obtain a passing
sample. Keep the fresh 120-second paired-gate requirement before each mutation.

After paired acceptance, verify trusted HTTPS at the ordinary dashboard hostname
from the workstation over IPv4 and IPv6, with bounded requests to `/dashboard`
expecting 200. Record any client-resolution failure separately from successful
node/VIP DNS acceptance; do not claim application closeout from DNS checks alone.

## Recovery and exclusions

Restore only changed nodes, in reverse order, from their own exact backups.
Restoration includes native validation, a full Unbound restart followed by a full
Pi-hole DNS restart, and paired acceptance. For two changed nodes, use
`rollback-primary`, `after-rollback-primary`, `rollback-secondary`, then
`after-rollback-all`. If only the secondary changed, restore only it and verify
`after-rollback-all`. Inspect the transaction's terminal result before selecting
recovery: an automatic, verified restoration must not be repeated.

A lost worker, unknown write state, changed destination, unavailable backup or
unproved recovery requires manual intervention. Preserve evidence and durable
state; no automatic replay, forced failover, cleanup, backend stop or reboot.

Monitors, alerts, synthetic notifications, route/radio changes, unrelated DNS
records and application account changes remain outside this operation. Exact
bundle identity and execution phases are recorded in the application ledger
and the private sealed review. The archive SHA-256 is
`620d307ced006fb84755b4e735048170ed25e394320c2c677c08f93878a338bf`.
The existing owner runner passed its local closed-archive check; no target was
contacted.
