# ✅ Unbound Test and Acceptance Matrix

Record a dated pass/fail result and evidence location for every row. Run the
repository checks first, then the matching target acceptance command:

```bash
Unbound/tests/run.sh
sudo Unbound/scripts/acceptance.sh ha 10.1.0.55
sudo Unbound/scripts/acceptance.sh v6
```

| Area | Required evidence | Gate |
| --- | --- | --- |
| Provenance | Trusted detached signature, all SHA-256 checks pass, source `.dsc`, `.changes`, `.buildinfo`, exact version, arm64/all architecture, resolved dependencies | Automated by `verify-release.sh`; reviewer confirms trusted key |
| Build | Clean updated Bookworm arm64 sbuild, upstream/Debian tests, lintian, autopkgtest, required `unbound -V` features | Recorded in bundle manifest and CI transcript |
| Upgrade | 1.17.1 package set upgrades without changing `pihole.conf`, local records, trust anchor, AppArmor local rules, overrides, or service enablement | `package-lifecycle-test.sh` plus HA preflight hashes |
| Configuration | `unbound-checkconf` succeeds with old and new binary; warnings reviewed separately | Preflight and acceptance scripts |
| Listeners | UDP/TCP 5335 is loopback-only | Automated by `acceptance.sh` |
| HA transport | Configured Cloudflare IPv4 and IPv6 endpoints accept TCP 853 | Automated by `ha-preflight.sh` |
| Recursive transport | Real root server answers authoritative UDP/TCP 53 without interception | Automated by `v6-preflight.sh` |
| DNSSEC | Valid domain is `NOERROR` with `AD`; deliberately broken domain is `SERVFAIL` | Automated by `acceptance.sh` |
| Local DNS | HA A, PTR, and SRV queries pass directly and through VIP | Automated with documented site test records |
| Pi-hole | v5 forwards to local 5335; v6 contains only local Unbound upstreams and Pi-hole DNSSEC is off | Script plus Pi-hole log review |
| Operations | Trust-anchor update, reload, restart, log reopen when file logging is used, reinstall, rotation, reboot | Release transcript and node journal |
| HA | Client resolution survives failover and failback; preferred owner returns | Manual rolling-runbook gate |
| Rollback | Pi-hole upstream restored before Unbound removal; cached downgrade works one node at a time | Disposable test and runbook rehearsal |
| Removal | No prompts, orphaned 5335 listener, or unintended Pi-hole/host-network changes | Disposable clean-target test |

Any failed row blocks promotion. Performance warnings do not authorize changes
to the existing HA cache, threads, logging, local-zone, or forwarding policy.
