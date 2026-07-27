# Pi-hole dual-stack Keepalived runbook

## Purpose

This runbook configures and validates a two-node Pi-hole and Unbound
Keepalived cluster with synchronized IPv4 and IPv6 virtual IP addresses.

The procedure is written for the following nodes and addresses:

| Role | Host | Priority | IPv4 | Stable ULA IPv6 |
| --- | --- | ---: | --- | --- |
| Preferred primary | `j1-svpihole0` | 150 | `10.1.0.53/22` | `fd36:5aa8:6971:1::53/64` |
| Backup | `j1-svpihole00` | 100 | `10.1.0.54/22` | `fd36:5aa8:6971:1::54/64` |
| Keepalived VIP | synchronized | — | `10.1.0.55/22` | `fd36:5aa8:6971:1::55/128` |

Other required addresses:

- IPv4 gateway: `10.1.0.1`
- ULA gateway: `fd36:5aa8:6971:1::1`
- Apprise API: `http://10.1.3.83:8000`
- Apprise configuration key: `apprise`

## Source and destination files

| Repository source | Deployment destination |
| --- | --- |
| `Keepalived/configs/keepalived-pihole0.conf` | `pihole0:/etc/keepalived/keepalived.conf` |
| `Keepalived/configs/keepalived-pihole00.conf` | `pihole00:/etc/keepalived/keepalived.conf` |
| `Keepalived/scripts/dns-check.sh` | Both nodes: `/etc/scripts/check-dns.sh` |
| `Keepalived/scripts/keepalived-notify.sh` | Both nodes: `/usr/local/bin/keepalived-notify.sh` |

## Design summary

- Both VRRP instances use VRRPv3.
- IPv4 uses virtual router ID `100`.
- IPv6 uses virtual router ID `101`.
- `PIHOLE_DUALSTACK` synchronizes both instances so the VIPs move together.
- Both nodes start in `BACKUP`; priority selects the preferred node.
- `pihole0` has priority `150`; `pihole00` has priority `100`.
- `preempt_delay 10` prevents immediate failback to a recovered preferred node.
- `check-dns` is an unweighted sync-group tracker. Three consecutive failures
  put the entire group into `FAULT`; three successes recover it.
- Each instance uses `track_src_ip` so loss of its stable source address causes
  a fault.
- The VRRP instance interface is inherently tracked by Keepalived. Do not add
  `track_interface eth0` to the sync group; Keepalived 2.2.7 reports it as
  duplicate tracking.
- The IPv6 VIP uses `/128 preferred_lft forever`. Keepalived may display the
  active address with `nodad`; this is expected for its virtual address.
- Scripts are owned by `root` but run as the unprivileged `pi` user.
- Apprise uses an IP address so DNS failure cannot prevent notifications.

## Important migration constraint

VRRPv2 and VRRPv3 peers do not participate in the same election. The original
cluster used IPv4 VRRPv2 with legacy `PASS` authentication. Do not activate
one new VRRPv3 configuration while the other node is still participating in
the old VRRPv2 election; that can cause duplicate VIP ownership.

For this migration:

1. Stage and install both new configurations without reloading.
2. Stop Keepalived on the old backup.
3. Restart the preferred primary into VRRPv3.
4. Validate both VIPs on the primary.
5. Start the backup into VRRPv3.

This ordering creates a short maintenance interval but prevents a mixed-version
split-brain condition.

## Prerequisites

Run on both nodes:

```bash
hostname
keepalived --version 2>&1 | head -n 1
systemctl is-active keepalived pihole-FTL unbound
command -v dig jq curl logger
```

Expected:

- Keepalived `2.2.7`
- All three services are active
- `dig`, `jq`, `curl`, and `logger` are installed

Verify the static node addresses:

```bash
ip -4 -o address show dev eth0 scope global
ip -6 -o address show dev eth0 scope global
ip -4 route
ip -6 route
```

Verify the health-check record on both nodes:

```bash
dig @127.0.0.1 -p 53 pihole.local.theama.co A +short
dig @127.0.0.1 -p 5335 pihole.local.theama.co A +short
```

Both queries must return:

```text
10.1.0.55
```

## Phase 1: pre-change cluster validation

Confirm that `pihole0` owns the existing IPv4 VIP:

```bash
ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
dig @10.1.0.55 example.com A +short
```

On `pihole00`, confirm that neither VIP is local:

```bash
ip -4 address show dev eth0 | grep -F '10.1.0.55/22' \
  || echo "PASS: IPv4 VIP is not on pihole00"

ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128' \
  || echo "PASS: IPv6 VIP is not on pihole00"
```

Do not proceed unless the existing IPv4 VIP answers and is owned by only one
node.

## Phase 2: create rollback copies

Run on each node before replacing its configuration:

```bash
KEEPALIVED_BACKUP="/etc/keepalived/keepalived.conf.pre-dualstack.$(date +%Y%m%d-%H%M%S)"

sudo cp -a -- \
  /etc/keepalived/keepalived.conf \
  "$KEEPALIVED_BACKUP"

sudo cmp --silent \
  /etc/keepalived/keepalived.conf \
  "$KEEPALIVED_BACKUP" \
  && echo "PASS: Keepalived backup verified"

printf 'Rollback configuration: %s\n' "$KEEPALIVED_BACKUP"
```

Record the path for each node. Backups created during the validated deployment
were:

- `pihole0`: `/etc/keepalived/keepalived.conf.pre-dualstack.20260726-233055`
- `pihole00`: `/etc/keepalived/keepalived.conf.pre-dualstack.20260726-230451`

## Phase 3: stage the files

On each node, create a staging directory and keep the SSH session open:

```bash
KEEPALIVED_STAGE=$(mktemp -d /tmp/keepalived-dualstack.XXXXXX)
chmod 700 "$KEEPALIVED_STAGE"
printf 'Staging directory: %s\n' "$KEEPALIVED_STAGE"
```

From the workstation, transfer the primary files:

```bash
PRIMARY_STAGE="/tmp/keepalived-dualstack.REPLACE_WITH_PIHOLE0_VALUE"

scp \
  /home/aaron/code/homelab-dns/Keepalived/configs/keepalived-pihole0.conf \
  pi@j1-svpihole0:"${PRIMARY_STAGE}/keepalived.conf"

scp \
  /home/aaron/code/homelab-dns/Keepalived/scripts/dns-check.sh \
  /home/aaron/code/homelab-dns/Keepalived/scripts/keepalived-notify.sh \
  pi@j1-svpihole0:"${PRIMARY_STAGE}/"
```

Set `PRIMARY_STAGE` to the exact staging path printed on `pihole0` before
running `scp`.

Transfer the backup files:

```bash
BACKUP_STAGE="/tmp/keepalived-dualstack.REPLACE_WITH_PIHOLE00_VALUE"

scp \
  /home/aaron/code/homelab-dns/Keepalived/configs/keepalived-pihole00.conf \
  pi@j1-svpihole00:"${BACKUP_STAGE}/keepalived.conf"

scp \
  /home/aaron/code/homelab-dns/Keepalived/scripts/dns-check.sh \
  /home/aaron/code/homelab-dns/Keepalived/scripts/keepalived-notify.sh \
  pi@j1-svpihole00:"${BACKUP_STAGE}/"
```

Set `BACKUP_STAGE` to the exact staging path printed on `pihole00` before
running `scp`.

On each node, inspect the staged files:

```bash
ls -l "$KEEPALIVED_STAGE"

file \
  "$KEEPALIVED_STAGE/keepalived.conf" \
  "$KEEPALIVED_STAGE/dns-check.sh" \
  "$KEEPALIVED_STAGE/keepalived-notify.sh"

sha256sum \
  "$KEEPALIVED_STAGE/keepalived.conf" \
  "$KEEPALIVED_STAGE/dns-check.sh" \
  "$KEEPALIVED_STAGE/keepalived-notify.sh"
```

## Phase 4: validate staged content

Run on each node:

```bash
bash -n \
  "$KEEPALIVED_STAGE/dns-check.sh" \
  "$KEEPALIVED_STAGE/keepalived-notify.sh" \
  && echo "PASS: Bash syntax"

if grep -n $'\r' \
  "$KEEPALIVED_STAGE/keepalived.conf" \
  "$KEEPALIVED_STAGE/dns-check.sh" \
  "$KEEPALIVED_STAGE/keepalived-notify.sh"
then
  echo "FAIL: CRLF characters found"
else
  echo "PASS: Unix LF line endings"
fi

"$KEEPALIVED_STAGE/dns-check.sh"
echo "DNS health-check exit code: $?"

grep -nE \
  'router_id|vrrp_version|state|priority|advert_int|preempt_delay|unicast_src_ip|track_src_ip' \
  "$KEEPALIVED_STAGE/keepalived.conf"

grep -nE \
  '^APPRISE_(URL|KEY|ENDPOINT)=' \
  "$KEEPALIVED_STAGE/keepalived-notify.sh"
```

Expected common settings:

```text
vrrp_version 3
state BACKUP
advert_int 0.5
preempt_delay 10
APPRISE_URL="http://10.1.3.83:8000"
APPRISE_KEY="apprise"
```

Expected node-specific settings:

| Setting | `pihole0` | `pihole00` |
| --- | --- | --- |
| `router_id` | `j1-svpihole0` | `j1-svpihole00` |
| `priority` | `150` | `100` |
| IPv4 source | `10.1.0.53` | `10.1.0.54` |
| IPv4 peer | `10.1.0.54` | `10.1.0.53` |
| IPv6 source | `fd36:5aa8:6971:1::53` | `fd36:5aa8:6971:1::54` |
| IPv6 peer | `fd36:5aa8:6971:1::54` | `fd36:5aa8:6971:1::53` |

The DNS health-check exit code must be `0`.

## Phase 5: install and test the scripts

On both nodes:

```bash
sudo install -o root -g root -m 0755 \
  "$KEEPALIVED_STAGE/dns-check.sh" \
  /etc/scripts/check-dns.sh

sudo install -o root -g root -m 0755 \
  "$KEEPALIVED_STAGE/keepalived-notify.sh" \
  /usr/local/bin/keepalived-notify.sh

sudo cmp --silent \
  "$KEEPALIVED_STAGE/dns-check.sh" \
  /etc/scripts/check-dns.sh \
  && echo "PASS: DNS script installed"

sudo cmp --silent \
  "$KEEPALIVED_STAGE/keepalived-notify.sh" \
  /usr/local/bin/keepalived-notify.sh \
  && echo "PASS: notification script installed"

sudo ls -l \
  /etc/scripts/check-dns.sh \
  /usr/local/bin/keepalived-notify.sh

sudo -u pi /etc/scripts/check-dns.sh
echo "Installed DNS health-check exit code: $?"
```

Expected:

- Ownership `root:root`
- Mode `0755`
- Health-check exit code `0`

Test Apprise from both nodes:

```bash
sudo -u pi /usr/local/bin/keepalived-notify.sh \
  GROUP INSTALL_TEST TEST

sleep 6

sudo journalctl \
  -t keepalived-notify \
  --since "2 minutes ago" \
  --no-pager
```

Confirm successful delivery in the journal, Discord, and Pushover.

## Phase 6: parse-test Keepalived

On each node:

```bash
KEEPALIVED_TEST_LOG="/tmp/keepalived-dualstack-test.$(date +%Y%m%d-%H%M%S).log"

sudo /usr/sbin/keepalived \
  --config-test="$KEEPALIVED_TEST_LOG" \
  --use-file="$KEEPALIVED_STAGE/keepalived.conf"

KEEPALIVED_TEST_STATUS=$?

printf 'Keepalived parser exit code: %s\n' \
  "$KEEPALIVED_TEST_STATUS"

sudo sed -n '1,240p' "$KEEPALIVED_TEST_LOG"
```

### Keepalived 2.2.7 parser behavior

On these Debian systems, a valid-looking `--config-test` process self-issued
`SIGTERM`, printed `Terminated`, returned exit `143`, and wrote an empty log.
An intentionally invalid sample returned exit `5` and explicit errors.

Treat explicit parser errors or exit `5` as a stop condition. Exit `143` with
an empty log is not sufficient validation by itself; complete the controlled
runtime activation and journal checks below.

## Phase 7: install both configuration files without reloading

Run on each node:

```bash
sudo install -o root -g root -m 0644 \
  "$KEEPALIVED_STAGE/keepalived.conf" \
  /etc/keepalived/keepalived.conf.new

sudo cmp --silent \
  "$KEEPALIVED_STAGE/keepalived.conf" \
  /etc/keepalived/keepalived.conf.new \
  && echo "PASS: replacement verified"

sudo mv -- \
  /etc/keepalived/keepalived.conf.new \
  /etc/keepalived/keepalived.conf

sudo cmp --silent \
  "$KEEPALIVED_STAGE/keepalived.conf" \
  /etc/keepalived/keepalived.conf \
  && echo "PASS: configuration installed"
```

Do not reload either node until both files are installed.

## Phase 8: coordinated VRRPv2-to-v3 activation

### 8.1 Stop the old backup election

On `pihole00`:

```bash
sudo systemctl stop keepalived

systemctl is-active keepalived \
  || echo "PASS: pihole00 Keepalived stopped"

dig @10.1.0.55 example.com A +short
```

The IPv4 VIP must continue answering from `pihole0`.

### 8.2 Activate the preferred primary

On `pihole0`:

```bash
sudo systemctl restart keepalived
sleep 15

systemctl is-active keepalived

ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128'

dig @10.1.0.55 example.com A +short
dig -6 @fd36:5aa8:6971:1::55 example.com AAAA +short

sudo journalctl \
  -u keepalived \
  --since "3 minutes ago" \
  --no-pager
```

Expected:

- Keepalived is active.
- Both VIPs are on `pihole0`.
- IPv4 and IPv6 DNS queries succeed.
- Both instances enter `MASTER` through `PIHOLE_DUALSTACK`.
- No duplicate `track_interface` warning appears.

### 8.3 Start the VRRPv3 backup

On `pihole00`:

```bash
sudo systemctl start keepalived
sleep 5

systemctl is-active keepalived

ip -4 address show dev eth0 | grep -F '10.1.0.55/22' \
  || echo "PASS: IPv4 VIP remains on primary"

ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128' \
  || echo "PASS: IPv6 VIP remains on primary"

dig @10.1.0.55 example.com A +short
dig -6 @fd36:5aa8:6971:1::55 example.com AAAA +short

sudo journalctl \
  -u keepalived \
  --since "2 minutes ago" \
  --no-pager
```

Expected:

- `pihole00` enters `BACKUP`.
- Neither VIP is local to `pihole00`.
- Both VIPs continue answering through `pihole0`.

## Phase 9: controlled service-stop failover

On `pihole0`:

```bash
sudo systemctl stop keepalived

ip -4 address show dev eth0 | grep -F '10.1.0.55/22' \
  || echo "PASS: IPv4 VIP left pihole0"

ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128' \
  || echo "PASS: IPv6 VIP left pihole0"
```

On `pihole00`:

```bash
sleep 5

ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128'

dig @10.1.0.55 example.com A +short
dig -6 @fd36:5aa8:6971:1::55 example.com AAAA +short

sudo journalctl \
  -u keepalived \
  --since "2 minutes ago" \
  --no-pager
```

Both VIPs must move together to `pihole00`.

## Phase 10: delayed failback

Start the preferred primary:

```bash
sudo systemctl start keepalived
sleep 5

if ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
then
  echo "FAIL: IPv4 preempted before delay"
else
  echo "PASS: IPv4 remains on backup during delay"
fi

if ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128'
then
  echo "FAIL: IPv6 preempted before delay"
else
  echo "PASS: IPv6 remains on backup during delay"
fi

sleep 10

ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128'
```

The validated deployment waited approximately 12 seconds from startup before
the preferred node reclaimed both VIPs.

On `pihole00`, confirm both VIPs left:

```bash
ip -4 address show dev eth0 | grep -F '10.1.0.55/22' \
  || echo "PASS: IPv4 returned to pihole0"

ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128' \
  || echo "PASS: IPv6 returned to pihole0"
```

## Phase 11: health-triggered failover

Stop Pi-hole FTL on the preferred primary:

```bash
sudo systemctl stop pihole-FTL
sleep 5

systemctl is-active pihole-FTL \
  || echo "PASS: pihole-FTL stopped for test"

systemctl is-active keepalived

ip -4 address show dev eth0 | grep -F '10.1.0.55/22' \
  || echo "PASS: IPv4 left unhealthy primary"

ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128' \
  || echo "PASS: IPv6 left unhealthy primary"

sudo journalctl \
  -u keepalived \
  --since "2 minutes ago" \
  --no-pager
```

Expected primary journal sequence:

```text
Script `check-dns` now returning 1
VRRP_Script(check-dns) failed
PIHOLE_IPV4 Entering FAULT STATE
PIHOLE_DUALSTACK Syncing instances to FAULT state
PIHOLE_IPV6 Entering FAULT STATE
```

On `pihole00`, verify both VIPs and DNS:

```bash
ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128'

dig @10.1.0.55 example.com A +short
dig -6 @fd36:5aa8:6971:1::55 example.com AAAA +short
```

Restore Pi-hole FTL on `pihole0`:

```bash
sudo systemctl start pihole-FTL
sleep 5

systemctl is-active pihole-FTL

sudo -u pi /etc/scripts/check-dns.sh
echo "DNS health-check exit code: $?"
```

At five seconds, both VIPs should still be on `pihole00`. After another ten
seconds, both should return to `pihole0`:

```bash
sleep 10

ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128'

dig @10.1.0.55 example.com A +short
dig -6 @fd36:5aa8:6971:1::55 example.com AAAA +short
```

## Phase 12: final steady-state validation

On `pihole0`:

```bash
systemctl is-enabled keepalived
systemctl is-active keepalived pihole-FTL unbound

ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128'

dig @10.1.0.55 example.com A +short
dig -6 @fd36:5aa8:6971:1::55 example.com AAAA +short
```

On `pihole00`:

```bash
systemctl is-enabled keepalived
systemctl is-active keepalived pihole-FTL unbound

ip -4 address show dev eth0 | grep -F '10.1.0.55/22' \
  || echo "PASS: IPv4 is on pihole0"

ip -6 address show dev eth0 | grep -F 'fd36:5aa8:6971:1::55/128' \
  || echo "PASS: IPv6 is on pihole0"

sudo -u pi /etc/scripts/check-dns.sh
echo "Backup DNS health-check exit code: $?"
```

Expected final state:

| Check | `pihole0` | `pihole00` |
| --- | --- | --- |
| Keepalived | enabled, active | enabled, active |
| Pi-hole FTL | active | active |
| Unbound | active | active |
| Health script | exit `0` | exit `0` |
| IPv4 VIP | present | absent |
| IPv6 VIP | present | absent |

## Cleanup

After all tests pass, remove only the temporary staging directories:

```bash
rm -r -- /tmp/keepalived-dualstack.XXXXXX
```

Use each node's exact generated path. Do not remove the rollback
configurations under `/etc/keepalived`.

## Rollback

If activation fails, prevent duplicate ownership by stopping Keepalived on both
nodes before restoring VRRPv2:

```bash
sudo systemctl stop keepalived
```

Restore the recorded pre-dual-stack configuration on each node:

```bash
sudo cp -a -- \
  /etc/keepalived/keepalived.conf.pre-dualstack.TIMESTAMP \
  /etc/keepalived/keepalived.conf
```

Start the old primary first:

```bash
sudo systemctl start keepalived
sleep 5

ip -4 address show dev eth0 | grep -F '10.1.0.55/22'
dig @10.1.0.55 example.com A +short
```

Only after the primary owns the IPv4 VIP should the old backup be started:

```bash
sudo systemctl start keepalived
```

Verify the IPv4 VIP is absent on the backup. The old VRRPv2 configuration does
not provide the IPv6 VIP.

## Known observations

- Keepalived 2.2.7 emitted a notice recommending `max_auto_priority`. The
  deployed configuration intentionally leaves automatic real-time scheduling
  escalation disabled.
- The Debian service occasionally logged that a systemd notification came from
  the VRRP child rather than the main PID. The service nevertheless reached
  `active/running`; validate service state and VIP behavior rather than treating
  that line alone as failure.
- During one rapid startup `BACKUP` to `MASTER` transition, the asynchronous
  BACKUP Apprise request timed out while the MASTER notification succeeded.
  Subsequent MASTER and BACKUP transition notifications delivered successfully.
- Full host-reboot validation is separate from the service-stop and
  health-trigger tests. Reboot `pihole00` first and confirm it returns as
  backup before scheduling a controlled reboot of `pihole0`.
