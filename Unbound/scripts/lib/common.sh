#!/usr/bin/env bash

set -Eeuo pipefail

UNBOUND_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
readonly UNBOUND_ROOT
readonly RELEASE_ENV="$UNBOUND_ROOT/packaging/release.env"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

log() {
  printf '==> %s\n' "$*" >&2
}

require_commands() {
  local command_name
  for command_name in "$@"; do
    command -v "$command_name" >/dev/null 2>&1 || die "missing command: $command_name"
  done
}

require_root() {
  [[ ${EUID:-$(id -u)} -eq 0 ]] || die "run this command as root"
}

load_release_env() {
  [[ -r $RELEASE_ENV ]] || die "missing $RELEASE_ENV"
  if LC_ALL=C sed '/^#/d; /^$/d' "$RELEASE_ENV" | sed -n '/^[A-Z_][A-Z0-9_]*=[A-Za-z0-9._:~+\/@-]*$/!p' | sed -n '1p' | read -r; then
    die "release.env contains an unsafe or malformed value"
  fi
  # shellcheck disable=SC1090
  source "$RELEASE_ENV"
  export UPSTREAM_VERSION DEBIAN_REVISION BACKPORT_VERSION PROFILE_VERSION
  export TARGET_SUITE TARGET_ARCH SBUILD_CHROOT SOURCE_DSC_URL
  [[ $BACKPORT_VERSION == "$UPSTREAM_VERSION-$DEBIAN_REVISION~bookworm1" ]] ||
    die "backport version does not match the pinned source"
  [[ $TARGET_SUITE == bookworm && $TARGET_ARCH == arm64 ]] ||
    die "only native Debian 12 arm64 builds are supported"
}

assert_bookworm_arm64() {
  local os_id version_id architecture
  # shellcheck disable=SC1091
  source /etc/os-release
  os_id=${ID:-}
  version_id=${VERSION_ID:-}
  architecture=$(dpkg --print-architecture)
  [[ $os_id == debian && $version_id == 12 && $architecture == arm64 ]] ||
    die "requires Debian 12 arm64; found ${os_id:-unknown} ${version_id:-unknown} $architecture"
}

safe_output_directory() {
  local path=$1
  [[ $path == "$UNBOUND_ROOT/packaging/work" || $path == "$UNBOUND_ROOT/packaging/work/"* ||
    $path == "$UNBOUND_ROOT/packaging/release" || $path == "$UNBOUND_ROOT/packaging/release/"* ]] ||
    die "refusing unsafe generated-output path: $path"
}

verify_bundle() {
  local bundle_dir=$1
  [[ -d $bundle_dir ]] || die "bundle directory does not exist: $bundle_dir"
  [[ -f $bundle_dir/SHA256SUMS && -f $bundle_dir/SHA256SUMS.asc ]] ||
    die "bundle is missing checksums or detached signature"
  (
    cd "$bundle_dir"
    gpg --verify SHA256SUMS.asc SHA256SUMS
    sha256sum --check SHA256SUMS
  )
}

assert_sysctls() {
  local receive_buffer send_buffer
  receive_buffer=$(sysctl -n net.core.rmem_max)
  send_buffer=$(sysctl -n net.core.wmem_max)
  ((receive_buffer >= 4194304)) || die "net.core.rmem_max is below 4194304"
  ((send_buffer >= 4194304)) || die "net.core.wmem_max is below 4194304"
}

assert_loopback_listener() {
  local listener_output
  listener_output=$(ss -H -lntu '( sport = :5335 )')
  [[ -n $listener_output ]] || die "nothing listens on port 5335"
  if awk '{print $5}' <<<"$listener_output" | sed -n '/^127\.0\.0\.1:/!{/^\[::1\]:/!p;}' | read -r; then
    die "port 5335 is exposed beyond loopback"
  fi
}
