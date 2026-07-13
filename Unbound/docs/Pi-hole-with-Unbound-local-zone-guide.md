# Pi-hole with Unbound Local Zone Guide

This guide explains the Pi-hole settings needed for Unbound `local-zone` records to resolve correctly when clients query Pi-hole first.

The intended DNS path is:

```text
clients -> Pi-hole:53 -> Unbound:5335
```

For a high-availability setup with keepalived, clients should use the DNS VIP:

```text
clients -> keepalived VIP -> active Pi-hole -> local Unbound
```

## Assumptions

- Pi-hole listens on port `53`.
- Unbound listens locally on port `5335`.
- Each Pi-hole node runs its own local Unbound instance.
- Unbound owns the internal zone with `local-zone` and `local-data` records.
- The public-safe example zone in this guide is `home.arpa.`.

## Pi-hole Upstream DNS

On each Pi-hole node, configure Pi-hole to forward DNS queries to the local Unbound instance.

In the Pi-hole web UI:

```text
Settings -> DNS -> Upstream DNS Servers
```

Set:

```text
Custom 1 (IPv4): 127.0.0.1#5335
```

If Unbound also listens on IPv6 loopback:

```text
Custom 3 (IPv6): ::1#5335
```

Do not select public upstream DNS providers in Pi-hole if Unbound is expected to answer the internal local zone.

Avoid mixing these with the local Unbound upstream:

```text
Cloudflare
Google
Quad9
OpenDNS
```

If Pi-hole has multiple upstreams, some local-zone queries may be sent to public DNS, where the internal names will not resolve.

## HA Node Pattern

For two Pi-hole/Unbound nodes behind keepalived:

```text
VIP:     10.0.0.10
node A:  10.0.0.11
node B:  10.0.0.12
```

Configure each Pi-hole to use its own local Unbound:

```text
node A Pi-hole -> 127.0.0.1#5335
node B Pi-hole -> 127.0.0.1#5335
```

Do not point node A at node B's Unbound, or node B at node A's Unbound, unless you intentionally want cross-node DNS fallback.

For the cleanest HA behavior, keep the Unbound local-zone configuration identical on both nodes.

## Conditional Forwarding

Pi-hole conditional forwarding is usually not needed for an Unbound-owned local zone.

Do not use conditional forwarding to send `home.arpa` queries to Unbound if Pi-hole already uses Unbound as its upstream. Pi-hole will forward the query normally.

Conditional forwarding is mainly useful when reverse DNS should be sent to another LAN DNS source, such as a router or DHCP server.

## Private Reverse Lookups

If Unbound contains `local-data-ptr` records for private IP addresses, Pi-hole must be allowed to forward private reverse lookups.

In the Pi-hole web UI, check:

```text
Settings -> DNS -> Advanced DNS settings
```

If reverse lookups should be answered by Unbound, disable:

```text
Never forward reverse lookups for private IP ranges
```

If this setting remains enabled, Pi-hole may block private PTR forwarding before Unbound gets the query.

One special case: Pi-hole may answer reverse lookups for its own active address as `pi.hole.`. That does not necessarily mean Unbound PTR forwarding is broken. Test a different local PTR record before changing anything.

## Pi-hole Local DNS Records

Prefer one source of truth for internal DNS records.

Recommended:

```text
Unbound owns local-zone records.
Pi-hole owns blocking, client DNS service, and forwarding to Unbound.
```

Avoid duplicating the same hostnames in both:

```text
Pi-hole Local DNS
Unbound local-data
```

Duplicated records can make troubleshooting confusing because Pi-hole may answer some names before forwarding to Unbound.

## Required Unbound Shape

Pi-hole only needs Unbound to be reachable locally. Unbound does not need to bind to the keepalived VIP.

Example:

```conf
server:
    interface: 127.0.0.1
    interface: ::1
    port: 5335

    access-control: 127.0.0.1 allow
    access-control: ::1 allow

    private-domain: "home.arpa"
    domain-insecure: "home.arpa"

    local-zone: "home.arpa." static
    local-data: "dns-vip.home.arpa. IN A 10.0.0.10"
    local-data: "_smtp._tcp.home.arpa. 180 IN SRV 0 10 8025 mail.home.arpa."
    local-data-ptr: "10.0.0.10 dns-vip.home.arpa."
```

## Validation Commands

Run these on the active Pi-hole node.

Test Unbound directly:

```bash
dig @127.0.0.1 -p 5335 dns-vip.home.arpa A
dig @127.0.0.1 -p 5335 -x 10.0.0.10
```

Test through Pi-hole on the node:

```bash
dig @127.0.0.1 dns-vip.home.arpa A
dig @127.0.0.1 -x 10.0.0.10
```

Test through the keepalived VIP from any client:

```bash
dig @10.0.0.10 dns-vip.home.arpa A
dig @10.0.0.10 -x 10.0.0.10
```

If using SRV records:

```bash
dig @10.0.0.10 _smtp._tcp.home.arpa SRV
```

Expected signs of success:

```text
status: NOERROR
ANSWER: 1 or more
SERVER: the Pi-hole IP or VIP being tested
```

For direct Unbound local-zone answers, the response should usually include the `aa` flag.

## Failover Validation

After forcing keepalived failover to the second node, repeat:

```bash
dig @10.0.0.10 dns-vip.home.arpa A
dig @10.0.0.10 _smtp._tcp.home.arpa SRV
dig @10.0.0.10 -x 10.0.0.1
```

If the active node changes but local-zone answers stay the same, both Pi-hole/Unbound nodes are configured consistently.

## Troubleshooting

If direct Unbound works but Pi-hole does not:

- Confirm Pi-hole upstream is `127.0.0.1#5335`.
- Remove public upstream providers from Pi-hole.
- Check Pi-hole Local DNS records for conflicting names.
- Check whether private reverse lookup forwarding is disabled.
- Restart Pi-hole DNS:

```bash
pihole restartdns
```

If Pi-hole works on one node but not after failover:

- Compare the Unbound local-zone config on both nodes.
- Confirm each Pi-hole points to local Unbound.
- Confirm Unbound is running on both nodes:

```bash
systemctl status unbound --no-pager
```

If reverse lookup for the Pi-hole VIP returns `pi.hole.`:

- Test a different PTR record.
- Pi-hole may be answering its own address before forwarding.
- This is usually cosmetic unless a service requires a specific PTR for the VIP.

## Public Repo Note

For public repositories, keep real node-specific Pi-hole/Unbound configs ignored and publish only sanitized examples.

Recommended pattern:

```text
Unbound/configs/example.conf
Unbound/configs/pihole0.conf  # ignored
Unbound/configs/pihole1.conf  # ignored
```
