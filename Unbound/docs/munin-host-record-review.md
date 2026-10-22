# Munin and svmf dual-stack DNS review

Deployment accepted October 21, 2026 at 10:12:30 CDT. All five execution phases
passed once; the exact-hash authorization is consumed.
The source is [pihole-local-zone.conf](../configs/pihole-local-zone.conf).

| Record | Name/address | Expected value |
| --- | --- | --- |
| A, unchanged | `munin.local.theama.co.` | `10.1.3.83` |
| A, unchanged | `svmf.local.theama.co.` | `10.1.3.83` |
| AAAA, added | `munin.local.theama.co.` | `fd36:5aa8:6971:1::83` |
| AAAA, added | `svmf.local.theama.co.` | `fd36:5aa8:6971:1::83` |
| IPv4 PTR, unchanged | `10.1.3.83` | `svmf.local.theama.co.` |
| IPv6 PTR, added | `fd36:5aa8:6971:1::83` | `svmf.local.theama.co.` |

Use one canonical PTR for this shared address, matching existing reverse-DNS
policy. `munin` is an additional forward name, not a second physical host.
Other names on `10.1.3.83`, including Mailrise, are outside this record change;
their IPv6 service readiness has not been established.

## Readiness and deployment boundary

The [network-owned static host change](../../../homelab-network/Ubiquiti/svmf-static-network-review.md#current-checkpoint--october-21-2026)
committed October 21 at 09:58:00 CDT. Both intended literal SSH/verified-HTTPS
families passed; static ::83 is assigned. The accepted NTP DNS deployment at
09:34:47 CDT supplies the exact current expected before zone and preserved
non-zone baseline. This preparation made no target contact. Boot/include/CLI and
zone hashes must match at execution; drift stops before mutation. No post-write
inode/mtime is assumed. The new expanded candidate must pass installed native
validation before replacement.

The [sealed execution review](/home/aaron/code/.local-evidence/homelab-dns/current/munin-svmf-dns-deployment-20261021-v1/review.md) is bound to
[sealing.json SHA-256](/home/aaron/code/.local-evidence/homelab-dns/current/munin-svmf-dns-deployment-20261021-v1/sealing.json:1)
`81d6544c533baa2592c9e63c093f2be2f403400309ffc244fb0561840a827e30`.
All five approved phases returned 0; final paired acceptance passed at
10:12:30 CDT. The [accepted outcome](/home/aaron/code/.local-evidence/homelab-dns/current/munin-svmf-dns-deployment-20261021-v1/outcome.md)
records exact A/AAAA for both names, canonical IPv4/IPv6 PTR on both node,
loopback and DNS VIP families, preserved NTP/local and public DNS, healthy Caddy
and verified proxy HTTPS 204 on both families. .54 passed before .53 mutation;
full Unbound then Pi-hole restarts changed both PIDs on each node. The final
fragment hash is `bec77d8a9a25392b9df50ba6f9edb9c013ab163e6c56f5b1bc9dd733fa892356`. All retained paired
samples show the coherent four-VIP group on .53; no intervening-transition or
packet-loss claim is made. No rollback or forced failover occurred. Target
backups/durable state remain at /var/lib/munin-svmf-dns-deployment-20261021-v1;
receipts are consumed, with no replay or cleanup. No svmf contact or test
notification occurred. Next: reconcile node, job-success and master acceptance
reviews; client caching/FQDN SSH, graph freshness and sustained monitoring remain
open. The repository record set matches the accepted fragment in a different order.

Use the [host-record procedure](host-record-deployment.md) with a new exact bundle
for these three additions. Bind candidate bytes, target baselines, native staged
validation, serial non-VIP-owner-first ordering and per-node rollback. After
each atomic replacement and successful validation, fully restart Unbound, verify
its health, then fully restart Pi-hole DNS on that same node.
For installed v5 nodes the reviewed command is `sudo pihole restartdns`; verify
versions before reusing it. Unbound local-zone synchronization is not implemented.
Caddy replication is separate. Permit cluster-driven failover within the reviewed
window; do not force VIP moves or modify synchronization.

## Acceptance and rollback

Query both names for A and AAAA and both addresses for canonical PTR through each
node's IPv4/IPv6 Pi-hole endpoints and both DNS VIPs. Also query loopback Unbound
to distinguish authoritative data from Pi-hole cache. Require exact answer sets,
healthy Unbound/Pi-hole/Keepalived, coherent VIP ownership and unrelated local and
public resolution. The frozen checks establish exact node/VIP answers; external client
TTL/negative-cache expiry and FQDN SSH identity over both families remain later
monitoring acceptance obligations. Both literal SSH families already passed
the network stage. No svmf SSH contact is included in this DNS operation. Dashboard access has its own monitoring acceptance; DNS
answers alone cannot accept a listener or firewall.

Stop progression on any wrong answer, service regression or drift. Restore only
changed nodes in reverse order from their verified private backups, validate,
fully restart Unbound, establish its health, fully restart Pi-hole DNS, and prove
baseline answers, coherent VIP ownership and health.
Foreign destination drift or failed recovery requires a hold; leave the untouched
peer alone. No package changes, Caddy changes or notification sends are included.
