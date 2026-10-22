# Host DNS record deployment

The [NTP1 IPv6 prerequisite review](ntp1-ipv6-prerequisite-review.md) defines an
independent two-record candidate required before the svmf network successor.
Its read-only readiness and deployment need separate exact-hash bundles; do not
combine it with pending Munin/svmf changes or reuse historical node baselines.

The [Munin/svmf dual-stack review](munin-host-record-review.md) executed and
passed October 21 at 10:12:30 CDT: three append-only records, .54 accepted before
.53, both full DNS restarts per node, and final paired DNS/Caddy acceptance.
Backups remain and all five phase receipts are consumed. Further DNS changes
need a new exact-hash operation. Monitoring acceptance remains separate.

## NTP-only deployment accepted — October 21, 2026

The [NTP prerequisite review](ntp1-ipv6-prerequisite-review.md#deployment-accepted--october-21-2026)
records successful .54-first/.53-second atomic updates and full Unbound/Pi-hole
restarts under archive SHA-256
`54224a0beac93bc715a8af42ce39b673a7b14f18ac300e1524f714364f03d545`.
All exact NTP DNS and paired DNS/Caddy health gates passed. Both nodes serve AAAA
::51 and its canonical IPv6 PTR; preserved IPv4 and unrelated local checks passed.
All retained samples show the four-VIP group on .53. No rollback or forced
failover occurred. Backups/durable state remain; receipts are consumed. This
accepts the NTP record change, not later Munin/svmf records or all Phase 5 DNS.

## Prepared change: Nautobot host

Status: deployed and verified on both nodes on September 21, 2026. All 24
node/VIP DNS checks and both FQDN SSH checks passed. The initial failed attempt
and verified rollback remain historical evidence; see the retry result below.
The owning source is [pihole-local-zone.conf](../configs/pihole-local-zone.conf),
installed as `/etc/unbound/unbound.conf.d/pihole-local-zone.conf` on both nodes.
This record-only change does not use the package-upgrade scripts.

| Record | Name/address | Value |
| --- | --- | --- |
| A | `j2-svpi4mf.local.theama.co.` | `10.1.2.170` |
| AAAA | `j2-svpi4mf.local.theama.co.` | `fd36:5aa8:6971:1::170` |
| PTR | `10.1.2.170` | `j2-svpi4mf.local.theama.co.` |
| PTR | `fd36:5aa8:6971:1::170` | `j2-svpi4mf.local.theama.co.` |

The September 21 read-only collection found all four records absent from both
node fragments, and all 24 node/VIP queries returned NXDOMAIN. Relevant Pi-hole
forward/reverse forwarding entries were present. The host's permanent ULA and
literal IPv4/IPv6 SSH passed. Evidence is private under
`/home/aaron/code/.local-evidence/nautobot-stage4-review-20260921/`.

The complete acceptance matrix is in the consumer's
[stage-4 roadmap](../../../homelab-server-configs/Nautobot/docs/ROADMAP.md#dns-acceptance-matrix).
This document owns the DNS deployment boundary, not Nautobot acceptance.

## Current local-zone update contract

Operator clarification, October 20, 2026: Unbound local-zone synchronization is
not implemented. Caddy replication on these nodes is separate. Install the
reviewed local-zone file independently on each node using atomic replacement,
then validate and fully restart Unbound followed by Pi-hole DNS. Both full
restarts also apply to rollback. Earlier operation outcomes and frozen bundles
below are historical; they do not authorize or implement this revised contract.

Cluster-driven failover during a node update is permitted within the reviewed
convergence window. Require the other node healthy and serving before the update,
then recheck both nodes and coherent ownership of all four linked DNS/Proxy
VIPs before progressing. PIHOLE_DUALSTACK moves DNS .55/::55 and Proxy .56/::56
together; Caddy fails over with DNS. Include brief Caddy service and verified-TLS
proxy health checks, without Caddy configuration/restart or sync changes.
Do not require ownership to remain on its initial node. Persistent split,
duplicate or missing ownership and lost baseline DNS service stop progression.
No forced Keepalived transition or Caddy synchronization change is included.

## Deployment readiness

Before requesting the separate live change, preserve a bounded, read-only
snapshot of both nodes' current local-zone file, file owner/group/mode and hash,
active main configuration/include graph, Unbound binary/version and effective
service/restart configuration. Capture the journal cursor and current health on
each node. Use `pi` with existing SSH credentials and strict host-key verification.
Do not collect control private keys or unrestricted configuration archives.

Confirm which node currently owns both DNS VIPs and that the peer is healthy
and serving. Names and HA preference do not prove active role. The operator
confirms no Unbound local-zone synchronization; do not require Caddy synchronization
qualification or disable its jobs for this update. Mixed initial VIP ownership
or unrelated source/live drift stops readiness. Record normal failover rather
than pinning the initial owner; do not force VIP movement.

Compare both deployed fragments with the candidate's parent version. Require
that the proposed per-node diff adds only the operation's reviewed records. Preserve
unrelated records; never overwrite live drift with the repository file. Conflicting
forward or reverse records in any effective include stop deployment. Existing
identical records call for reconciliation rather than duplicate insertion.

Prepare one reviewed execution bundle containing the exact candidate, per-node
before hashes/metadata, ordered actions, validation queries, rollback commands
and source revision. Hash all non-secret execution inputs. This document and
the source-file hash alone are not an executable authorization bundle.

Native `unbound-checkconf` is unavailable on the preparation workstation. The
authorized readiness review validated the candidate in memory using each node’s
installed Unbound 1.17.1 checker and captured effective includes; both passed.
This is configuration validation, not an Unbound package-upgrade qualification.
Local record/diff checks alone do not substitute for native validation. Before live replacement, validate a
protected candidate configuration tree with the target's installed checker,
resolving includes to staged candidate files while preserving required production
semantics. Avoid accidentally validating the old live include instead of the
candidate. Native validation and any staging transfer must be included in the
reviewed live scope; do not install packages just to bypass this readiness gap.

## Authorized execution sequence

After exact-bundle authorization, deploy one node at a time, current non-VIP
owner first. In the usual topology this is `pi@10.1.0.54`, followed by
`pi@10.1.0.53`. Re-evaluate actual roles before each node update. Stop on reviewed file/input
drift, unhealthy peer or ambiguous roles; coherent cluster-driven failover is
handled by the reviewed HA gate.

1. Create an exclusive mode-0700 node-local backup directory. Preserve exact
   original bytes and metadata of the one destination file, and record its hash.
   Keep each node's backup distinct and outside active include paths. Recheck that
   the destination is the reviewed regular file, not an unexpected symlink.
2. Stage the candidate in a non-included path; verify its hash and validate the
   candidate tree. Create the replacement temporary file in the destination
   directory on the same filesystem, outside its included *.conf names. Write
   complete candidate bytes, set the reviewed owner/group/mode, flush and fsync
   the file. Recheck the live before hash/metadata, atomically rename over the
   destination, then fsync the parent directory. Never truncate/write the active
   file in place. Preserve other files and retain exact backups.
3. Validate the effective main configuration after replacement:
   `sudo unbound-checkconf /etc/unbound/unbound.conf`.
   If it fails, restore the backup before any reload.
4. Fully restart Unbound with `sudo systemctl restart unbound.service` after
   successful validation. Require healthy running state, loopback listener and
   direct resolver answers within the reviewed convergence window. Capture status
   and bounded cursor-scoped journal output. Do not substitute a reload.
5. Fully restart Pi-hole DNS on that same node after healthy Unbound is established.
   Use `sudo pihole restartdns` on the installed v5 nodes; verify the equivalent
   full restart for other versions. Both restarts are mandatory for apply and
   rollback under [repository policy](../../AGENTS.md#unbound-local-zone-changes).
6. Verify healthy Unbound/Pi-hole/Keepalived on both nodes and coherent VIP ownership,
   loopback-only Unbound listeners and baseline DNS health. Query all four records
   directly through that node's IPv4 and IPv6 Pi-hole endpoints. Also query its
   loopback Unbound port 5335 to distinguish resolver data from Pi-hole cache.
   Check unrelated existing local records and public resolution against baseline.
7. Proceed to the second node only after the first node's complete gate passes.
   Recheck roles and peer readiness. Until both nodes are updated, VIP answers
   for new records must match the currently serving node's accepted deployment
   state; pre-existing DNS must remain available throughout the bounded window.
   Then run all 24 consumer queries through both node addresses and both VIPs.
   Confirm exact records and no unexpected aliases or extra addresses.

Pi-hole or client negative caches may retain the earlier NXDOMAIN. Record the
negative TTL and the deadline before retrying after expiry. A correct direct
Unbound answer does not waive the Pi-hole/VIP checks. Do not globally flush caches,
extend the window indefinitely without a reviewed scope. Both mandatory full service
restarts must be included in the reviewed scope; an Unbound reload or Pi-hole
cache-only/list-only reload does not satisfy the restart requirement.
If the bounded window cannot accommodate expiry, record incomplete validation
and follow the agreed rollback/hold decision rather than declaring success.

Finish with FQDN SSH in both address families and matching authenticated host
identity under the Nautobot review. Preserve strict host-key checking; a temporary
explicit alias to the independently trusted target identity is acceptable, while
changing DNS resolution via hosts files is not a DNS acceptance test.

## Rollback and stop conditions

Any failed restart, service degradation, wrong answer, unconverged VIP ownership,
unrelated DNS regression or changed input stops progression. Roll back already
changed nodes in reverse order using their own exact backups. If only the first
node changed, restore only that node. Do not modify a still-untouched peer.

Before restoring, verify backup hash and destination identity; stop for manual
review if another writer changed the destination since this operation. Restore
original bytes/owner/group/mode atomically, validate the full configuration, then
fully restart Unbound, establish its health, then fully restart Pi-hole DNS on
that node. Accept coherent cluster-driven failover under the same HA gate.
Verify original file hash, active services,
VIP ownership and pre-change DNS answers. Retain evidence of both failure and
rollback; rollback commands returning zero are not sufficient proof.

Restoring the original file can remove the newly added host records. Cached
positive answers may persist until TTL expiry, so record both direct resolver
state and eventual Pi-hole/VIP state. If SSH is lost, a backup is unavailable or
rollback cannot be verified, report manual intervention and leave remaining
nodes untouched. Keep backups until terminal review; cleanup is separately scoped.

## Validation references

- [Local-zone guide](Pi-hole-with-Unbound-local-zone-guide.md)
- [HA configuration](scenario-1-ha-configuration.md)
- [Upstream configuration validation](https://unbound.docs.nlnetlabs.nl/en/latest/getting-started/configuration.html)

Preserve private evidence, publish only sanitized decisions, and update the
consumer roadmap with observed results. Do not equate DNS deployment with stage-4
acceptance, application deployment, Caddy publication or Restic readiness.

## Prepared execution helpers

The current repository helpers implement the new atomic-write/two-full-restart
policy and paired HA gate. [Qualification](zone-transaction-qualification.md)
passed 29 offline contracts and four native fixture scenarios, including actual
Unbound/systemd apply, restart failures and reverse recovery. FTL and Keepalived
are fixture stand-ins; live acceptance remains required. Historical frozen
bundles and their recorded outcomes are unchanged.

New operations select `atomic-zone-full-restart-v2` and use a fresh paired gate,
one-use mutation receipts, bound original/candidate DNS expectations, durable
backups and reverse-order recovery. Current CLI and required inputs are defined
in the qualification document. Historical invocation examples below do not
specify the successor's authorization or new inputs.

The reviewed bundle contains copies of `scripts/apply-host-records.py` as
`node.py`, `scripts/dispatch-host-records.py` as `dispatch.py`, and
`scripts/verify-host-records.py` as `verify.py`. It also binds the exact candidate,
per-node metadata/configuration/binary hashes, expanded native-validation
inputs and an ordered execution/rollback procedure. The dispatcher verifies the
approved SHA-256 index before SSH; it operates on one node only. The operator
must pass every DNS/service gate before advancing, and restore previously changed
nodes if a later gate fails. Node helper success alone is not acceptance.

The September 21 readiness bundle and private review are under
`/home/aaron/code/.local-evidence/nautobot-dns-readiness-20260921/`.
The initial readiness phase made no live changes. The frozen bundle includes the owner procedure as
reviewed at assembly; future edits require rebuilding its index and authorization.

Run offline helper tests with `python3 Unbound/tests/test_host_records.py`.
They cover replacement failure, metadata, symlink/drift rejection and the
authorization hash gate; they do not simulate live HA, reload or DNS recovery.

## Initial execution disposition (historical)

The approved September 21 attempt changed the secondary, then automatically
restored its exact original file after the immediate post-reload service gate
failed. Independent verification confirmed rollback and healthy services, with
unchanged primary/VIP ownership. All 24 host DNS queries remain NXDOMAIN.
Private result: `/home/aaron/code/.local-evidence/nautobot-dns-readiness-20260921/EXECUTION_RESULT.md`.

Do not retry the executed bundle. Before proposing another execution, retain
service names/states in evidence, qualify a bounded reload-settlement gate and
rollback failure handling, then prepare a fresh reviewed bundle/backup namespace.
The transient state was not captured; a reload transition is a hypothesis, not
a proven root cause. Keep the original bundle and rollback backup intact.

## Retry preparation after verified rollback

The reusable helper now records each service's ID, ActiveState, SubState, PID,
Result and command status. Preflight still requires immediate healthy running
services. After apply or rollback reload, only Unbound's `reloading` state may
settle for at most 30 seconds. Two active/running samples one second apart are
required, with valid PIDs and successful unit results. Other inactive, failed,
activating or deactivating states, peer-service faults and changed VIP ownership
stop immediately. Command timeouts share the settlement deadline.

The same gate verifies automatic and explicit rollback. Original apply errors
and recovery errors are retained separately; restoring file bytes without healthy
services is not successful rollback. The journal cursor is parsed from the exact
`-- cursor:` line, excluding banners. The controller timeout is 300 seconds to
allow bounded preflight plus both settlement paths; a timeout still leaves the
remote outcome unknown and prohibits automatic retry.

Fourteen offline tests include the real transaction path with mocked commands,
transition/flapping/timeout cases, hard failures, successful recovery and failed
recovery. They are wired into `Unbound/tests/run.sh`. No test contacts a node or
proves live reload/HA acceptance. These tests preceded the live retry recorded below.

The new bundle uses a fresh node-local backup directory ending in `-retry1`.
The executed bundle and its original backup remain immutable historical evidence.
Readiness observations are retained evidence, not a new live refresh; exact hashes,
configuration/include identity, service health and VIP ownership must pass again
at execution. The retry received exact-bundle authorization and executed as recorded below.

## Verified retry result — September 21, 2026

The authorized retry deployed the four records secondary-first, then primary.
Both Unbound reloads recorded `reloading` followed by two healthy running samples.
Exact candidate hashes, root:root mode 0644, native configuration checks,
loopback-only port 5335 and node-local original backups were verified.

Pi-hole retained NXDOMAIN for both PTR records although direct Unbound queries
were correct. On the secondary, the observed negative TTL exceeded 10,000 seconds.
The user separately authorized `sudo pihole restartdns` on each node, expanding
the frozen bundle's no-Pi-hole-restart scope without modifying that bundle.
Secondary restart and all eight node checks completed before primary deployment.
Primary restart was separately approved after the same PTR failure appeared.
Each restart cleared the observed PTR failures; no forwarding change was needed.
This supports retained cache state as the explanation, rather than proving that
all future record changes require a full restart.

All 24 A/AAAA/PTR checks passed through both nodes and both DNS VIPs. Existing
local/public controls passed over both address families. FQDN SSH over IPv4 and
IPv6 authenticated the expected host and unchanged boot identity. Unbound,
Pi-hole and Keepalived were active; primary retained both DNS VIPs in readbacks.
No new Unbound unit/identifier journal entries were returned within the reviewed
cursor window. These samples do not claim uninterrupted service during restart.

Exact rollback backups remain in `/var/backups/nautobot-host-dns-20260921-retry1`
on both nodes; the earlier secondary backup is also retained. Future rollback
must account for positive Pi-hole/client caches and separately scope cache action.
Do not replay the consumed bundle. Terminal Git publication is recorded in [Unbound history](../HISTORY.md).
Remote backup cleanup has not been performed.
Nautobot stage-4 acceptance remains a separate review.

Private result and evidence index:
`/home/aaron/code/.local-evidence/nautobot-dns-readiness-20260921/RETRY_EXECUTION_RESULT.md`.
For future deployments, include the mandatory Pi-hole DNS restart and bounded
settlement/validation window before authorization. The existing generic helper
only applies/reloads Unbound; its caller must explicitly execute the required
restart and service/role/DNS gates. The helper alone is not a complete deployment.

For the NTP-only October 20 execution review, the operator requests no additional
fixtures, stand-ins or simulated failover testing. Use the retained qualification,
real sealed-input validation and brief live checks in the approved change.
The exact pending archive is listed in the
[NTP prerequisite review](ntp1-ipv6-prerequisite-review.md#sealed-deployment-ready-for-approval).
