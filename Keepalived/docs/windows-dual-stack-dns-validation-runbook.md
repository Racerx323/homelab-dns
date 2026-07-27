# Windows dual-stack DNS validation runbook

## Purpose

This runbook validates that a Windows client on the UniFi Default LAN receives
and uses the synchronized Pi-hole Keepalived DNS VIPs over IPv4 and IPv6.

Expected DNS VIPs:

| Address family | DNS VIP |
| --- | --- |
| IPv4 | `10.1.0.55` |
| IPv6 ULA | `fd36:5aa8:6971:1::55` |

The related server deployment procedure is
[keepalived-dual-stack-runbook.md](keepalived-dual-stack-runbook.md).

## Expected UniFi Default LAN configuration

### IPv4

- DHCP mode: DHCP Server
- DHCP server: `10.1.0.1`
- DHCP range: `10.1.0.103` through `10.1.3.254`
- Auto Default Gateway: enabled
- Auto DNS Server: disabled
- DNS server: `10.1.0.55`
- DHCP Guarding trusted server: `10.1.0.1`

The Keepalived VIP and node addresses are outside the DHCP pool.

### IPv6

- Interface type: Prefix Delegation
- Prefix Delegation interface: ISP
- Additional IP: `fd36:5aa8:6971:1::1/64`
- Client address assignment: SLAAC
- Auto DNS Server: disabled
- DNS server: `fd36:5aa8:6971:1::55`
- Router Advertisement: enabled
- RA priority: High

Do not advertise these addresses as DNS servers:

- UDM-SE ULA gateway: `fd36:5aa8:6971:1::1`
- UDM-SE dynamic global address: `2600:1702:7370:2f4f::1`
- Individual Pi-hole node addresses
- Public DNS resolvers

Advertising only the VIPs prevents clients from bypassing Pi-hole and preserves
DNS service during Keepalived failover.

## Prerequisites

- Windows client connected to the UniFi Default LAN
- Windows PowerShell
- Administrator PowerShell for adapter restart commands
- Pi-hole Keepalived cluster in its normal steady state
- `pihole0` owns both VIPs
- `pihole00` is in `BACKUP`

## Step 1: identify the active LAN adapter

Open PowerShell and run:

```powershell
Get-NetIPConfiguration |
    Where-Object {$_.NetAdapter.Status -eq "Up"} |
    Format-List InterfaceAlias,IPv4Address,IPv6Address,IPv4DefaultGateway,IPv6DefaultGateway
```

Identify the physical Ethernet or Wi-Fi interface connected to Default LAN.
Ignore WSL, Hyper-V, VPN, Bluetooth, loopback, and other virtual interfaces.

Set a variable for the remaining commands. This deployment used `10G`:

```powershell
$LanInterface = "10G"
```

Expected active-interface addressing:

- An IPv4 address inside `10.1.0.0/22`
- A stable ULA address inside `fd36:5aa8:6971:1::/64`
- A global IPv6 address inside the current ISP-delegated `/64`

Example:

```text
IPv4: 10.1.3.141
ULA:  fd36:5aa8:6971:1:...
GUA:  2600:1702:7370:2f4f:...
```

## Step 2: inspect advertised DNS servers

```powershell
Get-DnsClientServerAddress -InterfaceAlias $LanInterface -AddressFamily IPv4 |
    Format-Table InterfaceAlias,ServerAddresses -AutoSize

Get-DnsClientServerAddress -InterfaceAlias $LanInterface -AddressFamily IPv6 |
    Format-Table InterfaceAlias,ServerAddresses -AutoSize
```

Expected:

```text
IPv4: {10.1.0.55}
IPv6: {fd36:5aa8:6971:1::55}
```

The active LAN interface should not list the UDM-SE, an individual Pi-hole
node, or a public resolver as an additional DNS server.

## Step 3: clear stale router advertisements

Use this step only if the active adapter still lists an old DNS server after
the UniFi configuration changes.

Open PowerShell as Administrator:

```powershell
Restart-NetAdapter -Name $LanInterface -Confirm:$false

Start-Sleep -Seconds 10
```

Recheck the DNS servers:

```powershell
Get-DnsClientServerAddress -InterfaceAlias $LanInterface -AddressFamily IPv4 |
    Format-Table InterfaceAlias,ServerAddresses -AutoSize

Get-DnsClientServerAddress -InterfaceAlias $LanInterface -AddressFamily IPv6 |
    Format-Table InterfaceAlias,ServerAddresses -AutoSize
```

In the validated deployment, the stale UDM-SE DNS address
`2600:1702:7370:2f4f::1` disappeared after restarting the adapter.

If it returns immediately, recheck that **Auto DNS Server** is disabled in the
Default LAN IPv6 settings.

## Step 4: test VIP reachability

```powershell
ping.exe -n 3 10.1.0.55

ping.exe -6 -n 3 fd36:5aa8:6971:1::55
```

Expected:

- Three replies from each VIP
- Zero percent packet loss
- LAN-local latency

Test public IPv6 reachability:

```powershell
ping.exe -6 -n 3 2606:4700:4700::1111
```

Failure to reach the local ULA VIP indicates a LAN addressing, route, firewall,
or VIP-ownership problem. Failure only to reach the public address indicates a
WAN IPv6 or prefix-delegation problem.

## Step 5: test each VIP directly

Query the IPv4 VIP:

```powershell
Resolve-DnsName example.com -Type A -Server 10.1.0.55
```

Query the IPv6 VIP:

```powershell
Resolve-DnsName example.com -Type AAAA -Server fd36:5aa8:6971:1::55
```

Expected:

- Status is successful.
- The IPv4 query returns one or more `A` records.
- The IPv6 query returns one or more `AAAA` records.

Example answers can change over time. Validate the record type and successful
response rather than requiring specific public addresses.

## Step 6: test the Windows default resolver

Clear cached answers:

```powershell
Clear-DnsClientCache
```

Resolve through the DNS configuration supplied by UniFi:

```powershell
Resolve-DnsName example.com -Type A

Resolve-DnsName example.com -Type AAAA
```

Both commands must succeed. These tests confirm that Windows can use the
advertised VIPs without an explicit `-Server` override.

## Step 7: verify an internal record

```powershell
Resolve-DnsName pihole.local.theama.co -Type A
```

Expected:

```text
10.1.0.55
```

This verifies that Windows is using the internal Pi-hole and Unbound path
rather than bypassing it through a public resolver.

## Step 8: optional Windows-observed failover test

Perform this only during a maintenance window. Keep two PowerShell windows
open on the Windows client.

### Window 1: continuously query the IPv4 VIP

```powershell
while ($true) {
    $Timestamp = Get-Date -Format "HH:mm:ss.fff"

    try {
        $Answers = Resolve-DnsName example.com `
            -Type A `
            -Server 10.1.0.55 `
            -DnsOnly `
            -ErrorAction Stop

        $Addresses = ($Answers |
            Where-Object {$_.Type -eq "A"} |
            Select-Object -ExpandProperty IPAddress) -join ","

        Write-Host "$Timestamp IPv4 PASS $Addresses" -ForegroundColor Green
    }
    catch {
        Write-Host "$Timestamp IPv4 FAIL $($_.Exception.Message)" -ForegroundColor Red
    }

    Start-Sleep -Seconds 1
}
```

### Window 2: continuously query the IPv6 VIP

```powershell
while ($true) {
    $Timestamp = Get-Date -Format "HH:mm:ss.fff"

    try {
        $Answers = Resolve-DnsName example.com `
            -Type AAAA `
            -Server fd36:5aa8:6971:1::55 `
            -DnsOnly `
            -ErrorAction Stop

        $Addresses = ($Answers |
            Where-Object {$_.Type -eq "AAAA"} |
            Select-Object -ExpandProperty IPAddress) -join ","

        Write-Host "$Timestamp IPv6 PASS $Addresses" -ForegroundColor Green
    }
    catch {
        Write-Host "$Timestamp IPv6 FAIL $($_.Exception.Message)" -ForegroundColor Red
    }

    Start-Sleep -Seconds 1
}
```

Press `Ctrl+C` in each window to stop the loops.

### Trigger service-stop failover

On `pihole0`:

```bash
sudo systemctl stop keepalived
```

Expected:

- Both Windows query loops continue or recover quickly.
- Both VIPs move to `pihole00`.
- The IPv4 and IPv6 behavior is synchronized.

Restore the preferred node:

```bash
sudo systemctl start keepalived
```

The VIPs should remain on `pihole00` during the 10-second preemption delay and
then return together to `pihole0`.

### Trigger health-check failover

On `pihole0`:

```bash
sudo systemctl stop pihole-FTL
```

After three failed health checks, both VIPs should move to `pihole00`.

Restore Pi-hole:

```bash
sudo systemctl start pihole-FTL
```

The primary must pass three health checks and the preemption delay before
reclaiming the VIPs.

## Step 9: final client validation

After all failover testing:

```powershell
Get-DnsClientServerAddress -InterfaceAlias $LanInterface -AddressFamily IPv4 |
    Format-Table InterfaceAlias,ServerAddresses -AutoSize

Get-DnsClientServerAddress -InterfaceAlias $LanInterface -AddressFamily IPv6 |
    Format-Table InterfaceAlias,ServerAddresses -AutoSize

ping.exe -n 3 10.1.0.55
ping.exe -6 -n 3 fd36:5aa8:6971:1::55

Resolve-DnsName example.com -Type A
Resolve-DnsName example.com -Type AAAA
Resolve-DnsName pihole.local.theama.co -Type A
```

Final expected state:

| Check | Expected |
| --- | --- |
| IPv4 DNS server | Only `10.1.0.55` |
| IPv6 DNS server | Only `fd36:5aa8:6971:1::55` |
| IPv4 VIP ping | Success |
| IPv6 VIP ping | Success |
| Public A lookup | Success |
| Public AAAA lookup | Success |
| Internal Pi-hole record | `10.1.0.55` |

## Troubleshooting

### UDM-SE IPv6 address remains in the DNS list

1. Confirm **Auto DNS Server** is disabled under Default LAN IPv6.
2. Confirm the only configured IPv6 DNS server is
   `fd36:5aa8:6971:1::55`.
3. Restart the Windows adapter.
4. Recheck `Get-DnsClientServerAddress`.

### Direct VIP queries work but default queries fail

1. Recheck the DNS server list on the active adapter.
2. Disable or inspect VPN and security software that overrides Windows DNS.
3. Check for manually configured DNS servers:

   ```powershell
   Get-DnsClientServerAddress -InterfaceAlias $LanInterface
   ```

4. Reconnect the adapter and clear the Windows DNS cache.

### IPv4 succeeds but IPv6 fails

1. Confirm the Windows client has a ULA address in
   `fd36:5aa8:6971:1::/64`.
2. Confirm UniFi Router Advertisement is enabled.
3. Ping the ULA gateway:

   ```powershell
   ping.exe -6 -n 3 fd36:5aa8:6971:1::1
   ```

4. Confirm the IPv6 VIP is present on exactly one Pi-hole node.
5. Confirm Pi-hole answers directly on `fd36:5aa8:6971:1::55`.

### Public DNS works but internal records fail

This usually indicates that Windows is bypassing Pi-hole. Confirm that the
active interface lists only the two Keepalived VIPs and that UniFi Content
Filtering, Ad Blocking, a VPN, encrypted DNS, or endpoint security is not
redirecting DNS traffic.
