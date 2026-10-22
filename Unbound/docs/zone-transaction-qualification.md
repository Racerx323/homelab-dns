# Atomic local-zone deployment and recovery qualification

October 20, 2026. Repository implementation and isolated qualification only;
no production target contact, DNS write or service restart is authorized here.
The transaction baseline passed 29 offline cases and four native fixture scenarios;
subsequent read-only linked-service acceptance is described below.

## Production transaction

The [node payload](../scripts/apply-host-records.py),
[one-use dispatcher](../scripts/dispatch-host-records.py) and
[paired acceptance gate](../scripts/verify-host-records.py) implement the owner's
[atomic-write and two-restart contract](host-record-deployment.md#current-local-zone-update-contract).
The new operation must select policy `atomic-zone-full-restart-v2`. Historical
manifests are rejected; historical frozen execution bundles remain unchanged.

The node payload verifies root/hostname/boot, bound input/configuration hashes,
include membership, native staged validation and destination metadata. It keeps
an exclusive mutation lock, exact fsynced private backup, bound metadata and a
journal cursor. Durable phases record prepared, write intent, installed, apply
completion requiring paired acceptance, restoration intent and restoration
completion requiring paired acceptance. No local completion accepts the cluster.

Replacement uses a temporary file in the destination directory whose name is
outside the `*.conf` include. It writes complete candidate bytes, sets metadata,
fsyncs the file, rechecks the destination hash/metadata, atomically renames and
fsyncs the directory. Existing open readers retain the original inode. The final
check does not lock out an unrelated root administrator; unexplained destination
drift still stops apply/recovery. No Unbound zone synchronization is assumed.

After validating the installed effective configuration, fully restart Unbound,
check its running state and the frozen exact direct resolver answers over both
loopback families, then invoke plain `pihole restartdns`. Require local service
convergence and preserve output. Apply failure attempts atomic restoration from
the exact backup, validation and both full restarts using the original DNS
expectations. Restoration failure, foreign file/metadata drift or unavailable
backup remains a recovery hold; an error is never reported as acceptance.

An interrupted worker can retain write intent or installed state. Its receipt
cannot replay. Preserve state and establish the worker's terminal status under
reviewed read-only scope before an explicit restoration attempt. Lock contention
prevents concurrent restoration from writing over a still-running worker. SSH
loss or timeout is an unknown remote outcome, not evidence of rollback. Cleanup
of retained files, locks or staging is not automatic.

## Cluster and approval gates

The dispatcher checks the exact input index, policy and expiry, then requires a
fresh paired gate before each apply: baseline before the non-VIP node, accepted
first-node deployment before its peer. A one-use node/phase receipt is persisted
before pinned-key SSH. No peer advances automatically. A failed or interrupted
attempt consumes its receipt; do not blindly retry it.

The paired gate independently reads both authenticated host/boot/file states,
local service health and the frozen original/candidate DNS expectations. It
requires both VIPs on one healthy node, no duplicate or split ownership, and two
consecutive coherent samples within its convergence window. Owner movement is
allowed. VIP answers follow the serving node's accepted file state during the
mixed-version interval; after both nodes are updated all paths require the new
records. Persistent missing VIPs, bad DNS or peer faults fail the gate.

Rollback is serial and reverse ordered. The `rollback-secondary` gate means
primary has been restored and secondary remains candidate; `rollback-all` means
both original states. Both node and VIP DNS answers must pass; do not restore an
untouched peer. Caller reviews the exact current state before each rollback.
The gate's exclusive phase receipt prevents its earlier successful result from
being silently overwritten by a replay. Mutation guards expire after 120 seconds.

Every new execution review must bind current node identities, trusted keys,
per-node before metadata/include hashes, exact candidate and expanded native
validation inputs, before/candidate direct and node DNS checks, unrelated DNS
baselines, VIP checks, backup paths, operation expiry and ordered recovery. For
NTP1 render only the two reviewed AAAA/PTR additions against each live fragment;
exclude pending Munin/svmf changes. This successor uses one common candidate:
both retained live fragments match. If new before fragments differ, stop rather
than overwrite unrelated node data with that common candidate. Preserve current
Caddy/Keepalived configuration.

## Qualification and practical limits

The [offline tests](../tests/test_host_records.py) cover atomic replacement and
file/directory fsync, retained reader behavior, last-moment drift, corrupt backups,
symlink rejection, lock contention, restart order, bad direct answers, explicit
recovery, worker interruption, failed recovery, service deadlines, coherent owner
movement, split/duplicate/missing VIP rejection, expired/missing gates, identity
mismatch, authorization hashes and receipt consumption. The retained 29 baseline cases passed.
They run in the repository suite, pre-commit and the validation workflow.

The [native harness](../tests/qualify-zone-transaction.py) runs the actual node
payload and paired gate in two Podman containers with `--network=none`, native
Bookworm Unbound/systemd, IPv4/IPv6 DNS queries, real atomic writes and durable
backups. It tests two-node apply, coherent fixture VIP relocation, reverse-order
rollback, one-shot Unbound restart failure, one-shot Pi-hole restart failure and
foreign-drift preservation. DNS expectations include original missing records,
new records and their restoration through both families. Native r1 passed four
scenarios; r2 passed all four again after the final deadline/drift changes. Nine
retained apply/recovery readbacks confirm both service PIDs changed. Native
versions were Unbound 1.17.1-2+deb12u4, systemd 252.39-1~deb12u2 and dnsmasq
2.90-4~deb12u2, on amd64.

Pi-hole's service boundary is a dnsmasq process behind a test command accepting
only `restartdns`; Keepalived's service identity is a sleep sentinel. The harness
moves fixture VIPs explicitly. This qualifies transaction/control and acceptance
logic, not actual VRRP, physical failover, production ARM64, the installed FTL
binary or its complete hooks. Podman exec supplies the native test transport;
pinned SSH, hash/identity and one-use behavior have offline contract coverage.
Real target services, DNS availability and failover still require acceptance in
the separately approved deployment. Do not claim zero DNS packet loss from
bounded post-change checks or from these fixtures.

Private evidence is under workspace
`.local-evidence/homelab-dns/current/ntp1-transaction-qualification-20261020-v1/`.
It retains original source, input revisions, image build/version metadata,
command manifests, full output/status, offline logs and both native revisions.
The fixture image uses the retained local Bookworm validation base; this is not
a fresh-image reproducibility claim. Successful fixtures remove only their own
named containers after saving evidence; failed fixtures are retained.

Run offline checks with `python3 -I -B Unbound/tests/test_host_records.py`.
Native qualification requires the local fixture image described in
[the Containerfile](../tests/Containerfile.zone-transaction), rootless Podman
runtime access and a new private evidence directory. Run Podman and this harness
outside the filesystem sandbox. Keep output in a private log from launch and
retain the resulting directory; recover existing logs rather than rerunning an
unchanged case to retrieve output.

## Next execution handoff

Prepare the NTP-only sealed deployment review from accepted retained baselines
and the qualified source revision. Bind the exact two-record delta, current
identities/keys, before/candidate checks, staged validation, non-VIP-first actions,
HA convergence, reverse recovery and expiry. Recheck live inputs in its approved
preflight and stop on drift. Do not contact production or execute a mutation
until the new bundle's exact hash is approved. No production bundle was sealed
or executed during this qualification.

## Sealing update and operator testing constraint

The operator requires no further fixtures, stand-ins or simulated failover tests.
The execution bundle retains the transaction baseline qualification; later source
adds only brief read-only acceptance of the four linked DNS/Proxy VIPs, Caddy
service/verified-TLS HTTPS 204 and public DNS health, plus an archive/phase wrapper.
Those additions were checked by syntax, source review and the actual sealed
archive/index verification, without building more fixtures or contacting targets.
The previous native result is not claimed as byte-identical native qualification
of these additions. Live checks are part of ordinary deployment acceptance,
not a separate extended failover exercise or a prerequisite fixture stage.

PIHOLE_DUALSTACK moves DNS .55/::55 and Proxy .56/::56 together. Caddy ownership
moves with DNS, while its configuration and sync remain unchanged. The sealed
NTP-only deployment review is recorded in the
[prerequisite review](ntp1-ipv6-prerequisite-review.md#sealed-deployment-ready-for-approval).
No production phase has run; exact archive-hash approval is the next step.
