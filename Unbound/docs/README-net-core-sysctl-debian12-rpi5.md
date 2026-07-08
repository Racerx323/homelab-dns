# Debian 12 Raspberry Pi 5 net.core Sysctl Tuning for Unbound

This guide configures Linux socket buffer limits for Unbound on Debian 12 running on a Raspberry Pi 5.

The Unbound configuration uses:

```conf
so-rcvbuf: 4m
so-sndbuf: 4m
```

Linux caps requested socket buffers with kernel sysctl values. If the caps are lower than Unbound requests, Unbound may log warnings and silently receive a smaller buffer than configured.

For `4m` Unbound buffers, configure:

```text
net.core.rmem_max >= 4194304
net.core.wmem_max >= 4194304
```

`4194304` bytes is 4 MiB.

## Check Current Values

Run:

```bash
sysctl net.core.rmem_max
sysctl net.core.wmem_max
```

Expected minimum values:

```text
net.core.rmem_max = 4194304
net.core.wmem_max = 4194304
```

Higher values are also acceptable.

## Apply Temporarily

Temporary changes are useful for testing. They reset after reboot.

```bash
sudo sysctl -w net.core.rmem_max=4194304
sudo sysctl -w net.core.wmem_max=4194304
```

Verify:

```bash
sysctl net.core.rmem_max
sysctl net.core.wmem_max
```

Restart Unbound so it requests the buffers again:

```bash
sudo systemctl restart unbound
```

Check service status:

```bash
systemctl status unbound --no-pager
```

## Apply Persistently

Create a dedicated sysctl drop-in:

```bash
sudo nano /etc/sysctl.d/unbound-socket-buffers.conf
```

Add:

```conf
# Unbound socket buffer caps for so-rcvbuf: 4m and so-sndbuf: 4m.
net.core.rmem_max = 4194304
net.core.wmem_max = 4194304
```

Load the drop-in without rebooting:

```bash
sudo sysctl --system
```

Verify:

```bash
sysctl net.core.rmem_max
sysctl net.core.wmem_max
```

Restart Unbound:

```bash
sudo systemctl restart unbound
```

## Validate Unbound

Check the Unbound configuration:

```bash
sudo unbound-checkconf /etc/unbound/unbound.conf.d/pihole.conf
```

Confirm local Unbound still answers:

```bash
dig @127.0.0.1 -p 5335 pihole.local.theama.co A
dig @127.0.0.1 -p 5335 _smtp._tcp.local.theama.co SRV
```

Confirm Pi-hole through the keepalived VIP still answers:

```bash
dig @10.1.0.55 pihole.local.theama.co A
dig @10.1.0.55 -x 10.1.0.1
```

Check Unbound logs for socket buffer warnings:

```bash
sudo journalctl -u unbound -b --no-pager
```

Warnings to look for include messages about failing to set receive or send buffer size. If they appear, re-check the sysctl values and restart Unbound.

## Reboot Validation

After a reboot:

```bash
sysctl net.core.rmem_max
sysctl net.core.wmem_max
systemctl status unbound --no-pager
```

Then repeat the `dig` checks above.

## Rollback

Remove or edit:

```text
/etc/sysctl.d/unbound-socket-buffers.conf
```

Reload sysctl settings:

```bash
sudo sysctl --system
```

Then either remove/comment the Unbound socket buffer settings or leave them to be capped by the OS:

```conf
#so-rcvbuf: 4m
#so-sndbuf: 4m
```

Restart Unbound:

```bash
sudo systemctl restart unbound
```

## Notes

- These settings raise maximum socket buffer caps; they do not allocate 4 MiB permanently for every socket by themselves.
- This tuning is most useful during DNS traffic bursts.
- In this Pi-hole plus Unbound design, clients query Pi-hole on the keepalived VIP and Pi-hole forwards to local Unbound on `127.0.0.1:5335`.
- Apply the same sysctl drop-in on both Pi-hole/Unbound nodes so failover behavior is consistent.
