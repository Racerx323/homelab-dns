# Uptime Kuma DNS onboarding

Status: DNS deployment and ordinary-name dual-stack HTTPS accepted November 12, 2026.
The one-attempt approval is consumed; no further live authority.
Both failed deployments and completed readiness captures remain consumed. The application
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

## Local reconciliation — November 12, 2026

The original November 11 DNS approval remains unused. Its Caddy prerequisite is
satisfied by retained accepted primary-first release evidence and W-106 private
login/WebSocket plus passive observation acceptance. Both observation records
and the private receipt passed the existing local combined verifier again;
this does not refresh live service health.

The archive, all frozen members and index pass the owner's local `check` action.
The three execution helpers still match their owner sources. No phase invocation
or execution receipt exists in the sealed directory. Retained qualification and
six non-zone provenance files match their bound hashes. The sealed files,
authorization identity and original timestamps remain unchanged.

The repository zone has the same directive multiset as the sealed baseline but
orders records differently. It is neither the exact live-baseline file nor the
six-record candidate. Use the sealed candidate; do not replace its parent bytes
with the repository file or weaken the exact live preflight. Reconcile repository
record content and accepted live identity after a successful DNS transition.

Expiry remains **November 14, 2026 at 11:02:35 a.m. CST**
(`2026-11-14T17:02:35+00:00`). The runner requires more than five minutes remaining
on every invocation, including recovery: its effective invocation cutoff is
**10:57:35 a.m. CST** that day. Leave sufficient time for the whole operation and
recovery. Expiry does not authorize changing timestamps or bypassing a guard.

The recommended next live work is the existing five-phase sequence above,
once Aaron requests execution to resume. The earlier approval need not be
duplicated while the exact scope, inputs and expiry still hold. His November 12
request authorizes only local reconciliation; no host contact, phase execution,
DNS query, service restart, fresh seal or publication occurred. Live preflight
must still establish the expected baseline, health and coupled VIP ownership.
Any mismatch stops progression under the existing recovery rules.

## Initial gate failed — November 12, 2026

Aaron approved resuming the unchanged operation after local reconciliation.
The one-use `before` phase exited 1 at its bounded convergence deadline, with
repeated `snapshot_transport_failed` errors. The gate receipt remains rejected.
The verifier discards the underlying subprocess status/output, so this result
does not identify an SSH cause or establish an unhealthy DNS/HA service.

No apply phase ran: no zone replacement, service restart or rollback occurred.
The read-only gate requires no recovery. The operation and its approval are now
consumed; do not replay the gate or advance to mutation. Preserve the archive
and all receipts. W-118 in the application ledger tracks local diagnosis and
bounded failure reporting before a separately reviewed successor. The earlier
expiry does not authorize another attempt. DNS remains pending.

## Failure reporting qualified locally — November 12, 2026

W-118 is resolved for local correction and qualification. The current owner
verifier now retains bounded snapshot diagnostics as described in the
[owner procedure](host-record-deployment.md#prepared-execution-helpers).
The existing offline suite passes 34 tests, including execution of the actual
streamed node source through local Python, safe transport/remote rejection
classification, timeout/launch/output-limit/invalid-result cases, unchanged
successful decoding, and diagnostic retention at the paired-gate deadline.
Secret canaries in output and exception messages are not emitted.

This proves the reporting correction, not the cause of the historical live
failure. No new DNS fixture, simulated failover, container or live probe was used.
The consumed archive, extracted members and failed receipts remain unchanged.
Current source differs from that consumed verifier; a successor needs separate
preparation and review. None is sealed or authorized by these local checks.

## Successor awaiting approval — November 12, 2026

The prepared successor is `uptime-kuma-dns-20261112-q8i4a51n`, archive SHA-256
`0cc507728f976d0b51acb30803e785428b901c3fe4a68d6bedd3d77acc45c089`.
Its private directory is under
`/home/aaron/code/.local-evidence/homelab-dns/current/` with the operation name.
The application ledger's exact successor review owns the approval request;
its sealed `review.md` contains the individual execution and recovery commands.

The six-record candidate and all baseline checks are unchanged. The verifier
uses W-118's qualified safe diagnostics; operation and backup identities are
fresh. The predecessor and failed receipts remain intact. Local seal/member/index
checks, qualification identity checks and secret scanning pass; a wrong archive
digest is rejected. No phase has run and no live authority is inferred.

Expiry remains November 14 at 11:02:35 a.m. CST, with a 10:57:35 a.m. invocation
cutoff applying to every phase, including recovery. Plan enough time for the
whole operation. The prior approval is consumed; this new archive requires
separate exact-bundle approval. No host identity was refreshed or guard relaxed,
and the unknown historical failure may still reject this attempt.

## November 12 successor execution result

The exact successor above was approved for one attempt. Its `before` phase
failed with secondary `boot_identity_mismatch` (remote exit 1; expected 0).
The paired gate was not accepted; primary contact was not reached. No apply
phase, zone write or service restart occurred, and no recovery is required.
The current boot value and change timing were not collected. This explains
this attempt's rejection but does not prove the earlier failure's cause.

The private successor directory retains the unchanged archive, authorization,
invocation, controller log/status, failed gate and hashed terminal summary.
Session 3863 ended with exit 1. W-120 in the application ledger tracks retained
identity reconciliation before any separately reviewed inspection or successor.
No retry, new live inspection or source publication is authorized.

## Retained boot provenance reconciled — November 12, 2026

W-120 traces the secondary boot prerequisite to the October 20 readiness capture
and October 21 accepted DNS operation. Both consumed November attempts inherited
it unchanged. The reviewed November 9 DNS captures and accepted proxy observation
do not contain a newer boot identity. Current boot identity and change timing
remain unknown; the earlier attempt's cause remains unproved.

The guard rejected before binary/include/file/service checks; primary inspection
was not reached. Prepare a bounded paired read-only refresh under
[deployment readiness](host-record-deployment.md#deployment-readiness), tracked
as W-121 in the application ledger, before another deployment candidate.
Do not substitute only a boot ID or relax checks. Reconcile any current drift
before rebuilding the six-record candidate. Both archives and failed receipts
were hash-verified and remain unchanged. No fresh live work is authorized.

## Paired readiness prepared — November 12, 2026

The existing owner collector's `--uptime` mode is locally qualified and frozen
in `uptime-kuma-dns54-readiness-20261112-v2` and
`uptime-kuma-dns53-readiness-20261112-v2` under the private DNS evidence store.
The application ledger owns their exact archive digests, commands, expiry,
secondary-first scope and stop conditions. This review authorizes no contact.

Capture current boot identity rather than supplying an old expected value;
require stable identity throughout the read. Refresh bounded DNS configuration,
service/executable identities, record answers and coupled VIP ownership together.
Do not accept deployment readiness from a successful capture flag alone. Compare
both records locally before preparing a new deployment. The six-record change,
exact deployment checks and both consumed attempts remain unchanged.

## Paired readiness completed — November 12, 2026

Both v2 captures completed once, .54 followed by .53, and local paired comparison
passed. Both boot IDs are newer than the inherited October identities and stable
within capture. Bound effective files/metadata and the Pi-hole launcher hash match;
current native configuration checks and exact preserved DNS controls pass. All six
proposed records remain absent across the planned endpoints. All four linked VIPs
are coherently on .53; Unbound/Pi-hole/Keepalived/Caddy are active on both nodes.

The alternate Pi-hole launcher path was absent and the versions file failed the
protected-read policy; the actual bound launcher hash and local v5.18.3 Git tag
were captured. Synchronization projection remains incomplete and does not replace
the owner contract or retained control qualification. Readiness observations do
not authorize new changes or establish continuous HA stability.

The application ledger and private `dns-paired-readiness-result-3_ajijte` result
record comparison details and receipt hashes. Both capture approvals are consumed;
no mutation/recovery occurred. Prepare a fresh deployment candidate from these
observations for separate review, preserving both failed deployment bundles and
these completed captures. No replay or further live work is authorized.

## Boot continuity implementation qualified — November 12, 2026

W-122 implements the approved policy in the existing node, paired gate and
dispatcher. A new operation selects `boot_policy: operation-admission-v1` and
captures boot IDs during authenticated live admission rather than requiring
historical values. The accepted initial receipt binds both IDs to the operation
and digest; subsequent gates, apply and rollback reuse them. Unexpected reboot
or incomplete initial admission stops progression; resume cannot reset the IDs.
All exact configuration, host-key, health and freshness checks remain.

The existing suites pass 42 transaction and 27 readiness tests. Source syntax,
secret scan and preserved archive/receipt hashes pass. This is local qualification,
not deployment acceptance. Both failed deployments and completed captures remain
unchanged. No successor is sealed, and no live action or replay is authorized.
See the [owner continuity contract](host-record-deployment.md#operation-scoped-boot-continuity)
and application ledger for evidence and next preparation work.

## Admission-policy successor prepared — November 12, 2026

`uptime-kuma-dns-admission-20261112-myuc3p0t` is sealed under the private DNS evidence store.
Archive SHA-256: `d89d3b0c252dc86173ef98603539189ca96dc46dff55c333e2352e004cbb8e2e`. The application ledger's exact W-123 review owns
commands, approval, stop conditions and recovery; this document grants no authority.

The archive uses W-122 qualified source and hash-bound W-121 paired readiness.
Current boot IDs are captured at live admission, then retained across gates,
apply and recovery. Preparation-time observed IDs are provenance only. Baseline,
six-record candidate, expanded configuration, host keys, exact file identities,
node order, restarts and recovery scope remain unchanged. Both failed deployments
and completed inspections remain immutable.

Local archive/input and allowed-delta checks pass; wrong digest and absent
admission evidence are rejected. Exact-directory secret scan passes and qualified
source hashes match. No phase has run. Expiry remains November 14 at 11:02:35 a.m.
CST, with the 10:57:35 a.m. invocation cutoff applying to every phase including
recovery. Fresh exact-bundle approval is required for one attempt.

## Deployment accepted — November 12, 2026

Aaron approved archive
`d89d3b0c252dc86173ef98603539189ca96dc46dff55c333e2352e004cbb8e2e`
for one attempt. All five phases passed: admission, secondary apply, paired
secondary acceptance, primary apply and final paired acceptance. Admission
captured current boot IDs; all subsequent gates and mutations preserved them.
Both nodes installed candidate
`2df1be44a9ea39a35df1e75db16d72a4138b4ab3048fdc7bcf58bd7ff1a959dc`,
with native validation and full Unbound/Pi-hole DNS restarts on each node.

Exact DNS answers, preserved local/public controls, paired service/Caddy health
and coherent four-VIP ownership passed. All retained VIP samples show .53 as
owner. Both normal-name dashboard HTTPS requests returned 200 with trusted TLS.
No rollback, forced failover, reboot or Caddy mutation was needed.

Private evidence and hash-indexed terminal summary are under
`.local-evidence/homelab-dns/current/uptime-kuma-dns-admission-20261112-myuc3p0t/`
in the workspace. Both nodes retain their exact backups in
`/var/backups/uptime-kuma-dns-admission-20261112-myuc3p0t`.
The repository zone preserves prior ordering and now matches the accepted
candidate's directives; repository and installed byte hashes differ intentionally.
Earlier consumed attempts remain immutable. No replay, backup cleanup or Git
publication is authorized. Application W-124 records the combined acceptance;
W-020/W-076 and documentation/closeout remain separate.
