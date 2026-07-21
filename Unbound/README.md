# 📚 Unbound on Debian 12 Raspberry Pi 5

This project documents and configures Unbound for Pi-hole on Debian 12 arm64.
It covers both the existing Pi-hole v5 high-availability deployment and a
clean, single-node Pi-hole v6 reference installation.

Start with the [Unbound documentation index](docs/INDEX.md).

## 🏗️ Packaging and deployment automation

The repository pins Debian's Unbound `1.25.1-1` source and produces the exact
Bookworm backport version `1.25.1-1~bookworm1`. Build and release inputs live
under [`packaging`](packaging), while executable preflight, deployment,
rollback, and acceptance gates live under [`scripts`](scripts).

On a native Debian 12 arm64 build host with a clean `sbuild` chroot:

```bash
sudo Unbound/scripts/build-backport.sh
sudo Unbound/scripts/build-profile.sh
Unbound/tests/run.sh
sudo Unbound/scripts/package-lifecycle-test.sh ./candidate-packages \
  2>&1 | tee package-lifecycle-results.txt
SIGNING_KEY='<full GPG fingerprint>' \
  LIFECYCLE_RESULTS="$PWD/package-lifecycle-results.txt" \
  Unbound/scripts/create-release-bundle.sh
```

Signing keys are never stored in this repository. A release is deployable only
after the signed bundle, manifest, package closure, and acceptance evidence
have been reviewed.

## 🧱 Architecture and drift tracking

The canonical architecture model is maintained in the separate
`homelab-docs/architecture/likec4` project. Published diagram images in this
repository are generated from that model and carry provenance metadata under
`docs/assets/likec4`.

The advisory `Architecture Drift Check` pull-request workflow compares this
repository with that canonical model through Erode.

Local verification from this repository uses:

```bash
erode-drift --branch main
```
