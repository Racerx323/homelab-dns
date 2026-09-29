#!/usr/bin/env bash

set -euo pipefail

# build.sh builds Nebula-Sync from an upstream GitHub release tarball. The
# default version is "latest", resolved from the GitHub release redirect at run
# time so maintainers can pick up new releases without editing this script.
readonly PROGRAM_NAME="${0##*/}"
readonly APP_NAME="nebula-sync"
readonly REPOSITORY="lovelaze/nebula-sync"
readonly GITHUB_URL="https://github.com/${REPOSITORY}"
readonly DEFAULT_BUILD_DIR="build"
readonly DEFAULT_DIST_DIR="dist"
readonly BUILD_DEPENDENCIES=(
  ca-certificates
  curl
  golang-go
  tar
  coreutils
)
readonly REQUIRED_COMMANDS=(
  curl
  go
  grep
  mv
  sha256sum
  tar
)

version="latest"
build_dir="${DEFAULT_BUILD_DIR}"
dist_dir="${DEFAULT_DIST_DIR}"
goos=""
goarch=""
goamd64=""
dry_run=false
keep_workdir=false
install_deps=false
check_deps=false
generic=false

usage() {
  cat <<USAGE
Usage:
  ${PROGRAM_NAME} [options]

Build options:
      --version VERSION   Release tag to build. Default: latest
      --build-dir PATH    Build workspace. Default: build
      --dist-dir PATH     Artifact output directory. Default: dist
      --goos GOOS         Target operating system. Default: detected platform
      --goarch GOARCH     Target architecture. Default: detected platform
      --generic           Avoid CPU-specific GOAMD64 tuning.
      --check-deps        Report missing build dependencies and exit.
      --install-deps      Install missing Debian build dependencies.
      --keep-workdir      Keep extracted source after a successful build.
      --clean             Accepted for compatibility; builds are always clean.
  -n, --dry-run           Print actions without downloading or building.
  -h, --help              Show this help text.

Examples:
  bash ./scripts/build.sh
  bash ./scripts/build.sh --version v0.11.2
  bash ./scripts/build.sh --dry-run --version latest
USAGE
}

log() {
  printf '%s\n' "$*"
}

die() {
  printf 'Error: %s\n' "$*" >&2
  exit 1
}

repository_root() {
  local script_dir

  script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
  cd -- "${script_dir}/.." && pwd
}

# Print the command in a reusable shape for dry-run output, or execute it with
# arguments preserved exactly as passed.
run_cmd() {
  if [[ "${dry_run}" == "true" ]]; then
    printf '[dry-run]'
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi

  "$@"
}

run_in_dir() {
  local directory=$1
  shift

  if [[ "${dry_run}" == "true" ]]; then
    printf '[dry-run] cd %q &&' "${directory}"
    printf ' %q' "$@"
    printf '\n'
    return 0
  fi

  (cd "${directory}" && "$@")
}

require_root() {
  if [[ "${dry_run}" == "true" ]]; then
    return 0
  fi

  if [[ "${EUID}" -ne 0 ]]; then
    die "--install-deps must be run with sudo or as root"
  fi
}

require_command() {
  local command_name=$1

  if ! command -v "${command_name}" >/dev/null 2>&1; then
    die "required command not found: ${command_name}"
  fi
}

command_available() {
  command -v "$1" >/dev/null 2>&1
}

# Report command-level gaps so non-Debian or partially configured systems get a
# useful error even when package metadata is unavailable.
missing_required_commands() {
  local command_name

  for command_name in "${REQUIRED_COMMANDS[@]}"; do
    if ! command_available "${command_name}"; then
      printf '%s\n' "${command_name}"
    fi
  done
}

# Debian package checks are kept separate from command checks because one
# package can provide several commands, and installed packages may still be
# absent from PATH on unusual systems.
missing_debian_packages() {
  local package_name

  for package_name in "${BUILD_DEPENDENCIES[@]}"; do
    if ! dpkg-query -W -f='${Status}' "${package_name}" 2>/dev/null | grep -q 'install ok installed'; then
      printf '%s\n' "${package_name}"
    fi
  done
}

# Print dependency status without modifying the system. This is the safest first
# step before a maintainer opts into --install-deps.
report_build_dependencies() {
  local missing_commands
  local missing_packages

  missing_commands="$(missing_required_commands)"
  if command_available dpkg-query; then
    missing_packages="$(missing_debian_packages)"
  else
    missing_packages=""
  fi

  if [[ -z "${missing_commands}" && -z "${missing_packages}" ]]; then
    log "All build dependencies are installed."
    return 0
  fi

  if [[ -n "${missing_commands}" ]]; then
    log "Missing commands:"
    printf '%s\n' "${missing_commands}" | sed 's/^/  /'
  fi

  if [[ -n "${missing_packages}" ]]; then
    log "Missing Debian packages:"
    printf '%s\n' "${missing_packages}" | sed 's/^/  /'
  fi

  return 1
}

# Install only missing Debian packages. If everything is already present, the
# routine logs a no-op instead of asking apt-get to reinstall the full set.
install_build_dependencies() {
  local missing_packages=()

  if [[ "${dry_run}" != "true" ]]; then
    require_command apt-get
  fi
  require_root

  if command_available dpkg-query; then
    readarray -t missing_packages < <(missing_debian_packages)
  else
    missing_packages=("${BUILD_DEPENDENCIES[@]}")
  fi

  if [[ "${#missing_packages[@]}" -eq 0 ]]; then
    log "All Debian build dependency packages are already installed."
    return 0
  fi

  run_cmd env DEBIAN_FRONTEND=noninteractive apt-get update
  run_cmd env DEBIAN_FRONTEND=noninteractive apt-get install -y "${missing_packages[@]}"
}

# Translate uname's kernel names into Go's GOOS names. The script optimizes for
# the target where it is run, while still allowing explicit --goos overrides.
detect_goos() {
  local kernel_name

  kernel_name="$(uname -s 2>/dev/null || printf 'Linux')"
  case "${kernel_name}" in
    Linux)
      printf 'linux\n'
      ;;
    Darwin)
      printf 'darwin\n'
      ;;
    MINGW* | MSYS* | CYGWIN*)
      printf 'windows\n'
      ;;
    *)
      printf '%s\n' "${kernel_name,,}"
      ;;
  esac
}

# Translate uname's hardware names into Go's GOARCH names. This avoids needing
# go env before Go is installed.
detect_goarch() {
  local machine_name

  machine_name="$(uname -m 2>/dev/null || printf 'x86_64')"
  case "${machine_name}" in
    x86_64 | amd64)
      printf 'amd64\n'
      ;;
    aarch64 | arm64)
      printf 'arm64\n'
      ;;
    armv7l | armv7*)
      printf 'arm\n'
      ;;
    i386 | i686)
      printf '386\n'
      ;;
    *)
      printf '%s\n' "${machine_name}"
      ;;
  esac
}

# Pick the highest amd64 tuning level supported by the local CPU flags. This is
# intentionally target-native; use --generic when building for older machines.
detect_goamd64() {
  local cpu_flags

  if [[ "${generic}" == "true" || "$(detect_goarch)" != "amd64" ]]; then
    return 0
  fi

  cpu_flags="$(awk -F ': ' '/flags/ { print $2; exit }' /proc/cpuinfo 2>/dev/null || true)"
  [[ -n "${cpu_flags}" ]] || return 0

  if [[ " ${cpu_flags} " == *" avx512f "* && " ${cpu_flags} " == *" avx512bw "* && " ${cpu_flags} " == *" avx512cd "* && " ${cpu_flags} " == *" avx512dq "* && " ${cpu_flags} " == *" avx512vl "* ]]; then
    printf 'v4\n'
  elif [[ " ${cpu_flags} " == *" avx "* && " ${cpu_flags} " == *" avx2 "* && " ${cpu_flags} " == *" bmi1 "* && " ${cpu_flags} " == *" bmi2 "* && " ${cpu_flags} " == *" f16c "* && " ${cpu_flags} " == *" fma "* && " ${cpu_flags} " == *" lzcnt "* && " ${cpu_flags} " == *" movbe "* ]]; then
    printf 'v3\n'
  elif [[ " ${cpu_flags} " == *" cx16 "* && " ${cpu_flags} " == *" lahf_lm "* && " ${cpu_flags} " == *" popcnt "* && (" ${cpu_flags} " == *" sse3 "* || " ${cpu_flags} " == *" pni "*) && " ${cpu_flags} " == *" ssse3 "* && " ${cpu_flags} " == *" sse4_1 "* && " ${cpu_flags} " == *" sse4_2 "* ]]; then
    printf 'v2\n'
  fi
}

# Finalize target settings before validation so downstream build paths and
# artifact names are deterministic.
configure_target_platform() {
  if [[ -z "${goos}" ]]; then
    goos="$(detect_goos)"
  fi

  if [[ -z "${goarch}" ]]; then
    goarch="$(detect_goarch)"
  fi

  if [[ -z "${goamd64}" && "${goarch}" == "amd64" ]]; then
    goamd64="$(detect_goamd64)"
  fi

  log "Target platform: GOOS=${goos} GOARCH=${goarch}"
  if [[ -n "${goamd64}" ]]; then
    log "CPU tuning: GOAMD64=${goamd64}"
  elif [[ "${goarch}" == "amd64" ]]; then
    log "CPU tuning: GOAMD64 default"
  fi
}

parse_arguments() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --version)
        shift
        [[ $# -gt 0 ]] || die "--version requires a release tag"
        version=$1
        ;;
      --build-dir)
        shift
        [[ $# -gt 0 ]] || die "--build-dir requires a path"
        build_dir=$1
        ;;
      --dist-dir)
        shift
        [[ $# -gt 0 ]] || die "--dist-dir requires a path"
        dist_dir=$1
        ;;
      --goos)
        shift
        [[ $# -gt 0 ]] || die "--goos requires a value"
        goos=$1
        ;;
      --goarch)
        shift
        [[ $# -gt 0 ]] || die "--goarch requires a value"
        goarch=$1
        ;;
      --generic)
        generic=true
        goamd64=""
        ;;
      --check-deps)
        check_deps=true
        ;;
      --install-deps)
        install_deps=true
        ;;
      --keep-workdir)
        keep_workdir=true
        ;;
      --clean)
        log "--clean is accepted for compatibility; extraction is always clean."
        ;;
      -n | --dry-run)
        dry_run=true
        ;;
      -h | --help | help)
        usage
        exit 0
        ;;
      *)
        die "unknown argument: $1"
        ;;
    esac
    shift
  done
}

validate_configuration() {
  [[ -n "${version}" ]] || die "--version must not be empty"
  [[ -n "${build_dir}" ]] || die "--build-dir must not be empty"
  [[ -n "${dist_dir}" ]] || die "--dist-dir must not be empty"
  [[ -n "${goos}" ]] || die "--goos must not be empty"
  [[ -n "${goarch}" ]] || die "--goarch must not be empty"
  [[ "${build_dir}" != "/" ]] || die "--build-dir must not be /"
  [[ "${dist_dir}" != "/" ]] || die "--dist-dir must not be /"
}

# GitHub's latest-release endpoint redirects to /releases/tag/<tag>. Parsing
# the Location header avoids requiring jq for a tiny JSON query.
resolve_latest_version() {
  local latest_url="${GITHUB_URL}/releases/latest"
  local headers
  local location

  if [[ "${dry_run}" == "true" ]]; then
    printf '[dry-run] resolve latest release from %s\n' "${latest_url}" >&2
    if ! command -v curl >/dev/null 2>&1; then
      printf 'latest\n'
      return 0
    fi
  fi

  headers="$(curl -fsSLI "${latest_url}" 2>/dev/null || true)"
  location="$(printf '%s\n' "${headers}" | awk 'BEGIN { IGNORECASE = 1 } /^location:/ { print $2 }' | tr -d '\r' | tail -n 1)"
  if [[ -z "${location}" ]]; then
    if [[ "${dry_run}" == "true" ]]; then
      printf 'latest\n'
      return 0
    fi
    die "could not resolve latest release from ${latest_url}"
  fi

  location="${location%/}"
  printf '%s\n' "${location##*/}"
}

release_tarball_url() {
  local release_version=$1

  printf '%s/archive/refs/tags/%s.tar.gz\n' "${GITHUB_URL}" "${release_version}"
}

download_release_tarball() {
  local release_version=$1
  local tarball=$2
  local cache_dir
  local temp_tarball

  cache_dir="$(dirname -- "${tarball}")"
  temp_tarball="$(mktemp "${cache_dir}/.${APP_NAME}-${release_version}.tar.gz.XXXXXX")"

  if ! run_cmd curl -fL "$(release_tarball_url "${release_version}")" -o "${temp_tarball}"; then
    rm -f -- "${temp_tarball}"
    return 1
  fi

  if ! tar -tzf "${temp_tarball}" >/dev/null; then
    rm -f -- "${temp_tarball}"
    die "downloaded archive failed validation: ${temp_tarball}"
  fi

  run_cmd mv -f -- "${temp_tarball}" "${tarball}"
}

validate_extracted_source() {
  local source_dir=$1

  if [[ ! -f "${source_dir}/go.mod" ]]; then
    printf 'Error: extracted source is missing go.mod: %s\n' "${source_dir}" >&2
    return 1
  fi

  if ! grep -q '^module ' "${source_dir}/go.mod"; then
    printf 'Error: extracted go.mod is missing module declaration: %s\n' "${source_dir}/go.mod" >&2
    return 1
  fi
}

stage_release_source() {
  local root_dir=$1
  local release_version=$2
  local cache_dir="${root_dir}/${build_dir}/cache"
  local work_dir="${root_dir}/${build_dir}/${APP_NAME}-${release_version}"
  local tarball="${cache_dir}/${APP_NAME}-${release_version}.tar.gz"
  local temp_work_dir

  run_cmd mkdir -p "${cache_dir}" "${root_dir}/${build_dir}"

  if [[ "${dry_run}" == "true" ]]; then
    log "[dry-run] download release archive to temp file for ${tarball}"
    log "[dry-run] validate archive ${tarball}"
    log "[dry-run] extract archive to temp directory for ${work_dir}"
    log "[dry-run] validate extracted Go module for ${work_dir}"
    log "[dry-run] replace ${work_dir} with validated temp directory"
    return 0
  fi

  download_release_tarball "${release_version}" "${tarball}"
  temp_work_dir="$(mktemp -d "${root_dir}/${build_dir}/.${APP_NAME}-${release_version}.XXXXXX")"
  if ! tar -xzf "${tarball}" --strip-components=1 -C "${temp_work_dir}"; then
    rm -rf -- "${temp_work_dir}"
    die "could not extract release archive: ${tarball}"
  fi
  if ! validate_extracted_source "${temp_work_dir}"; then
    rm -rf -- "${temp_work_dir}"
    return 1
  fi
  run_cmd rm -rf -- "${work_dir:?}"
  run_cmd mv -f -- "${temp_work_dir}" "${work_dir}"
}

# Select the package to build from the extracted upstream source. Prefer an
# import path that ends in /cmd/nebula-sync, then fall back to the first main.
discover_main_package() {
  local source_dir=$1
  local main_packages
  local selected_package

  if ! main_packages="$(cd "${source_dir}" && go list -buildvcs=false -f '{{if eq .Name "main"}}{{.ImportPath}}{{end}}' ./... | sed '/^$/d')"; then
    die "could not inspect Go packages in ${source_dir}"
  fi
  [[ -n "${main_packages}" ]] || die "no Go main package found in ${source_dir}"

  selected_package="$(printf '%s\n' "${main_packages}" | awk '/\/cmd\/nebula-sync$/ { print; exit }')"
  if [[ -z "${selected_package}" ]]; then
    selected_package="$(printf '%s\n' "${main_packages}" | head -n 1)"
  fi

  printf '%s\n' "${selected_package}"
}

build_release() {
  local root_dir=$1
  local release_version=$2
  local cache_dir="${root_dir}/${build_dir}/cache"
  local work_dir="${root_dir}/${build_dir}/${APP_NAME}-${release_version}"
  local output_dir="${root_dir}/${dist_dir}/${APP_NAME}-${release_version}-${goos}-${goarch}"
  local output_binary="${output_dir}/${APP_NAME}"
  local main_package
  local build_environment=(
    GOOS="${goos}"
    GOARCH="${goarch}"
  )

  if [[ -n "${goamd64}" ]]; then
    build_environment+=(GOAMD64="${goamd64}")
  fi

  if [[ "${goos}" == "windows" ]]; then
    output_binary="${output_binary}.exe"
  fi

  stage_release_source "${root_dir}" "${release_version}"
  run_cmd rm -rf -- "${output_dir:?}"
  run_cmd mkdir -p "${cache_dir}" "${output_dir}"

  if [[ "${dry_run}" == "true" ]]; then
    log "[dry-run] discover Go main package in ${work_dir}"
    log "[dry-run] ${build_environment[*]} go build -trimpath -buildvcs=false -o ${output_binary} <main-package>"
    log "[dry-run] sha256sum ${output_binary} > ${output_binary}.sha256"
    log "[dry-run] install -m 0755 ${output_binary} ${root_dir}/${dist_dir}/${APP_NAME}"
    return 0
  fi

  main_package="$(discover_main_package "${work_dir}")"
  log "Building ${REPOSITORY} ${release_version} (${goos}/${goarch}) from ${main_package}"
  run_in_dir "${work_dir}" env "${build_environment[@]}" go build -trimpath -buildvcs=false -o "${output_binary}" "${main_package}"
  run_cmd sha256sum "${output_binary}" >"${output_binary}.sha256"
  run_cmd install -m 0755 "${output_binary}" "${root_dir}/${dist_dir}/${APP_NAME}"

  if [[ "${keep_workdir}" != "true" ]]; then
    run_cmd rm -rf -- "${work_dir:?}"
  fi

  log "Built ${output_binary}"
  log "Installer binary ${root_dir}/${dist_dir}/${APP_NAME}"
  log "Checksum ${output_binary}.sha256"
}

main() {
  local root_dir
  local release_version

  parse_arguments "$@"
  configure_target_platform
  validate_configuration

  if [[ "${install_deps}" == "true" ]]; then
    install_build_dependencies
  fi

  if [[ "${check_deps}" == "true" ]]; then
    report_build_dependencies
    exit $?
  fi

  if [[ "${dry_run}" != "true" ]]; then
    require_command curl
    require_command tar
    require_command go
    require_command sha256sum
  fi

  root_dir="$(repository_root)"
  release_version="${version}"
  if [[ "${release_version}" == "latest" ]]; then
    release_version="$(resolve_latest_version)"
  fi

  build_release "${root_dir}" "${release_version}"
}

main "$@"
