#!/usr/bin/env bash

# Separate an msmtp account password from /etc/msmtprc on Debian 12.
# The password is collected from /dev/tty and is never accepted as a
# command-line argument.

set -Eeuo pipefail

readonly PROGRAM_NAME="${0##*/}"

CONFIG_FILE="/etc/msmtprc"
ACCOUNT_NAME="mailgun"
SECRET_FILE=""
SECRET_GROUP="msmtp-secrets"
ROOT_ONLY=false
declare -a AUTHORIZED_USERS=()

CONFIG_TEMP=""
SECRET_TEMP=""
PASSWORD=""
PASSWORD_CONFIRM=""

usage() {
  cat <<'EOF'
Usage:
  sudo separate-msmtp-secret.sh [options]

Safely moves an msmtp account password into a permission-restricted file and
replaces password/passwordeval directives in that account with passwordeval.

Options:
  --account NAME       Account to update (default: mailgun)
  --config PATH        msmtprc to update (default: /etc/msmtprc)
  --secret-file PATH   Password file (default:
                       /etc/msmtp/secrets/ACCOUNT-password)
  --group NAME         Secret-reader group (default: msmtp-secrets)
  --user USER          Authorize USER to read the secret; repeat as needed
  --root-only          Restrict the secret to root instead of using a group
  -h, --help           Show this help

If neither --user nor --root-only is given, the non-root SUDO_USER is
authorized. If no such user exists, an explicit access mode is required.

Examples:
  sudo ./separate-msmtp-secret.sh --account mailgun --user pi
  sudo ./separate-msmtp-secret.sh --account mailgun --root-only
  sudo ./separate-msmtp-secret.sh --user unbound --user monitoring

The password is prompted for twice using /dev/tty. It is never accepted on the
command line or read from standard input.
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

  if [[ -n "${CONFIG_TEMP}" && -e "${CONFIG_TEMP}" ]]; then
    rm -f -- "${CONFIG_TEMP}"
  fi
  if [[ -n "${SECRET_TEMP}" && -e "${SECRET_TEMP}" ]]; then
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
      --user)
        (($# >= 2)) || die "--user requires a value"
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

validate_options() {
  [[ ${ACCOUNT_NAME} =~ ^[A-Za-z0-9._-]+$ ]] ||
    die "Invalid account name: ${ACCOUNT_NAME}"
  [[ ${SECRET_GROUP} =~ ^[A-Za-z0-9._-]+$ ]] ||
    die "Invalid group name: ${SECRET_GROUP}"
  [[ ${CONFIG_FILE} == /* ]] || die "--config must be an absolute path"

  if [[ -z ${SECRET_FILE} ]]; then
    SECRET_FILE="/etc/msmtp/secrets/${ACCOUNT_NAME}-password"
  fi

  [[ ${SECRET_FILE} == /* ]] || die "--secret-file must be an absolute path"
  [[ ${SECRET_FILE} =~ ^/[A-Za-z0-9._/-]+$ ]] ||
    die "Secret path contains unsupported characters: ${SECRET_FILE}"
  [[ ${CONFIG_FILE} =~ ^/[A-Za-z0-9._/-]+$ ]] ||
    die "Config path contains unsupported characters: ${CONFIG_FILE}"

  [[ -f ${CONFIG_FILE} ]] || die "Configuration file not found: ${CONFIG_FILE}"
  [[ ! -L ${CONFIG_FILE} ]] || die "Refusing to replace symlink: ${CONFIG_FILE}"
  if [[ -e ${SECRET_FILE} && -L ${SECRET_FILE} ]]; then
    die "Refusing to replace secret symlink: ${SECRET_FILE}"
  fi

  if ${ROOT_ONLY} && ((${#AUTHORIZED_USERS[@]} > 0)); then
    die "--root-only cannot be combined with --user"
  fi

  if ! ${ROOT_ONLY} && ((${#AUTHORIZED_USERS[@]} == 0)); then
    if [[ -n ${SUDO_USER:-} && ${SUDO_USER} != "root" ]]; then
      AUTHORIZED_USERS+=("${SUDO_USER}")
      log "No --user supplied; authorizing SUDO_USER=${SUDO_USER}"
    else
      die "Specify at least one --user or select --root-only"
    fi
  fi

  local user_name
  for user_name in "${AUTHORIZED_USERS[@]}"; do
    id "${user_name}" >/dev/null 2>&1 || die "User does not exist: ${user_name}"
  done
}

prompt_for_password() {
  [[ -r /dev/tty && -w /dev/tty ]] ||
    die "An interactive terminal is required to collect the password"

  printf 'Enter the new password for msmtp account %s: ' \
    "${ACCOUNT_NAME}" >/dev/tty
  IFS= read -r -s PASSWORD </dev/tty
  printf '\n' >/dev/tty

  [[ -n ${PASSWORD} ]] || die "The password cannot be empty"

  printf 'Confirm the new password: ' >/dev/tty
  IFS= read -r -s PASSWORD_CONFIRM </dev/tty
  printf '\n' >/dev/tty

  [[ ${PASSWORD} == "${PASSWORD_CONFIRM}" ]] || die "Passwords do not match"
  PASSWORD_CONFIRM=""
}

configure_access() {
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

rewrite_configuration() {
  local config_directory=${CONFIG_FILE%/*}
  local passwordeval_line

  passwordeval_line="passwordeval \"/usr/bin/cat ${SECRET_FILE}\""
  CONFIG_TEMP=$(mktemp "${config_directory}/.msmtprc.XXXXXX")

  if ! awk \
    -v target_account="${ACCOUNT_NAME}" \
    -v replacement="${passwordeval_line}" '
      function finish_account() {
        if (in_target && !inserted) {
          print replacement
          inserted = 1
        }
      }

      /^[[:space:]]*account[[:space:]]+/ {
        finish_account()

        account_name = $2
        sub(/:.*/, "", account_name)
        in_target = (account_name == target_account)
        if (in_target) {
          matches++
          inserted = 0
        }

        print
        next
      }

      in_target && /^[[:space:]]*#?[[:space:]]*password(eval)?([[:space:]]|$)/ {
        if (!inserted) {
          print replacement
          inserted = 1
        }
        next
      }

      { print }

      END {
        finish_account()
        if (matches != 1) {
          exit 42
        }
      }
    ' "${CONFIG_FILE}" >"${CONFIG_TEMP}"; then
    die "Expected exactly one account named '${ACCOUNT_NAME}' in ${CONFIG_FILE}"
  fi

  chown --reference="${CONFIG_FILE}" "${CONFIG_TEMP}"
  chmod --reference="${CONFIG_FILE}" "${CONFIG_TEMP}"

  if ! msmtp --pretend --file="${CONFIG_TEMP}" \
    --account="${ACCOUNT_NAME}" recipient@example.invalid \
    </dev/null >/dev/null; then
    die "The rewritten msmtp configuration failed validation"
  fi

  mv -f -- "${CONFIG_TEMP}" "${CONFIG_FILE}"
  CONFIG_TEMP=""
  log "Updated account '${ACCOUNT_NAME}' in ${CONFIG_FILE}"
}

print_summary() {
  printf '\nmsmtp password separation completed successfully.\n'
  printf '  Account:     %s\n' "${ACCOUNT_NAME}"
  printf '  Config:      %s\n' "${CONFIG_FILE}"
  printf '  Secret file: %s\n' "${SECRET_FILE}"

  if ${ROOT_ONLY}; then
    printf '  Access:      root only\n'
  else
    printf '  Access group: %s\n' "${SECRET_GROUP}"
    printf '  Authorized users:\n'
    printf '    - %s\n' "${AUTHORIZED_USERS[@]}"
    printf '\nLog out and back in, or restart affected services, before testing as\n'
    printf 'a newly authorized user.\n'
  fi

  printf '\nTest with:\n'
  printf '  msmtp --pretend --account=%q recipient@example.com </dev/null\n' \
    "${ACCOUNT_NAME}"
  printf '\nRotate any password that was previously committed to Git, and remove it\n'
  printf 'from repository history if required by your security policy.\n'
}

main() {
  parse_arguments "$@"
  validate_platform

  require_command addgroup
  require_command adduser
  require_command awk
  require_command chmod
  require_command chown
  require_command getent
  require_command id
  require_command install
  require_command mktemp
  require_command msmtp
  require_command mv
  require_command rm

  validate_options
  prompt_for_password
  configure_access
  write_secret
  rewrite_configuration
  print_summary
}

main "$@"
