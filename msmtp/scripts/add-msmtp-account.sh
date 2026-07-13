#!/usr/bin/env bash

# Add a password-authenticated msmtp account on Debian 12 while keeping the
# password outside /etc/msmtprc.

set -Eeuo pipefail
IFS=$'\n\t'

readonly PROGRAM_NAME="${0##*/}"
readonly DEFAULT_CONFIG_FILE="/etc/msmtprc"
readonly DEFAULT_SECRET_GROUP="msmtp-secrets"

CONFIG_FILE="${DEFAULT_CONFIG_FILE}"
SECRET_FILE=""
SECRET_GROUP="${DEFAULT_SECRET_GROUP}"
ACCOUNT_NAME=""
SMTP_HOST=""
SMTP_PORT=""
FROM_ADDRESS=""
SMTP_USER=""
TLS_MODE=""
ROOT_ONLY=false
declare -a AUTHORIZED_USERS=()

CONFIG_TEMP=""
SECRET_TEMP=""
PASSWORD=""
PASSWORD_CONFIRM=""

usage() {
  cat <<'EOF'
Usage:
  sudo add-msmtp-account.sh [options]

Adds a password-authenticated msmtp account on Debian 12. Missing account
details are prompted for interactively. The password is always prompted for
twice through /dev/tty and stored outside msmtprc.

Options:
  --account NAME       msmtp account name
  --host HOST          SMTP server hostname or address
  --port PORT          SMTP server port (default: 587 or 465 by TLS mode)
  --from ADDRESS       Envelope-from email address
  --username USER      SMTP authentication username (default: from address)
  --tls-mode MODE      starttls or implicit (default: starttls)
  --config PATH        Configuration file (default: /etc/msmtprc)
  --secret-file PATH   Password file (default:
                       /etc/msmtp/secrets/ACCOUNT-password)
  --group NAME         Secret-reader group (default: msmtp-secrets)
  --service-user USER  Authorize USER to read the secret; repeat as needed
  --root-only          Restrict the password to root instead of using a group
  -h, --help           Show this help

If neither --service-user nor --root-only is specified, the non-root
SUDO_USER is authorized. Passwords over an unencrypted SMTP connection are not
supported.

Examples:
  sudo ./add-msmtp-account.sh

  sudo ./add-msmtp-account.sh \
    --account mailgun \
    --host smtp.mailgun.org \
    --port 587 \
    --from system@example.com \
    --username system@example.com \
    --tls-mode starttls \
    --service-user pi

  sudo ./add-msmtp-account.sh \
    --account provider-smtps \
    --host smtp.example.com \
    --tls-mode implicit \
    --root-only
EOF
}

log() {
  printf '%s: %s\n' "${PROGRAM_NAME}" "$*" >&2
}

die() {
  log "ERROR: $*"
  exit 1
}

cleanup() {
  local exit_code=$?

  PASSWORD=""
  PASSWORD_CONFIRM=""

  if [[ -n ${CONFIG_TEMP} && -e ${CONFIG_TEMP} ]]; then
    rm -f -- "${CONFIG_TEMP}"
  fi
  if [[ -n ${SECRET_TEMP} && -e ${SECRET_TEMP} ]]; then
    rm -f -- "${SECRET_TEMP}"
  fi

  trap - EXIT HUP INT TERM
  exit "${exit_code}"
}

trap cleanup EXIT HUP INT TERM

require_command() {
  local command_name=$1

  command -v "${command_name}" >/dev/null 2>&1 ||
    die "Required command not found: ${command_name}"
}

parse_arguments() {
  while (($# > 0)); do
    case "$1" in
      --account)
        (($# >= 2)) || die "--account requires a value"
        ACCOUNT_NAME=$2
        shift 2
        ;;
      --host)
        (($# >= 2)) || die "--host requires a value"
        SMTP_HOST=$2
        shift 2
        ;;
      --port)
        (($# >= 2)) || die "--port requires a value"
        SMTP_PORT=$2
        shift 2
        ;;
      --from)
        (($# >= 2)) || die "--from requires a value"
        FROM_ADDRESS=$2
        shift 2
        ;;
      --username)
        (($# >= 2)) || die "--username requires a value"
        SMTP_USER=$2
        shift 2
        ;;
      --tls-mode)
        (($# >= 2)) || die "--tls-mode requires a value"
        TLS_MODE=$2
        shift 2
        ;;
      --config)
        (($# >= 2)) || die "--config requires a value"
        CONFIG_FILE=$2
        shift 2
        ;;
      --secret-file)
        (($# >= 2)) || die "--secret-file requires a value"
        SECRET_FILE=$2
        shift 2
        ;;
      --group)
        (($# >= 2)) || die "--group requires a value"
        SECRET_GROUP=$2
        shift 2
        ;;
      --service-user)
        (($# >= 2)) || die "--service-user requires a value"
        AUTHORIZED_USERS+=("$2")
        shift 2
        ;;
      --root-only)
        ROOT_ONLY=true
        shift
        ;;
      -h | --help)
        usage
        exit 0
        ;;
      --)
        shift
        (($# == 0)) || die "Unexpected positional arguments: $*"
        ;;
      *)
        die "Unknown option: $1"
        ;;
    esac
  done
}

validate_platform() {
  [[ ${EUID} -eq 0 ]] || die "Run this script as root (for example, with sudo)"
  [[ -r /etc/os-release ]] || die "Cannot read /etc/os-release"

  # /etc/os-release is controlled by the operating system.
  # shellcheck disable=SC1091
  source /etc/os-release

  [[ ${ID:-} == "debian" && ${VERSION_ID:-} == "12" ]] ||
    die "This script supports Debian 12 only"
}

prompt_value() {
  local variable_name=$1
  local prompt_text=$2
  local default_value=${3:-}
  local current_value=${!variable_name}
  local entered_value=""

  [[ -z ${current_value} ]] || return

  if [[ -n ${default_value} ]]; then
    printf '%s [%s]: ' "${prompt_text}" "${default_value}" >/dev/tty
  else
    printf '%s: ' "${prompt_text}" >/dev/tty
  fi

  IFS= read -r entered_value </dev/tty
  if [[ -z ${entered_value} ]]; then
    entered_value=${default_value}
  fi
  printf -v "${variable_name}" '%s' "${entered_value}"
}

collect_account_details() {
  [[ -r /dev/tty && -w /dev/tty ]] ||
    die "An interactive terminal is required"

  prompt_value ACCOUNT_NAME "Account name"
  prompt_value SMTP_HOST "SMTP host"
  prompt_value TLS_MODE "TLS mode (starttls or implicit)" "starttls"

  case ${TLS_MODE} in
    starttls)
      prompt_value SMTP_PORT "SMTP port" "587"
      ;;
    implicit)
      prompt_value SMTP_PORT "SMTP port" "465"
      ;;
    *)
      die "TLS mode must be 'starttls' or 'implicit'"
      ;;
  esac

  prompt_value FROM_ADDRESS "Envelope-from address"
  prompt_value SMTP_USER "SMTP username" "${FROM_ADDRESS}"

  if [[ -z ${SECRET_FILE} ]]; then
    SECRET_FILE="/etc/msmtp/secrets/${ACCOUNT_NAME}-password"
  fi
}

validate_no_config_syntax() {
  local value=$1
  local label=$2

  [[ -n ${value} ]] || die "${label} cannot be empty"
  [[ ${value} != *[[:space:]#\"]* ]] ||
    die "${label} contains whitespace or unsupported configuration characters"
}

validate_options() {
  local port_number
  local user_name

  [[ ${ACCOUNT_NAME} =~ ^[A-Za-z0-9._-]+$ ]] ||
    die "Invalid account name: ${ACCOUNT_NAME}"
  [[ ${SMTP_HOST} =~ ^[A-Za-z0-9._:-]+$ ]] ||
    die "Invalid SMTP host or address: ${SMTP_HOST}"
  [[ ${SMTP_PORT} =~ ^[0-9]+$ ]] || die "Port must be numeric"
  port_number=$((10#${SMTP_PORT}))
  ((port_number >= 1 && port_number <= 65535)) ||
    die "Port must be between 1 and 65535"
  SMTP_PORT=${port_number}

  validate_no_config_syntax "${FROM_ADDRESS}" "From address"
  [[ ${FROM_ADDRESS} == *@* ]] || die "From address must contain @"
  validate_no_config_syntax "${SMTP_USER}" "SMTP username"

  [[ ${CONFIG_FILE} == /* ]] || die "--config must be an absolute path"
  [[ ${SECRET_FILE} == /* ]] || die "--secret-file must be an absolute path"
  [[ ${CONFIG_FILE} =~ ^/[A-Za-z0-9._/-]+$ ]] ||
    die "Config path contains unsupported characters: ${CONFIG_FILE}"
  [[ ${SECRET_FILE} =~ ^/[A-Za-z0-9._/-]+$ ]] ||
    die "Secret path contains unsupported characters: ${SECRET_FILE}"
  [[ ${SECRET_GROUP} =~ ^[A-Za-z0-9._-]+$ ]] ||
    die "Invalid group name: ${SECRET_GROUP}"

  [[ -d ${CONFIG_FILE%/*} ]] ||
    die "Configuration directory does not exist: ${CONFIG_FILE%/*}"
  [[ ! -L ${CONFIG_FILE} ]] || die "Refusing configuration symlink: ${CONFIG_FILE}"
  if [[ -e ${CONFIG_FILE} && ! -f ${CONFIG_FILE} ]]; then
    die "Configuration path is not a regular file: ${CONFIG_FILE}"
  fi
  if [[ -e ${SECRET_FILE} && -L ${SECRET_FILE} ]]; then
    die "Refusing secret symlink: ${SECRET_FILE}"
  fi

  if ${ROOT_ONLY} && ((${#AUTHORIZED_USERS[@]} > 0)); then
    die "--root-only cannot be combined with --service-user"
  fi

  if ! ${ROOT_ONLY} && ((${#AUTHORIZED_USERS[@]} == 0)); then
    if [[ -n ${SUDO_USER:-} && ${SUDO_USER} != "root" ]]; then
      AUTHORIZED_USERS+=("${SUDO_USER}")
      log "No --service-user supplied; authorizing SUDO_USER=${SUDO_USER}"
    else
      die "Specify --service-user or --root-only"
    fi
  fi

  for user_name in "${AUTHORIZED_USERS[@]}"; do
    id "${user_name}" >/dev/null 2>&1 || die "User does not exist: ${user_name}"
  done
}

lock_configuration() {
  exec 9>/run/lock/add-msmtp-account.lock
  flock -n 9 || die "Another msmtp account update is already running"
}

ensure_account_is_new() {
  [[ -f ${CONFIG_FILE} ]] || return

  if awk -v target_account="${ACCOUNT_NAME}" '
    /^[[:space:]]*account[[:space:]]+/ {
      account_name = $2
      sub(/:.*/, "", account_name)
      if (account_name == target_account) {
        found = 1
      }
    }
    END { exit(found ? 0 : 1) }
  ' "${CONFIG_FILE}"; then
    die "Account '${ACCOUNT_NAME}' already exists in ${CONFIG_FILE}"
  fi
}

prompt_for_password() {
  printf 'Enter the password for msmtp account %s: ' \
    "${ACCOUNT_NAME}" >/dev/tty
  IFS= read -r -s PASSWORD </dev/tty
  printf '\n' >/dev/tty
  [[ -n ${PASSWORD} ]] || die "The password cannot be empty"

  printf 'Confirm the password: ' >/dev/tty
  IFS= read -r -s PASSWORD_CONFIRM </dev/tty
  printf '\n' >/dev/tty
  [[ ${PASSWORD} == "${PASSWORD_CONFIRM}" ]] || die "Passwords do not match"
  PASSWORD_CONFIRM=""
}

confirm_secret_replacement() {
  local answer=""

  [[ -e ${SECRET_FILE} ]] || return

  printf 'Secret file %s already exists. Replace it? [y/N]: ' \
    "${SECRET_FILE}" >/dev/tty
  IFS= read -r answer </dev/tty
  [[ ${answer} == "y" || ${answer} == "Y" ]] ||
    die "Existing secret was not replaced"
}

configure_secret_access() {
  local secret_directory=${SECRET_FILE%/*}
  local user_name

  if ${ROOT_ONLY}; then
    install -d -o root -g root -m 700 -- "${secret_directory}"
    return
  fi

  if ! getent group "${SECRET_GROUP}" >/dev/null; then
    addgroup --system "${SECRET_GROUP}" >/dev/null
  fi

  for user_name in "${AUTHORIZED_USERS[@]}"; do
    adduser "${user_name}" "${SECRET_GROUP}" >/dev/null
  done

  install -d -o root -g "${SECRET_GROUP}" -m 750 -- "${secret_directory}"
}

write_secret() {
  local secret_directory=${SECRET_FILE%/*}

  umask 077
  SECRET_TEMP=$(mktemp "${secret_directory}/.${ACCOUNT_NAME}-password.XXXXXX")
  printf '%s\n' "${PASSWORD}" >"${SECRET_TEMP}"

  if ${ROOT_ONLY}; then
    chown root:root "${SECRET_TEMP}"
    chmod 600 "${SECRET_TEMP}"
  else
    chown root:"${SECRET_GROUP}" "${SECRET_TEMP}"
    chmod 640 "${SECRET_TEMP}"
  fi

  mv -f -- "${SECRET_TEMP}" "${SECRET_FILE}"
  SECRET_TEMP=""
  PASSWORD=""
  log "Installed password at ${SECRET_FILE}"
}

append_account_block() {
  local tls_starttls

  if [[ ${TLS_MODE} == "starttls" ]]; then
    tls_starttls="on"
  else
    tls_starttls="off"
  fi

  {
    printf '\n# SMTP account: %s\n' "${ACCOUNT_NAME}"
    printf 'account %s\n' "${ACCOUNT_NAME}"
    printf 'host %s\n' "${SMTP_HOST}"
    printf 'port %s\n' "${SMTP_PORT}"
    printf 'from %s\n' "${FROM_ADDRESS}"
    printf 'user %s\n' "${SMTP_USER}"
    printf 'auth on\n'
    printf 'tls on\n'
    printf 'tls_starttls %s\n' "${tls_starttls}"
    printf 'tls_trust_file /etc/ssl/certs/ca-certificates.crt\n'
    printf 'passwordeval "/usr/bin/cat %s"\n' "${SECRET_FILE}"
  } >>"${CONFIG_TEMP}"
}

write_configuration() {
  local config_directory=${CONFIG_FILE%/*}
  local config_existed=false

  [[ -f ${CONFIG_FILE} ]] && config_existed=true
  umask 077
  CONFIG_TEMP=$(mktemp "${config_directory}/.msmtprc.XXXXXX")

  if ${config_existed}; then
    cp --preserve=all -- "${CONFIG_FILE}" "${CONFIG_TEMP}"
  else
    chown root:root "${CONFIG_TEMP}"
    chmod 644 "${CONFIG_TEMP}"
    {
      printf '# System-wide msmtp configuration for Debian 12\n\n'
      printf 'defaults\n'
      printf 'auth on\n'
      printf 'tls on\n'
      printf 'tls_trust_file /etc/ssl/certs/ca-certificates.crt\n'
    } >"${CONFIG_TEMP}"
  fi

  append_account_block

  if ! ${config_existed}; then
    printf '\n# Use the only configured account by default\n' >>"${CONFIG_TEMP}"
    printf 'account default: %s\n' "${ACCOUNT_NAME}" >>"${CONFIG_TEMP}"
  fi

  if ! msmtp --pretend --file="${CONFIG_TEMP}" \
    --account="${ACCOUNT_NAME}" recipient@example.invalid \
    </dev/null >/dev/null; then
    die "The generated msmtp configuration failed validation"
  fi

  mv -f -- "${CONFIG_TEMP}" "${CONFIG_FILE}"
  CONFIG_TEMP=""

  if ${config_existed}; then
    log "Appended account '${ACCOUNT_NAME}' to ${CONFIG_FILE}"
  else
    log "Created ${CONFIG_FILE} with account '${ACCOUNT_NAME}'"
  fi
}

print_summary() {
  printf '\nmsmtp account created successfully.\n'
  printf '  Account:     %s\n' "${ACCOUNT_NAME}"
  printf '  SMTP server: %s:%s\n' "${SMTP_HOST}" "${SMTP_PORT}"
  printf '  TLS mode:    %s\n' "${TLS_MODE}"
  printf '  Config:      %s\n' "${CONFIG_FILE}"
  printf '  Secret:      %s\n' "${SECRET_FILE}"

  if ${ROOT_ONLY}; then
    printf '  Access:      root only\n'
  else
    printf '  Secret group: %s\n' "${SECRET_GROUP}"
    printf '  Authorized users:\n'
    printf '    - %s\n' "${AUTHORIZED_USERS[@]}"
    printf '\nLog out and back in, or restart affected services, so new group\n'
    printf 'membership takes effect.\n'
  fi

  printf '\nConfiguration test:\n'
  printf '  msmtp --pretend --account=%q recipient@example.com </dev/null\n' \
    "${ACCOUNT_NAME}"
}

main() {
  parse_arguments "$@"
  validate_platform

  require_command addgroup
  require_command adduser
  require_command awk
  require_command chmod
  require_command chown
  require_command cp
  require_command flock
  require_command getent
  require_command id
  require_command install
  require_command mktemp
  require_command msmtp
  require_command mv
  require_command rm

  collect_account_details
  validate_options
  lock_configuration
  ensure_account_is_new
  confirm_secret_replacement
  prompt_for_password
  configure_secret_access
  write_secret
  write_configuration
  print_summary
}

main "$@"
