# nebula-sync Maintainer

This folder contains source files, installer scripts, tests, and documentation for a Debian source-build installer of Nebula-Sync.

## Application Information

- Application Name: `nebula-sync`
- Application Description: Nebula-Sync is a tool to synchronize Pi-hole configurations across multiple devices.
- Application GitHub Repository: [Nebula-Sync](https://github.com/lovelaze/nebula-sync)
- Application Latest Release Download: [Nebula-Sync Release](https://github.com/lovelaze/nebula-sync/releases/latest)
- Application Configuration File Templates:
  - Full Synchronization: [full.env](templates/full.env)
  - Manual Synchronization: [manual.env](templates/manual.env)

## Repository Structure

- `configs/` contains generated and example configuration files.
- `templates/` contains source configuration templates. Do not modify these during normal installer runs.
- `src/` contains source code or supporting implementation files.
- `scripts/` contains installer and build entry points.
- `tests/` contains package, installer, and script checks.
- `docs/` contains installer and script documentation.
- `dist/` contains built release artifacts, including `dist/nebula-sync` after a successful build.
- `debian/` contains Debian packaging metadata when package builds are supported.

## Installer Responsibilities

### Application Lifecycle

- Install required Debian packages.
- Build or consume the `dist/nebula-sync` binary.
- Install application files.
- Update application files.
- Support install, configure, upgrade, status, and uninstall behavior.
- Include a version control mechanism for installer-managed application files.

### Configuration

- Install application configuration files.
- Update application configuration files only through documented commands.
- Preserve existing configuration unless replacement is explicitly requested.
- Support full and manual synchronization configuration templates.
- Do not modify files in the `templates/` directory during normal installer runs.

### Systemd

- Create and manage the `nebula-sync.service` systemd service.
- Create and manage the `nebula-sync-sync.timer` timer for Pi-hole peer synchronization.
- Create and manage the `nebula-sync-update.timer` timer for nebula-sync application auto-update.
- Keep systemd unit names consistent across scripts, tests, README examples, and `docs/installer.md`.

### Safety and Reliability

- Provide dry-run mode for mutating commands.
- Produce clear logs.
- Include robust error handling.
- Include useful comments and documentation for non-obvious behavior.
- Require explicit flags for destructive actions.
- Write to a temporary file first, validate it, and then move it into place to avoid partial writes.
- Extract archives to a temporary directory first, validate them, and then move them into place to avoid partial writes.
- Include trap handlers to clean up temporary files and directories on exit.

## Safety Guarantees

- Dry-run mode previews mutating behavior without changing the host system.
- Uninstall preserves generated configuration unless `--purge` is passed.
- Destructive operations require explicit flags such as `--force` or `--purge`.
- Existing user configuration is not replaced unless the user explicitly requests replacement or passes a documented force flag.
- Template files are treated as source inputs and are not modified by installer commands.

## Build Commands

Build the latest upstream Nebula-Sync release first:

```bash
bash ./scripts/build.sh
```

The installer requires the built binary at `dist/nebula-sync` and fails early if it is missing.

If build dependencies are missing on Debian, inspect or install them explicitly:

```bash
bash ./scripts/build.sh --check-deps
sudo bash ./scripts/build.sh --install-deps
```

## Installer Commands

Run the installer entry point from this repository:

```bash
sudo bash ./scripts/install.sh install
```

Supported commands:

- `install`: installs required Debian packages, application files, configuration templates, and systemd units.
- `configure`: prompts for full/manual sync and writes a validated `.env` configuration with the target timezone.
- `upgrade`: refreshes application files and systemd units without replacing existing configuration.
- `status`: prints install paths and systemd service/timer status.
- `uninstall --force`: disables units and removes application files while preserving generated configuration.
- `uninstall --force --purge`: disables units, removes application files, and removes generated configuration files.

Preview any mutating command with dry-run mode:

```bash
bash ./scripts/install.sh --dry-run install
bash ./scripts/install.sh --dry-run configure
bash ./scripts/install.sh --dry-run uninstall --force --purge
```

### Non-interactive Configure

The `configure` command may be interactive by default, but it should also support a documented non-interactive mode through flags or environment variables.

Recommended future pattern:

```bash
sudo bash ./scripts/install.sh configure \
  --mode full \
  --timezone America/Chicago
```

## Validation Commands

For shell syntax checks:

```bash
bash -n scripts/install.sh
bash -n scripts/build.sh
```

For Bash static analysis:

```bash
shellcheck -x scripts/install.sh scripts/build.sh
```

For tests:

```bash
bats tests
```

If a repo helper such as `bin/check-bash` exists, prefer it for changed Bash files:

```bash
bin/check-bash scripts/install.sh scripts/build.sh
```

## Documentation

For command behavior, safety guarantees, install paths, systemd units, file ownership, exit codes, and current implementation status, see [docs/installer.md](docs/installer.md).

Update documentation when user-facing behavior, command flags, generated files, systemd units, or safety guarantees change.
