#!/usr/bin/env bats

setup() {
  repo_root="$(cd "${BATS_TEST_DIRNAME}/.." && pwd)"
  installer="${repo_root}/scripts/install.sh"
  builder="${repo_root}/scripts/build.sh"
  built_binary="${repo_root}/dist/nebula-sync"
  created_built_binary=false

  if [[ ! -e "${built_binary}" ]]; then
    mkdir -p "${repo_root}/dist"
    printf '#!/usr/bin/env bash\n' >"${built_binary}"
    created_built_binary=true
  fi
}

teardown() {
  if [[ "${created_built_binary}" == "true" ]]; then
    rm -f -- "${built_binary}"
  fi
}

@test "build help prints release options" {
  run bash "${builder}" help

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"--version VERSION"* ]]
  [[ "${output}" == *"--install-deps"* ]]
  [[ "${output}" == *"--generic"* ]]
  [[ "${output}" == *"--dry-run"* ]]
}

@test "dry-run build previews latest release workflow" {
  run bash "${builder}" --dry-run --version v0.11.2

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"[dry-run]"* ]]
  [[ "${output}" == *"Target platform:"* ]]
  [[ "${output}" == *"v0.11.2.tar.gz"* ]]
  [[ "${output}" == *"go build -trimpath"* ]]
  [[ "${output}" == *"dist/nebula-sync"* ]]
}

@test "help prints command list" {
  run bash "${installer}" help

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"Commands:"* ]]
  [[ "${output}" == *"install"* ]]
  [[ "${output}" == *"configure"* ]]
  [[ "${output}" == *"uninstall"* ]]
}

@test "dry-run configure previews temp env validation" {
  run bash "${installer}" --dry-run configure

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"detected target timezone"* ]]
  [[ "${output}" == *"prompt for sync type"* ]]
  [[ "${output}" == *"write temp env file"* ]]
  [[ "${output}" == *"validate temp env file"* ]]
  [[ "${output}" == *"nebula-sync.env"* ]]
}

@test "dry-run install does not require root" {
  run bash "${installer}" --dry-run install

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"[dry-run]"* ]]
  [[ "${output}" == *"apt-get update"* ]]
  [[ "${output}" == *"systemctl enable nebula-sync.timer"* ]]
}

@test "uninstall requires force even in dry-run mode" {
  run bash "${installer}" --dry-run uninstall

  [ "${status}" -ne 0 ]
  [[ "${output}" == *"uninstall requires --force"* ]]
}

@test "dry-run purge previews config removal" {
  run bash "${installer}" --dry-run uninstall --force --purge

  [ "${status}" -eq 0 ]
  [[ "${output}" == *"rm -rf -- /opt/nebula-sync"* ]]
  [[ "${output}" == *"rm -rf -- /etc/nebula-sync"* ]]
}
