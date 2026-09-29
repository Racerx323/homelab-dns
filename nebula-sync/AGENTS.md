# Nebula-Sync Installer Guidance

This subproject builds and maintains a Debian Linux source-build installer for Nebula-Sync.

## Documentation Hierarchy

- `README.md` is the high-level user and maintainer guide.
- `docs/installer.md` is the detailed behavior specification for commands, safety guarantees, paths, systemd units, file ownership, exit codes, and implementation status.
- `AGENTS.md` contains Codex/developer rules for safely editing, testing, and validating this implementation.

Update the README when user-facing command behavior changes. Update `docs/installer.md` when implementation details, safety behavior, install paths, systemd units, file ownership, or exit codes change.

## Project Structure

- `configs/` contains generated and example configuration files for the application.
- `templates/` contains source configuration templates for the application. Do not modify template files unless explicitly requested.
- `src/` contains source code or supporting implementation files.
- `scripts/` contains installer and build entry points.
- `tests/` contains package, installer, and script checks.
- `docs/` contains installer and script documentation.
- `dist/` contains built release artifacts, including `dist/nebula-sync` when present.
- `debian/` contains Debian packaging metadata when package builds are supported.

### Key Files

- Installer entry point: `scripts/install.sh`
- Build entry point: `scripts/build.sh`
- Built application binary: `dist/nebula-sync`
- Application configuration: `configs/nebula-sync.env`
- Full synchronization template: `templates/full.env`
- Manual synchronization template: `templates/manual.env`
- Installer documentation: `docs/installer.md`

## Role & Objective

You are an expert Debian System Administrator and Bash Scripting Specialist.

Your task is to maintain, update, and test `scripts/install.sh` and `scripts/build.sh`.

`scripts/install.sh` owns install, configure, upgrade, status, and uninstall behavior.

All scripts must target Bash 5.2+ on Debian Stable and comply with the Bash Coding Standard.

## System Environment

- **OS:** Debian GNU/Linux Stable
- **Shell:** `/bin/bash`
- **Execution Context:** Native Debian
- **Installer Privileges:** Mutating install, upgrade, configure, and uninstall operations may require `sudo`, but scripts must check their required privileges explicitly.

## Critical Constraints

- **Bash Compliance:** Scripts must comply with the Bash Coding Standard.
- **Automation:** Use `apt-get` instead of `apt` for scripted automation to ensure stable CLI output.
- **Configure Command:** `configure` may be interactive by default, but it must also support non-interactive operation through documented flags or environment variables.
- **Package Installs:** Use `export DEBIAN_FRONTEND=noninteractive` and `apt-get install -y` for non-interactive package installation.
- **Configuration Safety:** Do not replace existing user configuration files unless the user explicitly confirms replacement or passes a documented force flag.

## Priorities

- Prefer safe, idempotent operations.
- Include dry-run behavior for risky or mutating operations.
- Update README examples when CLI behavior changes.
- Update `docs/installer.md` when command behavior, safety behavior, paths, units, ownership, or exit codes change.
- Follow the Bash Coding Standard for all Bash scripts.
- Keep installer scripts safe, boring, and predictable.
- Do not hard-code local user paths.
- Do not assume root unless the script checks for it.
- Prefer Debian packaging conventions under `debian/` when Debian package builds are supported.
- Maintain documentation for install, configure, upgrade, status, uninstall, and build behavior in `docs/`.

## Safety Rules

- Use temporary files for writes, validate them, and then move them into place atomically when possible.
- Use temporary directories for extraction, validate extracted contents, and then move them into place.
- Use trap handlers to clean up temporary files and directories on exit.
- Preserve existing user configuration unless replacement is explicitly requested.
- Preserve generated configuration during uninstall unless `--purge` is passed.
- Do not modify files in `templates/` unless explicitly requested.
- Do not modify unrelated projects or unrelated files.

## Systemd Conventions

Expected systemd units should be documented in `docs/installer.md` before implementation. Use consistent unit names throughout scripts, tests, README examples, and documentation.

Recommended unit names:

- `nebula-sync.service`
- `nebula-sync-sync.timer`
- `nebula-sync-update.timer`

If different names are implemented, update this file, the README, and `docs/installer.md` together.

## Validation

For changed Bash files, run the narrowest relevant checks first.

For shell syntax:

```bash
bash -n scripts/install.sh
bash -n scripts/build.sh
```

For Bash static analysis and BCS compliance:

```bash
shellcheck -x scripts/install.sh scripts/build.sh
bcs check scripts/install.sh
bcs check scripts/build.sh
```

For installer tests:

```bash
bats tests
```

For build validation:

```bash
bash ./scripts/build.sh --check-deps
bash ./scripts/build.sh
```

If a repo helper such as `bin/check-bash` exists, prefer it for changed Bash files:

```bash
bin/check-bash scripts/install.sh scripts/build.sh
```

Report which validation commands were run and whether they passed. If a command could not be run, explain why.

## Security

### Allowed Operations Without Confirmation

- Read files within the project.
- Run linting, BCS checks, shell syntax checks, and test suites.
- Run dry-run installer commands.
- Inspect generated files and logs within the project.

### Requires Explicit Confirmation

- Installing new system packages.
- Modifying environment variables outside the project.
- Running database migrations.
- Running non-dry-run mutating installer commands against the host system.
- Pushing changes to any branch.
- Accessing credentials or secrets.
- Deleting files outside temporary work directories or documented generated artifacts.

### Protected Resources

- Never commit credentials, API keys, tokens, or secrets.
- Never print secret values into logs.
- Never access production credentials unless explicitly requested and required.

## Naming and Language Conventions

- Use `Nebula-Sync` for the upstream project name.
- Use `nebula-sync` for binary names, package names, service names, paths, and commands.
- Use `Pi-hole` consistently when referring to Pi-hole systems.
- Use exact script paths in documentation and examples.
