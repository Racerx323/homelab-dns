# NTP1 native IPv6 DNS prerequisite review

Repository candidate and readiness scope, prepared October 20, 2026.
No DNS-node contact, deployment, reload or restart is authorized by this document.
The owning source is [pihole-local-zone.conf](../configs/pihole-local-zone.conf).

## Deployment accepted — October 21, 2026

Approved archive SHA-256
`54224a0beac93bc715a8af42ce39b673a7b14f18ac300e1524f714364f03d545`
executed all five serial phases successfully, completing at 09:34:47 CDT.
.54 was atomically updated and accepted before .53. Both nodes fully restarted
Unbound and Pi-hole DNS; retained PID readbacks confirm both restarts per node.
Final local-zone SHA-256 on both nodes is
`cd69e1d0674ed844c4768c355db319d521dd53805df2da38f25ef9cb819480ef`.

Exact NTP A/AAAA/IPv4-PTR/IPv6-PTR and the preserved local A passed through
both physical node families, loopback Unbound and DNS VIPs. Public resolution
health passed. Both Caddy services were healthy and verified-TLS HTTPS returned
204 through each proxy VIP family. All retained paired samples show the complete
four-VIP group on .53; no statement about intervening failover or packet loss is
inferred. No forced movement, Caddy/Keepalived config change or sync action occurred.

No rollback was needed. Private outcome.md/outcome.json, logs, consumed receipts
and target backups remain in the approved operation's evidence directory and
`/var/lib/ntp1-dns-deployment-20261020-v1` on both nodes. Do not replay completed
phases or clean up retained state implicitly. No new fixture or notification test
was performed. Original archive/review inputs are immutable.

The NTP DNS prerequisite for the svmf network successor is accepted. Next prepare
the successor network review with refreshed baseline requirements; named ntp1
IPv4/native-IPv6 checks on svmf belong to its approved preflight. Munin/svmf DNS,
SRV/primary work and overall NTP production acceptance remain separate.

## Current deployment decision — operator clarification

October 20, 2026: Unbound local-zone synchronization is not implemented. Caddy
replication is separate. Update each node independently with an atomic local-zone
replacement, validate, fully restart Unbound, establish its health, then fully
restart Pi-hole DNS. Both restarts apply after rollback restoration as well.
Reload-path and broad synchronization qualification are superseded as gates for
this record change. Captured Gravity Sync source/timer observations remain
historical Pi-hole observations; they do not establish a zone-propagation writer.
No synchronization job is paused or changed by this operation.

Use the current non-VIP owner first while its peer is healthy and serving.
Cluster-driven failover during restart is permitted within a reviewed convergence
window. Require coherent ownership of both VIPs by one healthy node and correct
answers from both physical nodes before peer progression. Persistent split,
duplicate or lost VIP ownership and baseline DNS loss stop progression. Do not
force failover or modify Keepalived/Caddy under this record update.

The [production transaction qualification](zone-transaction-qualification.md)
passed 29 offline cases and four native fixture scenarios on the final source
revision. Atomic replacement now fsyncs both file and directory with a final
hash/metadata guard; apply and rollback perform both full restarts. Durable state,
one-use dispatch and paired coherent-HA gates replace the old pinned-owner
behavior. Native FTL and Keepalived remain stand-ins; target acceptance is still
mandatory. Historical frozen bundles remain unchanged.

## Sealed deployment ready for approval

The private execution review is prepared under workspace `.local-evidence/`:
`homelab-dns/current/ntp1-dns-deployment-20261020-v1`.
Archive SHA-256:
`54224a0beac93bc715a8af42ce39b673a7b14f18ac300e1524f714364f03d545`.
The directory contains review.md, sealing.json, frozen runner/payloads, exact
before/candidate bytes, native-expanded inputs, pinned keys and provenance.
Local archive/closed-member/index/input checks passed without target contact.
This exact archive was subsequently approved and executed successfully; see the
accepted outcome above. Its execution phases are consumed.

The operator confirms Keepalived couples DNS and Caddy: PIHOLE_DUALSTACK moves
DNS 10.1.0.55/::55 and Proxy 10.1.0.56/::56 together. The retained October 20
address captures show all four on .53 and none on .54. Brief acceptance checks
require all four on one healthy node, Caddy active and verified HTTPS 204 from
proxy.local.theama.co/ over both literal proxy VIPs, plus exact DNS answers.
No Caddy configuration/restart, sync changes or forced failover are included.
The operator prohibits further fixtures/stand-ins/simulated failover tests;
prior qualification is retained and no additional fixture stage blocks execution.

## Reason and exact candidate

The NTP architecture identifies `ntp1.local.theama.co` as the service name for
the rebuilt `j2-svntp1` at 10.1.0.51 and fd36:5aa8:6971:1::51. The operator
confirms ntp2 does not exist. The svmf static-network sealer incorrectly used
ntp2, which must be corrected without creating a fictitious DNS dependency.

The approved svmf resolver diagnostic, archive SHA-256
`12b1bb0a770ab96b541049550b7fe7feaaa8c121713c053cdf6aa2bd9ce34b0a`,
queried ntp1 through both DNS VIPs on October 20, 2026. A returned 10.1.0.51;
AAAA returned NOERROR with zero answers. Named getent ahostsv6 exited 0 but
returned only mapped IPv4 ::ffff:10.1.0.51. This does not prove native IPv6
resolution. The capture sampled serving VIPs, not each physical DNS node or its
installed configuration. All diagnostic receipts are consumed.

| Record | Name/address | Expected value | Candidate action |
| --- | --- | --- | --- |
| A | `ntp1.local.theama.co.` | `10.1.0.51` | Preserve |
| AAAA | `ntp1.local.theama.co.` | `fd36:5aa8:6971:1::51` | Add if absent |
| IPv4 PTR | `10.1.0.51` | `ntp1.local.theama.co.` | Preserve |
| IPv6 PTR | `fd36:5aa8:6971:1::51` | `ntp1.local.theama.co.` | Add if absent |

Use one canonical PTR. Do not add ntp2, rename the physical host or publish a
second PTR for j2-svntp1. Do not change the primary ntp service at .50.
The two reviewed source additions were deployed and accepted on both nodes on
October 21, 2026; the preserved IPv4 records remain accepted as well.

## Read-only readiness scope to seal separately

Prepare an exact-hash inspection bundle before target contact. Pin existing
SSH keys/aliases for the two DNS nodes and, separately, the NTP node. Target
names, literal addresses, account and current identity must be established from
their owners' records; a previous hostname or HA preference is not a live-role
proof. The expected DNS-node addresses are .53/.54 and their ::53/::54 ULAs;
resolve any ownership or identity drift before issuing a bundle.

On the NTP node, verify the permanent ::51 address, absence of tentative/DAD
failure, intended routes, and authenticated IPv4/IPv6 identity. Preserve its
running time service; no restart, interface activation, NTP configuration change,
address assignment or test notification. Publication readiness must establish
that the intended ULA is assigned; an architecture entry alone is insufficient.

On each DNS node, inspect the current local-zone fragment hash/owner/group/mode,
effective include graph and selected conflicting forward/reverse records, installed
Unbound/Pi-hole versions and validation/reload paths, supported full Pi-hole DNS
restart command, configuration synchronization writers, service health and actual
ownership of both DNS VIPs. Exclude credentials, control private keys and unrelated
raw configuration archives. Capture current A/AAAA and IPv4/IPv6 PTR answers
through both node transports, VIPs and node-local Unbound port 5335; keep response
codes/answer sets distinct from tool exit codes. Determine negative-cache bounds.
No reload, restart, cache flush, synchronization change or VIP movement belongs
to this read-only inspection.

If records are already identical, reconcile instead of duplicate insertion.
Conflicting records, mixed VIP ownership, a synchronization writer defeating
serial changes, unrelated destination drift or unavailable validation hold the
deployment review. Never overwrite those findings with the repository candidate.

## Separate deployment and rollback contract

Use the [host-record procedure](host-record-deployment.md) only after readiness,
with a new exact execution bundle. Pin each node's current fragment and render a
node-specific candidate containing only the two reviewed NTP additions. Require
the exact two-line semantic delta while preserving every unrelated live record.
The repository source also contains pending Munin/svmf additions; copying that
whole file would broaden scope and is forbidden for this NTP-only stage.

Bind native staged validation, exact private backups and metadata, atomic
replacement, Unbound validation/full restart and a full Pi-hole DNS restart on that same
node. [Repository policy](../../AGENTS.md#unbound-local-zone-changes) requires
both full restarts after every deployed local-zone change and rollback restoration.
Verify the installed version's command; the historical v5 command is
`sudo pihole restartdns`. Do not infer current compatibility.

Change the actual non-VIP owner first. Accept its exact forward/reverse results,
healthy Unbound/Pi-hole/Keepalived, coherent VIP ownership and unrelated local
and public resolution before changing the peer. Require final node/VIP answers
over both transports, correct native ULA and canonical PTR, then repeat svmf's
named getent checks with native-family/expected-address validation. AAAA over an
IPv4 DNS transport and A over IPv6 transport do not prove the application family.
Successful native FQDN SSH and the separate network-wrapper gates remain required.

On failure, stop progression and restore only changed nodes in reverse order
from exact private backups. Validate, fully restart Unbound, establish its health,
fully restart Pi-hole DNS and
verify original answers, health and VIP ownership. Stop rather than overwrite
foreign file drift; retain a recovery hold if restoration cannot be proved.
No package upgrade, network mutation, Caddy change or notification send is included.

## Ordering and acceptance status

This NTP DNS prerequisite precedes the corrected svmf network successor. It
does not depend on assigning svmf's ::83. The separate
[Munin/svmf DNS review](munin-host-record-review.md) remains held on accepted
svmf static networking and must not be bundled with these NTP additions.
The consumer's [readiness checklist](../../../homelab-ntp/ntpsec/docs/PRODUCTION-READINESS.md)
owns the next gate. Native validation and address readiness are recorded below;
DNS deployment acceptance subsequently passed as recorded above.

## Sealed read-only inspection reviews

Prepared October 20, 2026 without target contact. The repository runner
`Unbound/scripts/inspect-ntp-dns-readiness.py` freezes its source/tests, explicit
NTP bounded-transport helper, established key, candidate provenance and exact
specification/review in each archive. Seventeen offline contracts passed. Private
review directories are listed below relative to the workspace evidence root:

- `homelab-ntp/current/ntp1-address-readiness-20261020-v1`: `bd139b4d64ace97d4c73cb0e1f509e76d5d7c3c3d0a15081b2b9a8e6f95ec24e`.
- `homelab-dns/current/ntp1-dns53-readiness-20261020-v1`: `b4ee8a69eb5879dd3fe1de84956b52fea25e36fdd87dfab32cfdef9e1cf51ce6`.
- `homelab-dns/current/ntp1-dns54-readiness-20261020-v1`: `53420d803c3b48a518a1e8f02c0d224a5434a124ab046b0e87167bc95e4cbdd2`.

Each directory contains `review.md`, `sealing.json` and the frozen execution
inputs. Approve each exact archive hash before invoking its `runner.py execute`
command. NTP has two explicit planned literal-family sessions; each DNS archive
has one IPv4 SSH capture to its node only. Both DNS nodes' IPv4/IPv6 DNS paths
are sampled from their respective captures. No peer progression, key discovery,
automatic retry, target staging or persistent mutation is included.

The DNS identity names are retained September 21 observations, not a current
role assumption; host/key mismatch stops capture. The NTP key alias 10.1.0.137
is retained established key identity from its accepted monitoring archive; the
actual destinations are the reviewed .51 and ::51 literals. No DNS dependency
or new trust-on-first-use is introduced. The checker validates only the two NTP
additions rendered from the live fragment, excluding pending Munin/svmf changes.
Writer/restart projections deliberately preserve unproven semantics as findings.
Readiness capture completion alone cannot accept a deployment.

## Executed readiness and remaining qualification — October 20, 2026

All three exact approved archives executed once with complete captures, controller
exit 0 and no target mutation. The receipts are consumed; do not replay them.
Private `outcome.md`/`outcome.json` files reside in the directories listed above.
NTP authenticated .51/::51 SSH, fixed saved ULA, DAD flags, route sources and
unchanged boot/time-service identity passed address publication readiness.
This does not establish overall host production acceptance.

Both nodes' Unbound 1.17.1 validated the original effective configuration and
the in-memory candidate containing exactly the two missing NTP records.
The live local-zone fragments matched; unrelated Munin/svmf additions were excluded.
Both DNS VIPs stayed on .53; .54 owned neither. Each node completed 24 queries
across node, loopback and VIP endpoints over both transports: exact A/IPv4 PTR,
NOERROR/zero-answer AAAA and NXDOMAIN/zero-answer IPv6 PTR. Neither record was
installed. Stable service/configuration identities passed.

The [local-zone guide](Pi-hole-with-Unbound-local-zone-guide.md) requires Unbound
reload followed by a full Pi-hole DNS restart after deployment and rollback.
This is the intended procedure, not evidence that the installed control paths
are qualified. The ExecReload projection did not establish the actual reload
path. Core Git tag v5.18.3 and restartdns tokens do not establish the full restart
implementation or other component versions.

Next prepare a narrowly scoped read-only qualification of the installed reload
and full-restart implementation, plus configuration synchronization and serial
change isolation. Gravity Sync timers are active on both nodes; protected-file
reads of its configuration and Pi-hole versions were unavailable under the
capture policy, not proof those files are absent. Inspect safe metadata and
selected non-secret fields without broadening into credentials. Active Caddy
lsyncd projections do not prove complete writer coverage. Establish writer
paths, synchronization direction/exclusions and a safe serial deployment contract
before sealing deployment. No reload, restart, writer change or failover is
permitted by the completed readiness approvals or by the guide reference.

## Reload/restart and synchronization qualification sealed

Prepared October 20, 2026 without target contact. The same repository runner now
has a separately bound DNS-only qualification scope. Twenty-three offline tests
passed, including source redaction, safe configuration projection, pinned boot
identity, immutable scope, one-use transport and service-drift rejection.
Prior executed archives remain immutable and cannot replay.

Separate private review directories, relative to workspace `.local-evidence/`:

| Node | Directory | Archive SHA-256 |
| --- | --- | --- |
| .53 | `homelab-dns/current/ntp1-dns53-controls-qualification-20261020-v1` | `6a93995c22fa7ce05ba29b1fb8727211fdedc270008809c0ccec34eab2fbe397` |
| .54 | `homelab-dns/current/ntp1-dns54-controls-qualification-20261020-v1` | `7faeb091e55bd1c60bdce3f420739df350dcf4f36a7cc63c4b0488a159fe1199` |

Each binds the prior authenticated hostname/boot and established Ed25519 key,
one IPv4 SSH capture, frozen source/helper/tests and a 24-hour expiry. No NTP or
DNS-peer progression. Read service identities, VIP ownership, effective include
hashes, selected control settings, unit sources and approved Pi-hole/Gravity Sync
shell sources. Inspect fixed synchronization configs and bounded scheduler paths
through non-secret field/path/feature projections. Root/pi-owned files are
accepted only with protected ancestry; the two launcher links may resolve only
into approved code roots. Unsupported storage remains a finding.

Review source to trace Unbound reload, full Pi-hole restart, synchronization
push/pull/defaults/exclusions and local-zone ownership. Configs, cron commands
and credentials are never exported in full. Redacted/dynamic dependencies,
unavailable files and unknown writers remain deployment holds; source inspection
does not exercise runtime behavior or prove comprehensive writer isolation.
No reload/restart/control request, native validation, DNS query, sync invocation,
writer pause, configuration write, failover or notification is included.

The v1 reviews above were subsequently approved and executed; see the outcome
and corrected successor below. Review both complete successor outcomes together. Only after closing the control/writer gaps may a separate
serial HA DNS deployment be sealed. Retain full Pi-hole restarts for both apply
and rollback as required by the guide and repository policy.

## Control qualification v1 incomplete; corrected v2 sealed

Both approved v1 archives executed once on October 20, 2026. Authenticated SSH
and pinned hostname/boot checks passed on each node. SSH exit was 0; controller
exit was 2 because capture remained incomplete. No target mutation occurred.
Both receipts are consumed; their frozen inputs and partial evidence remain private.

The first binary read, `/usr/sbin/unbound-control`, failed the protected regular
file predicate before unit/source/synchronization collection. That predicate
combines regular-file type, root ownership, mode and one-MiB size constraints;
the specific failed condition was not exported. Do not infer absence, a bad
binary or an oversized file. Both partial captures observed control-enable yes
and control-interface /run/unbound.ctl, with the prior local-zone hash unchanged.
Neither reached final service/VIP/source stability checks or qualified controls.

Corrected the repository runner to preserve an unavailable binary hash as a
finding, capture lstat-only type/owner/mode/size without following links, and
continue independent reads. File protections and read bounds remain unchanged;
this does not accept the binary or waive unresolved control-path evidence.
Expanded offline regression coverage exercises this exact rejection and verifies
continued unit/source collection and final checks. All 23 tests passed.

Separately sealed v2 directories under workspace `.local-evidence/`:

| Node | Directory | Archive SHA-256 |
| --- | --- | --- |
| .53 | `homelab-dns/current/ntp1-dns53-controls-qualification-20261020-v2` | `13cd0b42f2c0b4b95c4e72c2108597f20869dd7c766925e368989c81216cc212` |
| .54 | `homelab-dns/current/ntp1-dns54-controls-qualification-20261020-v2` | `1e170dbf53b546eb7efd02f2a2f656c6cb1167a224b0993047509fe170850268` |

Preparation made no additional contact. New source/review hashes require new
exact-hash execution approvals; v1 approval cannot replay or authorize v2.
Next execute each approved successor once, reconcile both complete outcomes and
resolve remaining control/writer gaps before sealing any DNS deployment.

## Control qualification v2 executed — remaining isolation gate

Both v2 archives above were approved and executed once on October 20, 2026.
Controller and SSH exits were 0; complete captures performed no target mutation.
Host/boot, Unbound/Pi-hole/Keepalived identities and VIP ownership stayed stable:
.53 retained both VIPs; .54 owned neither. Successfully captured files/include
graphs and sanitized unit-source projections remained stable; redacted unit lines
are not complete byte-level source proof. Private outcomes/source reviews are
retained beside each executed archive. Both receipts are consumed.

The lstat diagnostic now explains v1's rejected binary read: unbound-control is
a regular root:root 0755 file of 1,487,016 bytes, above the one-MiB read bound.
Its hash remains unavailable; neither corruption nor executable failure is proved.

Captured Pi-hole source establishes that plain restartdns dispatches the default
full service restart. Its reload and reload-lists arguments select cache/list
signals and do not satisfy full-restart policy. The Unbound unit's ExecReload
sends HUP; remote control is enabled on /run/unbound.ctl. The owner's documented
unbound-control reload path remains separate and unexercised. Do not silently
substitute systemctl reload merely because the unit source was observed.

Gravity Sync's service starts the captured script without arguments, selecting
smart sync. Its default paths cover Pi-hole/DNSMASQ files and source contains
pull/push and local/remote FTL restart paths. Both timers were active/waiting,
with OnBootSec=120 and OnUnitInactiveSec=29m. These observations do not prove
recent success or a fixed one-way authority. The source imports overrideable
configuration; defaults do not establish effective deployed paths or exclusions.

Reads of gravity-sync.conf, Pi-hole versions and root/pi crontabs were rejected
by the protected-file policy. Selected lstat metadata reports regular root-owned
config files but does not identify the failed ancestor predicate. Do not infer
absence or change permissions. The actual Caddy unit is caddy-lsyncd.service;
its limited Lua projection does not establish complete source/target/exclusions.

The operator subsequently clarified that no Unbound local-zone synchronization
is implemented and requires full restarts of both Unbound and Pi-hole DNS.
The broad synchronization/reload-path follow-up proposed from these findings is
superseded by the current deployment decision at the start of this review.
Retain the completed captures and unavailable-input findings; do not replay them
or modify Caddy/Gravity Sync configuration. Next qualify atomic replacement,
both full restarts, recovery and coherent HA failover acceptance, then seal the
NTP-only deployment review. No live mutation is authorized by this document.

## Atomic transaction qualification completed

The final repository revision passed all 29 offline tests, the repository suite,
pre-commit checks and four isolated native scenarios. Source revisions, image and
package identities, every fixture command/output/status and nine paired service
PID-change readbacks are retained under private
`ntp1-transaction-qualification-20261020-v1/native-r2`. Native r1 retains the
previous revision's result. No production target was contacted; no live DNS
file, service, synchronization job, Caddy or Keepalived configuration changed.
The [qualification report](zone-transaction-qualification.md) defines exact
coverage/limits and the next sealing handoff.
