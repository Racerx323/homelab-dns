#!/usr/bin/env bash

set -euo pipefail

# install.sh is the single command dispatcher for the source-build installer.
# It is intentionally conservative: mutating commands support dry-run output,
# root-only operations are checked at command execution time, and uninstall
# keeps user configuration unless --purge is explicitly supplied.
readonly PROGRAM_NAME="${0##*/}"
readonly APP_NAME="nebula-sync"
readonly ACTIVE_CONFIG_FILE="${APP_NAME}.env"
readonly DEFAULT_INSTALL_DIR="/opt/nebula-sync"
readonly DEFAULT_CONFIG_DIR="/etc/nebula-sync"
readonly DEFAULT_SYSTEMD_DIR="/etc/systemd/system"

# Parsed command state. These globals are assigned only by parse_arguments and
# validated before dispatch so each command function can stay small and direct.
command_name=""
dry_run=false
force=false
purge=false
install_dir="${DEFAULT_INSTALL_DIR}"
config_dir="${DEFAULT_CONFIG_DIR}"
systemd_dir="${DEFAULT_SYSTEMD_DIR}"

usage() {
  cat <<USAGE
Usage:
  ${PROGRAM_NAME} [global-options] <command> [command-options]

Commands:
  install       Install packages, app files, config templates, and systemd units.
  configure     Create an active .env configuration from a template.
  upgrade       Refresh app files and systemd units without replacing config.
  status        Show installation paths and service status.
  uninstall     Disable installed units and remove app files.
  help          Show this help text.

Global options:
  -n, --dry-run           Print actions without changing the system.
      --install-dir PATH  Installation directory. Default: /opt/nebula-sync
      --config-dir PATH   Configuration directory. Default: /etc/nebula-sync
      --systemd-dir PATH  systemd unit directory. Default: /etc/systemd/system
  -h, --help              Show this help text.

Uninstall options:
      --force             Required for uninstall actions.
      --purge             With --force, also remove generated config files.
USAGE
}

# Emit one line to stdout. Keeping logging small makes dry-run output easy to
# read in terminals and test assertions.
log() {
  printf '%s\n' "$*"
}

# Print a fatal error in a consistent format before exiting non-zero.
die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

# Resolve the repository root from the script path instead of the caller's
# working directory. This keeps template and source lookups stable under sudo.
repository_root() {
  local script_dir

  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  cd -- "${script_dir}/.." && pwd
}

# Mutating commands require root in normal mode. Dry-run mode is allowed for
# unprivileged users because it only prints the operations that would run.
require_root() {
  if [[ "${dry_run}" == "true" ]]; then
    return 0
  fi

  if [[ "${EUID}" -ne 0 ]]; then
    die "this command must be run with sudo or as root"
  fi
}

# Run a command normally, or print a shell-escaped preview in dry-run mode.
# Arguments are never joined into a string for execution.
run_cmd() {
  if [[ "${dry_run}" == "true" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi

  "$@"
}

# Run best-effort cleanup commands. Missing systemd units should not make an
# uninstall fail before files can be removed.
run_optional_cmd() {
  if [[ "${dry_run}" == "true" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi

  if ! "$@"; then
    log "Optional command failed; continuing: $*"
  fi
}

# Describe compound shell operations in dry-run mode. This is used only where
# the real operation needs shell features such as a heredoc or recursive copy.
run_shell() {
  local description=$1
  shift

  if [[ "${dry_run}" == "true" ]]; then
    printf '[dry-run] %s\n' "${description}"
    return 0
  fi

  "$@"
}

# Move a completed temporary file into its final location. The temp file must be
# in the same filesystem as the target so mv(1) replaces atomically.
move_file_into_place() {
  local source_file=$1
  local target_file=$2
  local mode=$3

  run_cmd chmod "${mode}" "${source_file}"
  run_cmd mv -f -- "${source_file}" "${target_file}"
}

# Create a directory with a specific mode through install(1), giving predictable
# permissions on Debian and producing a clear dry-run preview.
ensure_directory() {
  local path=$1
  local mode=$2

  run_cmd install -d -m "${mode}" "${path}"
}

# Install the minimal Debian packages needed by the current scaffold. apt-get is
# used instead of apt because the installer is intended for scripted automation.
install_required_packages() {
  run_cmd env DEBIAN_FRONTEND=noninteractive apt-get update
  run_cmd env DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates \
    curl \
    git \
    systemd
}

# Place installer-owned application files under the selected install directory.
# Existing configuration is handled separately and is never overwritten here.
install_app_files() {
  local root_dir=$1
  local built_binary="${root_dir}/dist/${APP_NAME}"

  [[ -f "${built_binary}" ]] || die "built binary not found: ${built_binary}; run scripts/build.sh first"

  ensure_directory "${install_dir}" "0755"
  run_cmd install -d -m 0755 "${install_dir}/scripts"
  run_cmd install -m 0755 "${root_dir}/scripts/install.sh" "${install_dir}/scripts/install.sh"
  run_cmd install -m 0755 "${built_binary}" "${install_dir}/${APP_NAME}"

  if [[ -d "${root_dir}/src" ]]; then
    run_cmd install -d -m 0755 "${install_dir}/src"
    run_shell "copy source files from ${root_dir}/src to ${install_dir}/src" \
      cp -R "${root_dir}/src/." "${install_dir}/src"
  fi
}

# Copy template environment files only when the target does not already exist.
# This makes repeated installs safe and preserves local Pi-hole credentials.
install_config_templates() {
  local root_dir=$1
  local template_file
  local target_file

  ensure_directory "${config_dir}" "0750"

  for template_file in "${root_dir}/templates/"*.env; do
    [[ -e "${template_file}" ]] || continue

    target_file="${config_dir}/$(basename -- "${template_file}")"
    if [[ -e "${target_file}" ]]; then
      log "Preserving existing config: ${target_file}"
      continue
    fi

    run_cmd install -m 0640 "${template_file}" "${target_file}"
  done
}

prompt_required() {
  local prompt_text=$1
  local value

  while true; do
    if ! read -r -p "${prompt_text}" value; then
      die "input ended while reading required value"
    fi
    if [[ -n "${value}" ]]; then
      printf '%s\n' "${value}"
      return 0
    fi
    log "Value is required."
  done
}

prompt_sync_mode() {
  local value

  while true; do
    if ! read -r -p "Sync type [full/manual]: " value; then
      die "input ended while reading sync type"
    fi
    case "${value,,}" in
      full | f)
        printf 'full\n'
        return 0
        ;;
      manual | m)
        printf 'manual\n'
        return 0
        ;;
      *)
        log "Enter full or manual."
        ;;
    esac
  done
}

prompt_replica_count() {
  local value

  while true; do
    if ! read -r -p "Number of replicas: " value; then
      die "input ended while reading replica count"
    fi
    if [[ "${value}" =~ ^[1-9][0-9]*$ ]]; then
      printf '%s\n' "${value}"
      return 0
    fi
    log "Enter a positive integer."
  done
}

collect_replicas() {
  local replica_count=$1
  local replicas=()
  local index
  local replica

  for ((index = 1; index <= replica_count; index++)); do
    replica="$(prompt_required "Replica ${index} connection string [http://host|password]: ")"
    replicas+=("${replica}")
  done

  local joined=""
  for replica in "${replicas[@]}"; do
    if [[ -z "${joined}" ]]; then
      joined="${replica}"
    else
      joined="${joined},${replica}"
    fi
  done

  printf '%s\n' "${joined}"
}

detect_system_timezone() {
  local timezone_value
  local localtime_target

  if command -v timedatectl >/dev/null 2>&1; then
    timezone_value="$(timedatectl show -p Timezone --value 2>/dev/null || true)"
    if [[ -n "${timezone_value}" ]]; then
      printf '%s\n' "${timezone_value}"
      return 0
    fi
  fi

  if [[ -r /etc/timezone ]]; then
    timezone_value="$(sed -n '1s/[[:space:]]*$//p' /etc/timezone)"
    if [[ -n "${timezone_value}" ]]; then
      printf '%s\n' "${timezone_value}"
      return 0
    fi
  fi

  localtime_target="$(readlink /etc/localtime 2>/dev/null || true)"
  case "${localtime_target}" in
    *zoneinfo/*)
      printf '%s\n' "${localtime_target#*zoneinfo/}"
      return 0
      ;;
  esac

  printf 'UTC\n'
}

# Render a selected template into a concrete env file by replacing only the
# values owned by this configuration routine.
write_config_from_template() {
  local template_file=$1
  local target_file=$2
  local primary_value=$3
  local replicas_value=$4
  local full_sync_value=$5
  local timezone_value=$6
  local line

  while IFS= read -r line || [[ -n "${line}" ]]; do
    case "${line}" in
      PRIMARY=*)
        printf 'PRIMARY=%s\n' "${primary_value}"
        ;;
      REPLICAS=*)
        printf 'REPLICAS=%s\n' "${replicas_value}"
        ;;
      FULL_SYNC=*)
        printf 'FULL_SYNC=%s\n' "${full_sync_value}"
        ;;
      TZ=* | \#TZ=*)
        printf 'TZ=%s\n' "${timezone_value}"
        ;;
      *)
        printf '%s\n' "${line}"
        ;;
    esac
  done <"${template_file}" >"${target_file}"
}

# Validate the generated env file before it can replace the active
# configuration. This catches missing substitutions and invalid sync mode state.
validate_env_file() {
  local env_file=$1
  local required_key

  for required_key in PRIMARY REPLICAS FULL_SYNC TZ; do
    grep -Eq "^${required_key}=[^[:space:]]+$" "${env_file}" || die "generated env file is missing valid ${required_key}: ${env_file}"
  done

  grep -Eq '^FULL_SYNC=(true|false)$' "${env_file}" || die "generated env file has invalid FULL_SYNC: ${env_file}"
  [[ -f "/usr/share/zoneinfo/$(grep -E '^TZ=' "${env_file}" | cut -d '=' -f 2-)" ]] || die "generated env file has invalid TZ: ${env_file}"
}

# Generate configuration into a temp file in config_dir, validate it, then move
# it into place. This mirrors the systemd unit write pattern.
write_config_atomically() {
  local template_file=$1
  local final_file=$2
  local primary_value=$3
  local replicas_value=$4
  local full_sync_value=$5
  local timezone_value=$6
  local temp_file

  if [[ "${dry_run}" == "true" ]]; then
    log "[dry-run] write temp env file for ${final_file}"
    log "[dry-run] validate temp env file for ${final_file}"
    log "[dry-run] move validated temp env file into ${final_file}"
    return 0
  fi

  temp_file="$(mktemp "${config_dir}/.$(basename -- "${final_file}").XXXXXX")"
  {
    write_config_from_template "${template_file}" "${temp_file}" "${primary_value}" "${replicas_value}" "${full_sync_value}" "${timezone_value}"
    validate_env_file "${temp_file}"
    move_file_into_place "${temp_file}" "${final_file}" "0640"
  } || {
    rm -f -- "${temp_file}"
    return 1
  }
}

# Interactive configuration flow. The selected full/manual template is preserved
# as a named env file, and the same validated content is written to
# nebula-sync.env for the systemd service.
configure_env_file() {
  local root_dir=$1
  local sync_mode
  local template_file
  local target_file
  local active_file="${config_dir}/${ACTIVE_CONFIG_FILE}"
  local primary_value
  local replica_count
  local replicas_value
  local full_sync_value
  local timezone_value

  ensure_directory "${config_dir}" "0750"
  timezone_value="$(detect_system_timezone)"

  if [[ "${dry_run}" == "true" ]]; then
    log "[dry-run] detected target timezone: ${timezone_value}"
    log "[dry-run] prompt for sync type, primary, and replica count"
    log "[dry-run] prompt for each replica connection string"
    sync_mode="full"
    primary_value="http://primary.example.com|password"
    replicas_value="http://replica1.example.com|password"
  else
    sync_mode="$(prompt_sync_mode)"
    primary_value="$(prompt_required "Primary connection string [http://host|password]: ")"
    replica_count="$(prompt_replica_count)"
    replicas_value="$(collect_replicas "${replica_count}")"
  fi

  template_file="${root_dir}/templates/${sync_mode}.env"
  target_file="${config_dir}/${sync_mode}.env"
  [[ -f "${template_file}" ]] || die "configuration template not found: ${template_file}"

  if [[ "${sync_mode}" == "full" ]]; then
    full_sync_value="true"
  else
    full_sync_value="false"
  fi

  write_config_atomically "${template_file}" "${target_file}" "${primary_value}" "${replicas_value}" "${full_sync_value}" "${timezone_value}"
  write_config_atomically "${template_file}" "${active_file}" "${primary_value}" "${replicas_value}" "${full_sync_value}" "${timezone_value}"
  log "Configuration written: ${target_file}"
  log "Active configuration written: ${active_file}"
}

write_service_unit() {
  local target_file=$1

  cat >"${target_file}" <<UNIT
[Unit]
Description=Nebula-Sync Pi-hole configuration sync
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
EnvironmentFile=-${config_dir}/${ACTIVE_CONFIG_FILE}
ExecStart=${install_dir}/${APP_NAME}
UNIT
}

write_timer_unit() {
  local target_file=$1

  cat >"${target_file}" <<'UNIT'
[Unit]
Description=Run Nebula-Sync periodically

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
UNIT
}

validate_unit_file() {
  local unit_file=$1
  local required_section=$2

  grep -qx '\[Unit\]' "${unit_file}" || die "generated unit is missing [Unit]: ${unit_file}"
  grep -qx "\\[${required_section}\\]" "${unit_file}" || die "generated unit is missing [${required_section}]: ${unit_file}"
}

write_unit_atomically() {
  local unit_name=$1
  local required_section=$2
  local final_file="${systemd_dir}/${unit_name}"
  local temp_file

  if [[ "${dry_run}" == "true" ]]; then
    log "[dry-run] write temp unit for ${final_file}"
    log "[dry-run] validate temp unit for ${final_file}"
    log "[dry-run] move validated temp unit into ${final_file}"
    return 0
  fi

  temp_file="$(mktemp "${systemd_dir}/.${unit_name}.XXXXXX")"
  {
    if [[ "${unit_name}" == "${APP_NAME}.service" ]]; then
      write_service_unit "${temp_file}"
    else
      write_timer_unit "${temp_file}"
    fi
    validate_unit_file "${temp_file}" "${required_section}"
    move_file_into_place "${temp_file}" "${final_file}" "0644"
  } || {
    rm -f -- "${temp_file}"
    return 1
  }
}

# Write systemd units through temporary files and validate required sections
# before replacing the final unit paths.
install_systemd_units() {
  ensure_directory "${systemd_dir}" "0755"

  write_unit_atomically "${APP_NAME}.service" "Service"
  write_unit_atomically "${APP_NAME}.timer" "Timer"

  run_cmd systemctl daemon-reload
  run_cmd systemctl enable "${APP_NAME}.timer"
}

# Full install path: packages, app files, first-run config templates, then units.
command_install() {
  local root_dir

  root_dir="$(repository_root)"
  require_root
  install_required_packages
  install_app_files "${root_dir}"
  install_config_templates "${root_dir}"
  install_systemd_units
  log "Install command completed."
}

command_configure() {
  local root_dir

  root_dir="$(repository_root)"
  require_root
  configure_env_file "${root_dir}"
  log "Configure command completed."
}

# Upgrade intentionally avoids config templates so local settings survive.
command_upgrade() {
  local root_dir

  root_dir="$(repository_root)"
  require_root
  install_app_files "${root_dir}"
  install_systemd_units
  log "Upgrade command completed."
}

# Status is read-only and works without root. systemctl failures are tolerated
# because development hosts may not run systemd.
command_status() {
  log "Application: ${APP_NAME}"
  log "Install directory: ${install_dir}"
  log "Config directory: ${config_dir}"
  log "systemd directory: ${systemd_dir}"

  if command -v systemctl >/dev/null 2>&1; then
    systemctl --no-pager status "${APP_NAME}.timer" || true
  else
    log "systemctl is not available on this system."
  fi
}

# Uninstall is destructive enough to require --force. Configuration survives by
# default; --purge is the explicit opt-in for removing generated config files.
command_uninstall() {
  require_root

  if [[ "${force}" != "true" ]]; then
    die "uninstall requires --force; use --dry-run --force to preview"
  fi

  run_optional_cmd systemctl disable --now "${APP_NAME}.timer"
  run_cmd rm -f "${systemd_dir}/${APP_NAME}.timer" "${systemd_dir}/${APP_NAME}.service"
  run_optional_cmd systemctl daemon-reload
  run_cmd rm -rf -- "${install_dir:?}"

  if [[ "${purge}" == "true" ]]; then
    run_cmd rm -rf -- "${config_dir:?}"
  else
    log "Preserving config directory: ${config_dir}"
  fi

  log "Uninstall command completed."
}

# Parse global options and the single command name. Command-specific flags are
# accepted globally for a simple first-pass CLI.
parse_arguments() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      -n | --dry-run)
        dry_run=true
        ;;
      --force)
        force=true
        ;;
      --purge)
        purge=true
        ;;
      --install-dir)
        shift
        [[ $# -gt 0 ]] || die "--install-dir requires a path"
        install_dir=$1
        ;;
      --config-dir)
        shift
        [[ $# -gt 0 ]] || die "--config-dir requires a path"
        config_dir=$1
        ;;
      --systemd-dir)
        shift
        [[ $# -gt 0 ]] || die "--systemd-dir requires a path"
        systemd_dir=$1
        ;;
      -h | --help)
        command_name="help"
        ;;
      install | configure | upgrade | status | uninstall | help)
        [[ -z "${command_name}" ]] || die "only one command may be specified"
        command_name=$1
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
    shift
  done
}

# Guard path options before any command dispatch. The ${var:?} protections near
# rm still remain as a final defense for destructive operations.
validate_configuration() {
  [[ -n "${install_dir}" ]] || die "--install-dir must not be empty"
  [[ -n "${config_dir}" ]] || die "--config-dir must not be empty"
  [[ -n "${systemd_dir}" ]] || die "--systemd-dir must not be empty"
  [[ "${install_dir}" != "/" ]] || die "--install-dir must not be /"
  [[ "${config_dir}" != "/" ]] || die "--config-dir must not be /"
  [[ "${systemd_dir}" != "/" ]] || die "--systemd-dir must not be /"
}

# Main dispatch defaults to help so running the script without arguments is
# informational rather than surprising.
main() {
  parse_arguments "$@"
  validate_configuration

  case "${command_name:-help}" in
    install)
      command_install
      ;;
    configure)
      command_configure
      ;;
    upgrade)
      command_upgrade
      ;;
    status)
      command_status
      ;;
    uninstall)
      command_uninstall
      ;;
    help)
      usage
      ;;
    *)
      die "unknown command: ${command_name}"
      ;;
  esac
}

main "$@"
