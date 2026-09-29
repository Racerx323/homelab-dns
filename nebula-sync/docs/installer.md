# Nebula-Sync Installer

This installer is a Bash 5+ command dispatcher for Debian systems. It currently
scaffolds the source-build lifecycle for Nebula-Sync while keeping mutating
operations predictable and reviewable.

## Entry Points

- `scripts/install.sh` is the primary command dispatcher.
- `scripts/uninstall.sh` is a compatibility wrapper for
  `scripts/install.sh uninstall`.
- `scripts/build.sh` downloads and builds an upstream Nebula-Sync release.

## Build Workflow

Build the latest upstream release:

```bash
bash ./scripts/build.sh
```

Build a pinned release:

```bash
bash ./scripts/build.sh --version v0.11.2
```

Check or install Debian build dependencies:

```bash
bash ./scripts/build.sh --check-deps
sudo bash ./scripts/build.sh --install-deps
```

As of June 25, 2026, the latest upstream GitHub release is `v0.11.2`. The
default `latest` value is resolved at runtime from the GitHub latest-release
redirect, so future releases do not require an installer change.

The build script downloads the release tarball to a temporary file, validates
the archive, extracts it into a temporary directory, validates the extracted Go
module, replaces the release work directory, compiles with `go build -trimpath`,
writes artifacts under `dist/nebula-sync-<version>-<goos>-<goarch>/`, and
refreshes `dist/nebula-sync` for installer consumption.

By default, `build.sh` detects the host hardware with `uname` and targets the
local platform. On amd64 systems, it also checks `/proc/cpuinfo` and applies a
native `GOAMD64` level when the CPU advertises the required instruction flags.
Use `--generic` to skip CPU-specific tuning and produce a more portable amd64
binary. Cross-builds can still be requested with `--goos` and `--goarch`.
The `--clean` option remains accepted for older automation, but release
extraction is now clean by default.

## Commands

```bash
sudo bash ./scripts/install.sh install
sudo bash ./scripts/install.sh configure
sudo bash ./scripts/install.sh upgrade
bash ./scripts/install.sh status
sudo bash ./scripts/install.sh uninstall --force
sudo bash ./scripts/install.sh uninstall --force --purge
```

`install` installs required Debian packages, copies installer-owned files,
copies missing configuration templates, writes systemd units, reloads systemd,
and enables the timer. It fails unless `dist/nebula-sync` exists, so run
`scripts/build.sh` first.

`configure` prompts for a full or manual sync, uses the matching template as a
starting point, prompts for the primary connection string, prompts for the
number of replicas, prompts for each replica connection string, writes the
selected `full.env` or `manual.env` through a temporary file, validates the
generated env values, moves it into the configuration directory, and refreshes
the active `nebula-sync.env` consumed by systemd. The routine also detects the
target system timezone with `timedatectl`, `/etc/timezone`, or `/etc/localtime`
and writes `TZ=<timezone>` into the generated env file.

`upgrade` refreshes installer-owned files and systemd units. It does not copy
configuration templates, so existing local configuration is preserved.

`status` prints the selected install, config, and systemd paths, then reports
the timer status when `systemctl` is available.

`uninstall --force` disables the timer, removes generated systemd units, reloads
systemd, and removes the install directory. It preserves configuration by
default.

`uninstall --force --purge` also removes the generated configuration directory.

## Dry Run

Use `--dry-run` to preview mutating commands without root:

```bash
bash ./scripts/build.sh --dry-run
bash ./scripts/build.sh --dry-run --install-deps
bash ./scripts/install.sh --dry-run install
bash ./scripts/install.sh --dry-run configure
bash ./scripts/install.sh --dry-run upgrade
bash ./scripts/install.sh --dry-run uninstall --force --purge
```

Dry-run output prints each command with a `[dry-run]` prefix. Compound operations
that require shell features, such as heredoc-based unit writes, are printed as
plain action descriptions.

## Path Overrides

The installer supports path overrides for development and packaging tests:

```bash
bash ./scripts/install.sh --dry-run \
  --install-dir /tmp/nebula-sync/opt \
  --config-dir /tmp/nebula-sync/etc \
  --systemd-dir /tmp/nebula-sync/systemd \
  install
```

Empty paths and `/` are rejected before dispatch. Destructive uninstall commands
also use shell parameter guards as a final defense.

## Safety Model

- `set -euo pipefail` is enabled in every shell entry point.
- `apt-get` is used with `DEBIAN_FRONTEND=noninteractive`.
- Build dependency installation only runs when `--install-deps` is supplied.
- Mutating commands require root unless `--dry-run` is set.
- Existing `.env` files under the config directory are preserved.
- Install fails before writing systemd units when the built binary is missing.
- Generated configuration files are written as temporary files, validated, then
  moved into place.
- Systemd units are generated as temporary files, validated, then moved into
  place.
- Uninstall requires `--force`.
- Config removal requires both `--force` and `--purge`.
- Systemd cleanup is best-effort so missing units do not block file removal.

## Current Limitations

- Debian package checks such as `lintian` apply only after package artifacts are
  produced.
