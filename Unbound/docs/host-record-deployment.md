# Host DNS record deployment

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

## Deployment readiness

Before requesting the separate live change, preserve a bounded, read-only
snapshot of both nodes' current local-zone file, file owner/group/mode and hash,
active main configuration/include graph, Unbound binary/version and effective
service/reload configuration. Capture the journal cursor and current health on
each node. Use `pi` with existing SSH credentials and strict host-key verification.
Do not collect control private keys or unrestricted configuration archives.

Confirm which node currently owns both DNS VIPs and whether configuration
synchronization watches the destination. Names and HA preference do not prove
active role. Mixed VIP ownership, automatic propagation that defeats serial
validation, or unrelated source/live differences stop readiness for review.
Do not disable synchronization or move VIPs under a record-only change.

Compare both deployed fragments with the candidate's parent version. Require
that the proposed per-node diff adds only the four reviewed records. Preserve
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
`pi@10.1.0.53`. Stop if actual roles or reviewed hashes changed.

1. Create an exclusive mode-0700 node-local backup directory. Preserve exact
   original bytes and metadata of the one destination file, and record its hash.
   Keep each node's backup distinct and outside synchronized paths. Recheck that
   the destination is the reviewed regular file, not an unexpected symlink.
2. Stage the candidate in a non-included path; verify its hash and validate the
   candidate tree. Match destination ownership/mode. Replace atomically only if
   the live file still matches its reviewed before hash. Preserve other files.
3. Validate the effective main configuration after replacement:
   `sudo unbound-checkconf /etc/unbound/unbound.conf`.
   If it fails, restore the backup before any reload.
4. Use the owner's existing `sudo unbound-control reload` path only after its
   availability has been verified in readiness. Capture status and bounded
   cursor-scoped journal output. Do not silently substitute a restart or install
   control credentials if that path is unavailable.
5. Restart Pi-hole DNS on the changed node after successful Unbound validation
   and reload. This is required for every deployed local-zone change, including
   rollback restoration, by [repository policy](../../AGENTS.md#unbound-local-zone-changes).
   On the installed v5 nodes use `sudo pihole restartdns`; verify the supported
   full DNS-service restart command for other versions. Include it explicitly in
   the reviewed deployment and rollback scope.
6. Verify active Unbound/Pi-hole/Keepalived services, unchanged VIP ownership,
   loopback-only Unbound listeners and baseline DNS health. Query all four records
   directly through that node's IPv4 and IPv6 Pi-hole endpoints. Also query its
   loopback Unbound port 5335 to distinguish resolver data from Pi-hole cache.
   Check unrelated existing local records and public resolution against baseline.
7. Proceed to the second node only after the first node's complete gate passes.
   Then run all 24 consumer queries through both node addresses and both VIPs.
   Confirm exact records and no unexpected aliases or extra addresses.

Pi-hole or client negative caches may retain the earlier NXDOMAIN. Record the
negative TTL and the deadline before retrying after expiry. A correct direct
Unbound answer does not waive the Pi-hole/VIP checks. Do not globally flush caches,
extend the window indefinitely without a reviewed scope. The mandatory Pi-hole
DNS restart must be included in the reviewed scope; an Unbound reload or
cache-only/list-only reload does not satisfy the restart requirement.
If the bounded window cannot accommodate expiry, record incomplete validation
and follow the agreed rollback/hold decision rather than declaring success.

Finish with FQDN SSH in both address families and matching authenticated host
identity under the Nautobot review. Preserve strict host-key checking; a temporary
explicit alias to the independently trusted target identity is acceptable, while
changing DNS resolution via hosts files is not a DNS acceptance test.

## Rollback and stop conditions

Any failed reload, service degradation, wrong answer, unexpected VIP movement,
unrelated DNS regression or changed input stops progression. Roll back already
changed nodes in reverse order using their own exact backups. If only the first
node changed, restore only that node. Do not modify a still-untouched peer.

Before restoring, verify backup hash and destination identity; stop for manual
review if another writer changed the destination since this operation. Restore
original bytes/owner/group/mode atomically, validate the full configuration, then
reload through the same reviewed path, then restart Pi-hole DNS on that node.
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

The reviewed bundle contains copies of `scripts/apply-host-records.py` as
`node.py`, `scripts/dispatch-host-records.py` as `dispatch.py`, and
`scripts/verify-host-records.py` as `verify.py`. It also binds the exact candidate,
per-node metadata/configuration/binary/sync hashes, expanded native-validation
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
