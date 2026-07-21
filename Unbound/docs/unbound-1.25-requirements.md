# Unbound 1.25.1 Scenario Requirements

This document is the authoritative requirements baseline for the Unbound
1.25.1 packaging, deployment, configuration, rollback, and acceptance
scenarios. The scenario runbooks and automation must remain consistent with
these requirements.

## Shared Build and Release Foundation

- Pin Unbound `1.25.1`; do not resolve “latest” dynamically. Future releases require an intentional version/checksum update and full regression run.
- Backport Debian’s existing `unbound_1.25.1-1` source package to Debian 12 rather than creating packaging from scratch. Debian already packages 1.25.1 for newer releases, while Bookworm supplies 1.17.1. [Debian sources](https://sources.debian.org/src/unbound/), [upstream release](https://www.nlnnetlabs.nl/projects/unbound/download/)
- Build natively for `arm64` in an isolated, fully updated Debian 12 builder using `sbuild` or an equivalent clean Bookworm chroot.
- Version the backport `1.25.1-1~bookworm1`, preserving Debian’s package names, dependencies, systemd unit, AppArmor profile, tmpfiles handling, trust-anchor integration, and conffile behavior.
- Retain required compile features: systemd, libevent, Python bindings, subnet, DNSTAP, libnghttp2, TCP Fast Open, and Debian filesystem paths.
- Run upstream tests, Debian package tests, `lintian`, package-content inspection, and clean install/upgrade/removal tests.
- Produce a signed release bundle containing:
  - Required arm64 and architecture-independent `.deb` files.
  - Source package, `.changes`, and `.buildinfo`.
  - `SHA256SUMS` and a detached GPG signature.
  - Build manifest with source commit/version, toolchain versions, configure flags, dependencies, and test results.
  - Installation, verification, upgrade, and rollback runbooks.
- Treat custom builds as an internally maintained security product: monitor NLnet Labs and Debian security announcements, then rebuild and redeploy deliberately for each approved release.

## Scenario 1: Rolling Upgrade of Pi-hole v5 HA Nodes

### Configuration and preflight

- Upgrade the installed Debian `unbound` package in place using the signed 1.25.1 Bookworm backport.
- Preserve `/etc/unbound/unbound.conf.d/pihole.conf` byte-for-byte unless the 1.25.1 validator identifies an error or an option has changed behavior.
- Retain the existing Cloudflare DNS-over-TLS `forward-zone`; this scenario does not convert the HA nodes to full recursion.
- Before changing either node:
  - Record OS, architecture, installed Unbound package set, `unbound -V`, Pi-hole version, Pi-hole upstreams, keepalived role, systemd overrides, AppArmor status, sysctls, listeners, and firewall state.
  - Back up `/etc/unbound`, `/var/lib/unbound`, relevant AppArmor local rules, sysctl drop-ins, systemd overrides, Pi-hole configuration, and the current Debian `.deb` packages.
  - Record checksums and package ownership for every Unbound configuration file.
  - Verify the VIP is healthy on `pihole0` and keep it away from the node being upgraded.
  - Validate IPv4 and IPv6 connectivity to the configured Cloudflare DoT endpoints on TCP 853.
- Test the live `pihole.conf` against the newly built 1.25.1 binary before installation. If validation fails:
  - Stop the rollout.
  - Copy the file to a candidate configuration.
  - Make only the minimum compatibility correction.
  - Record a unified diff and the reason for every changed directive.
  - Validate the candidate with both the old and new binaries where possible.
- Review warnings separately from fatal errors. Performance recommendations alone do not authorize changing the existing cache, threading, local-zone, logging, or forwarding behavior.

### Package upgrade and service handling

- Install the signed package set through `apt`, allowing normal Debian upgrade and conffile handling.
- Never answer a conffile prompt by blindly accepting the package version; retain the administrator version and review differences separately.
- Preserve Debian’s systemd unit and maintainer scripts instead of installing the custom unit from `unbound-main.docx`.
- Disable `unbound-resolvconf.service` and prevent creation of `resolvconf_resolvers.conf`, because Pi-hole uses Unbound on port 5335 and `/etc/resolv.conf` cannot express that port.
- Retain the 4 MiB socket-buffer settings and verify:
  - `net.core.rmem_max >= 4194304`
  - `net.core.wmem_max >= 4194304`
- Keep the existing file log only after validating its directory ownership, logrotate `create` settings, `unbound-control log_reopen`, and AppArmor local exception.
- Validate the DNSSEC trust anchor, remote-control credentials, runtime directories, and file permissions before restarting.
- Require `unbound-checkconf` as a pre-start check; a failed validation must leave the existing service or the peer HA node available.

### Rolling deployment

1. Upgrade standby node `pihole00` while `pihole0` owns the VIP.
2. Confirm package versions, service status, listeners, logs, and direct queries to `127.0.0.1:5335`.
3. Confirm Pi-hole v5 still forwards only to its local Unbound instance.
4. Move the VIP to `pihole00` and test public, local-zone, PTR, SRV, DNSSEC, IPv4, and IPv6 responses through `10.1.0.55`.
5. Observe the standby under live traffic before touching `pihole0`.
6. Upgrade and validate `pihole0`.
7. Restore `pihole0` as preferred VIP owner and perform failover/failback testing.
8. Reboot one node at a time and repeat service, DNS, and VIP tests.

### Rollback

- Move the VIP immediately to the known-good peer.
- Reinstall the cached Bookworm 1.17.1 package set through `apt`.
- Restore the matching `/etc/unbound` and `/var/lib/unbound` backup if the new package or a compatibility edit changed them.
- Reapply the previous Pi-hole upstream configuration if it changed.
- Validate direct Unbound and Pi-hole resolution before returning the node to keepalived service.
- Never downgrade both nodes during the same maintenance action.

## Scenario 2: Clean Pi-hole v6 Target

### Package and configuration interfaces

- Use the same tested 1.25.1 Bookworm binary packages.
- Add a separate architecture-independent `unbound-pihole-profile` package so application binaries and site configuration have independent lifecycles.
- The profile package installs a managed conffile at `/etc/unbound/unbound.conf.d/pihole.conf` with:
  - Loopback-only listeners on `127.0.0.1` and `::1`.
  - Port `5335`, UDP and TCP enabled.
  - Native IPv4 and IPv6 recursion.
  - DNSSEC validation and qname minimisation.
  - EDNS buffer size `1232`.
  - Rebinding protection for private IPv4 and IPv6 ranges.
  - Conservative Raspberry Pi 5 cache/thread defaults.
  - No forward zone, public resolver, private hostname, or private local-zone record.
  - DNSTAP disabled.
- Provide a disabled `home.arpa` local-zone example under `/usr/share/doc/unbound-pihole-profile/examples`; do not activate it automatically.
- Prefer journald/syslog for the generic profile, avoiding custom log-file permissions and AppArmor changes.
- The package must not modify Pi-hole, keepalived, firewall, `/etc/resolv.conf`, or network configuration in maintainer scripts.

### Installation workflow

1. Require Debian 12 arm64 and an independently installed, healthy Pi-hole v6.
2. Verify the signed release manifest and each package checksum.
3. Confirm UDP and TCP port 53 can reach a real root server without interception, following Pi-hole’s official tests. Abort full-recursion installation if the root-server response is proxied or TCP/53 is blocked. [Pi-hole Unbound guide](https://docs.pi-hole.net/guides/dns/unbound/)
4. Confirm port `5335` is free and system time is synchronized.
5. Install the package closure and `unbound-pihole-profile` through `apt`.
6. Disable `unbound-resolvconf.service` if present and ensure the host resolver has not been pointed to `127.0.0.1` without a port.
7. Apply and verify the profile’s required socket-buffer sysctls.
8. Run `unbound-checkconf`, initialize/verify the root trust anchor, start Unbound, and test it directly.
9. Only after direct tests pass, configure Pi-hole v6 explicitly:
   - Set `dns.upstreams` to local Unbound using the validated `pihole-FTL --config` interface.
   - Remove public upstreams from that array.
   - Leave Pi-hole-side DNSSEC validation disabled so Unbound is the single validation layer.
   - Restart/reload FTL through the supported Pi-hole command.
10. Verify Pi-hole forwards queries to port 5335 and answers clients normally. Pi-hole v6 configuration is managed through `/etc/pihole/pihole.toml`, with its CLI preferred for validation. [Pi-hole v6 configuration](https://docs.pi-hole.net/ftldns/configfile/)

### Clean-target rollback

- Restore the previously captured Pi-hole v6 `dns.upstreams` value before stopping Unbound.
- Remove `unbound-pihole-profile` and the custom Unbound packages through `apt`.
- Preserve modified conffiles as `.dpkg-*` or an explicit backup for recovery.
- Reinstall Debian’s Bookworm Unbound only if the user wants the repository version; otherwise leave it absent.
- Verify Pi-hole resolution through the restored upstream before declaring rollback complete.

## Test and Acceptance Matrix

- Package provenance: signature, checksum, `.buildinfo`, version, architecture, and dependencies validate.
- Upgrade: Debian 1.17.1 upgrades to 1.25.1 without losing the existing `pihole.conf`, local records, trust anchor, AppArmor rules, or service enablement.
- Configuration: `unbound-checkconf` succeeds and all enabled directives are supported by 1.25.1.
- Networking: only loopback port 5335 accepts client queries; outbound transport matches each scenario—Cloudflare TCP 853 for HA, authoritative UDP/TCP 53 for the clean recursive target.
- DNSSEC: a valid test domain returns `NOERROR` with `AD`; a deliberately broken domain returns `SERVFAIL`.
- Local DNS: HA A, PTR, and SRV records resolve directly, through each Pi-hole node, and through the VIP.
- Pi-hole integration: v5 and v6 logs show forwarding to local Unbound, with no public upstream selected in Pi-hole.
- Operations: service restart, reload, log rotation, trust-anchor update, package reinstall, and reboot all succeed.
- HA: client resolution survives failover and failback.
- Clean target: installation and rollback both complete without package prompts, orphaned listeners, or unintended changes to Pi-hole and host networking.

## Assumptions

- Both HA nodes run Debian 12 arm64, Pi-hole v5, keepalived, and Debian’s current Bookworm Unbound package.
- The clean target runs Debian 12 arm64 on a Raspberry Pi 5, with Pi-hole v6 installed separately.
- Native IPv4 and IPv6 connectivity is reliable on all targets.
- The existing HA `pihole.conf` is the authoritative site configuration and intentionally uses Cloudflare DoT.
- The clean Pi-hole v6 target intentionally uses full recursive resolution.
- A dedicated GPG release-signing key is available and its private material remains outside the repository and build artifacts.

## Implementation documentation

- [Documentation index](INDEX.md)
- [Build and release procedure](build-and-release.md)
- [Scenario 1: Pi-hole v5 HA upgrade](scenario-1-ha-upgrade-installation.md)
- [Scenario 2: clean Pi-hole v6 target](scenario-2-clean-installation.md)
- [Test and acceptance matrix](acceptance-matrix.md)
