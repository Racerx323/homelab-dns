# 🏗️ Unbound 1.25.1 Build and Release

This procedure produces the maintained Debian 12 arm64 backport and the
separate Pi-hole profile package. It never resolves a latest version: all
source and output versions are pinned in
[`../packaging/release.env`](../packaging/release.env).

This procedure implements the shared build and release foundation in the
[Unbound 1.25.1 scenario requirements](unbound-1.25-requirements.md).

## Build host

Use a fully updated native Debian 12 arm64 host dedicated to package builds.
Install `sbuild`, `schroot`, `devscripts`, `debian-keyring`, `debhelper`,
`lintian`, `autopkgtest`, `shellcheck`, `shfmt`, `gpg`, and normal Debian
packaging tools. Create and update the clean `bookworm-arm64-sbuild` chroot
according to Debian's sbuild documentation.

Do not cross-build this release. The scripts reject a non-Bookworm or
non-arm64 host and ask sbuild to update and dist-upgrade the isolated chroot
before every build.

## Authenticate and build

```bash
sudo Unbound/scripts/build-backport.sh
sudo Unbound/scripts/build-profile.sh
Unbound/tests/run.sh
```

`build-backport.sh` downloads the exact Debian `unbound_1.25.1-1.dsc`, verifies
its Debian signature and signed source-file hashes, adds only the
`1.25.1-1~bookworm1` changelog entry, and builds it in sbuild. Upstream and
Debian tests run during the package build; lintian and autopkgtest run before
the artifacts are accepted.

The profile is an independent Debian source package. Its managed
`/etc/unbound/unbound.conf.d/pihole.conf` is a normal conffile, so profile
configuration and application binaries can evolve separately. It has no
maintainer scripts and therefore cannot alter Pi-hole, Keepalived, firewall,
resolver, or network configuration.

Before signing, copy the candidate `.deb` files to a disposable Debian 12
arm64 target with neither Pi-hole nor Keepalived installed. Run the destructive
lifecycle test there and retain its complete transcript:

```bash
sudo Unbound/scripts/package-lifecycle-test.sh ./candidate-packages \
  2>&1 | tee package-lifecycle-results.txt
```

## Inspect and sign the release

Use a dedicated release key whose private material is outside the repository
and build directories. Supply its complete fingerprint:

```bash
export SIGNING_KEY='<40-character GPG fingerprint>'
export LIFECYCLE_RESULTS="$PWD/package-lifecycle-results.txt"
Unbound/scripts/create-release-bundle.sh
```

The release command rejects wrong versions or architectures, requires the
runtime package closure and profile, inspects every package payload, executes
the packaged arm64 `unbound -V`, and requires these features:

- systemd and Debian filesystem integration;
- libevent and libnghttp2;
- Python module and bindings package;
- EDNS Client Subnet and DNSTAP;
- TCP Fast Open client and server support.

The signed bundle contains arm64 and architecture-independent binaries,
source files, signed `.dsc`/`.changes`, `.buildinfo`, package inventories,
test results, runbooks, `SHA256SUMS`, and `SHA256SUMS.asc`.

Verify it from a separately trusted public key before copying it to a node:

```bash
Unbound/scripts/verify-release.sh \
  Unbound/packaging/release/unbound-1.25.1-1~bookworm1
```

## Reproducibility and clean lifecycle tests

Before approval, repeat the build on a fresh builder and compare `.buildinfo`
and binary package contents. Exercise these paths in disposable Debian 12
arm64 targets:

1. clean install of the Unbound closure and profile;
2. upgrade from the current Bookworm 1.17.1 package set while preserving all
   Unbound conffiles and service enablement;
3. reinstall of every package;
4. reload, restart, trust-anchor update, log reopening, and reboot;
5. package removal without prompts or orphaned listeners;
6. rollback to cached Bookworm packages and matching configuration.

Attach the command transcript and results to the release approval. The live
HA and Pi-hole checks remain manual because they require the real VIP, local
zone, and Pi-hole state.

## Security maintenance

This backport is an internally maintained security product. Subscribe to NLnet
Labs release/security announcements and Debian Security Tracker updates for
`unbound`. A newer upstream or Debian revision is never consumed
automatically: update the pinned version, review Debian packaging changes,
rebuild from a clean chroot, run the complete regression matrix, sign a new
bundle, and deploy it through a fresh rolling maintenance action.
