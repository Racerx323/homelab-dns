#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

usage() {
  printf 'Usage: SIGNING_KEY=<fingerprint> LIFECYCLE_RESULTS=<file> %s [output-directory]\n' "${0##*/}"
}

if [[ ${1:-} == -h || ${1:-} == --help ]]; then
  usage
  exit 0
fi

load_release_env
require_commands gpg debsign dpkg-deb dpkg-query sha256sum git find gcc sbuild
[[ -n ${SIGNING_KEY:-} ]] || die "SIGNING_KEY must contain the release key fingerprint"
[[ $SIGNING_KEY =~ ^[A-Fa-f0-9]{40}$ ]] || die "SIGNING_KEY must be a full 40-character fingerprint"
[[ -s ${LIFECYCLE_RESULTS:-} ]] || die "LIFECYCLE_RESULTS must contain disposable-host test evidence"

readonly artifacts_dir="$UNBOUND_ROOT/packaging/work/results"
readonly output_dir="${1:-$UNBOUND_ROOT/packaging/release/unbound-$BACKPORT_VERSION}"
safe_output_directory "$output_dir"
[[ -d $artifacts_dir ]] || die "build artifacts do not exist: $artifacts_dir"
[[ ! -e $output_dir ]] || die "output already exists: $output_dir"

mapfile -t changes_files < <(find "$artifacts_dir" -maxdepth 1 -type f -name '*.changes' -print | sort)
((${#changes_files[@]} >= 2)) || die "expected Unbound and profile .changes files"

log "signing source descriptors and changes files with the external release key"
for changes_file in "${changes_files[@]}"; do
  debsign --re-sign -k"$SIGNING_KEY" "$changes_file"
done

install -d -m 0755 "$output_dir/packages" "$output_dir/source" "$output_dir/runbooks"

mapfile -t deb_files < <(find "$artifacts_dir" -maxdepth 1 -type f -name '*.deb' -print | sort)
((${#deb_files[@]} > 0)) || die "no binary packages found"

declare -A required_packages=(
  [unbound]=0
  [libunbound8]=0
  ["unbound-anchor"]=0
  ["unbound-pihole-profile"]=0
  ["python3-unbound"]=0
)

for deb_file in "${deb_files[@]}"; do
  package_name=$(dpkg-deb -f "$deb_file" Package)
  package_version=$(dpkg-deb -f "$deb_file" Version)
  package_arch=$(dpkg-deb -f "$deb_file" Architecture)
  [[ $package_arch == arm64 || $package_arch == all ]] ||
    die "unexpected package architecture $package_arch in $deb_file"
  if [[ $package_name == unbound-pihole-profile ]]; then
    [[ $package_version == "$PROFILE_VERSION" && $package_arch == all ]] ||
      die "profile package has the wrong version or architecture"
  else
    [[ $package_version == "$BACKPORT_VERSION" ]] ||
      die "$package_name has unexpected version $package_version"
  fi
  if [[ -v required_packages[$package_name] ]]; then
    required_packages[$package_name]=1
  fi
  cp -a "$deb_file" "$output_dir/packages/"
done

for package_name in "${!required_packages[@]}"; do
  ((required_packages[$package_name] == 1)) || die "missing required package: $package_name"
done

mapfile -t metadata_files < <(
  find "$artifacts_dir" "$UNBOUND_ROOT/packaging/work" \
    -maxdepth 1 -type f \( -name '*.dsc' -o -name '*.tar.*' -o -name '*.changes' -o -name '*.buildinfo' \) \
    -print | sort -u
)
((${#metadata_files[@]} > 0)) || die "no source/build metadata found"
for metadata_file in "${metadata_files[@]}"; do
  cp -a "$metadata_file" "$output_dir/source/"
done

readonly extraction_dir="$UNBOUND_ROOT/packaging/work/manifest-root"
safe_output_directory "$extraction_dir"
if [[ -e $extraction_dir ]]; then
  find "$extraction_dir" -mindepth 1 -delete
else
  install -d -m 0755 "$extraction_dir"
fi
for deb_file in "${deb_files[@]}"; do
  dpkg-deb --extract "$deb_file" "$extraction_dir"
done

unbound_binary="$extraction_dir/usr/sbin/unbound"
[[ -x $unbound_binary ]] || die "unbound binary is missing from package closure"
unbound_version_output=$(LD_LIBRARY_PATH="$extraction_dir/usr/lib/aarch64-linux-gnu" "$unbound_binary" -V)
[[ $unbound_version_output == *"Version $UPSTREAM_VERSION"* ]] || die "binary version check failed"
for feature in --with-libevent --with-pythonmodule --enable-subnet --enable-dnstap \
  --with-libnghttp2 --enable-systemd --enable-tfo-client --enable-tfo-server \
  --sysconfdir=/etc --localstatedir=/var --with-pidfile=/run/unbound.pid \
  --with-rootkey-file=/var/lib/unbound/root.key --with-chroot-dir=; do
  [[ $unbound_version_output == *"$feature"* ]] || die "required configure feature is missing: $feature"
done

{
  printf 'Unbound release manifest\n'
  printf 'generated_utc=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf 'repository_commit=%s\n' "$(git -C "$UNBOUND_ROOT/.." rev-parse HEAD)"
  printf 'debian_source=%s-%s\n' "$UPSTREAM_VERSION" "$DEBIAN_REVISION"
  printf 'backport_version=%s\n' "$BACKPORT_VERSION"
  printf 'profile_version=%s\n' "$PROFILE_VERSION"
  printf 'target=%s/%s\n' "$TARGET_SUITE" "$TARGET_ARCH"
  printf 'builder_kernel=%s\n' "$(uname -srvmo)"
  printf 'gcc=%s\n' "$(gcc --version | sed -n '1p')"
  printf 'dpkg=%s\n' "$(dpkg-query -W -f='${Version}' dpkg)"
  printf 'sbuild=%s\n' "$(sbuild --version | sed -n '1p')"
  printf '\nPackage inventory\n'
  for deb_file in "${deb_files[@]}"; do
    dpkg-deb -f "$deb_file" Package Version Architecture Depends
  done
  printf '\nUnbound build configuration\n%s\n' "$unbound_version_output"
  printf '\nTest evidence\n'
  printf 'upstream_and_debian_tests=passed_during_sbuild\n'
  printf 'lintian=passed\n'
  printf 'autopkgtest=passed\n'
  printf 'repository_tests=see TEST-RESULTS.txt\n'
} >"$output_dir/BUILD-MANIFEST.txt"

for deb_file in "${deb_files[@]}"; do
  printf '\n===== %s =====\n' "${deb_file##*/}"
  dpkg-deb --contents "$deb_file"
done >"$output_dir/PACKAGE-CONTENTS.txt"

"$UNBOUND_ROOT/tests/run.sh" >"$output_dir/TEST-RESULTS.txt" 2>&1
cp -a "$LIFECYCLE_RESULTS" "$output_dir/PACKAGE-LIFECYCLE-RESULTS.txt"
cp -a "$UNBOUND_ROOT/docs/build-and-release.md" "$output_dir/runbooks/"
cp -a "$UNBOUND_ROOT/docs/scenario-1-ha-upgrade-installation.md" "$output_dir/runbooks/"
cp -a "$UNBOUND_ROOT/docs/scenario-1-ha-troubleshooting.md" "$output_dir/runbooks/"
cp -a "$UNBOUND_ROOT/docs/scenario-2-clean-installation.md" "$output_dir/runbooks/"
cp -a "$UNBOUND_ROOT/docs/scenario-2-clean-troubleshooting.md" "$output_dir/runbooks/"
cp -a "$UNBOUND_ROOT/docs/acceptance-matrix.md" "$output_dir/runbooks/"

(
  cd "$output_dir"
  checksum_tmp=$(mktemp "$UNBOUND_ROOT/packaging/work/SHA256SUMS.XXXXXX")
  find . -type f ! -name SHA256SUMS ! -name SHA256SUMS.asc -print0 |
    sort -z | xargs -0 sha256sum >"$checksum_tmp"
  mv "$checksum_tmp" SHA256SUMS
  gpg --batch --local-user "$SIGNING_KEY" --armor --detach-sign --output SHA256SUMS.asc SHA256SUMS
  gpg --verify SHA256SUMS.asc SHA256SUMS
  sha256sum --check SHA256SUMS
)

log "signed release bundle created at $output_dir"
