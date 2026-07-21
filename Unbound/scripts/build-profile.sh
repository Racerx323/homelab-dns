#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

require_root
load_release_env
assert_bookworm_arm64
require_commands dpkg-buildpackage dpkg-parsechangelog sbuild lintian autopkgtest

readonly profile_dir="$UNBOUND_ROOT/packaging/unbound-pihole-profile"
readonly work_dir="$UNBOUND_ROOT/packaging/work"
readonly result_dir="$work_dir/results"
readonly build_source_dir="$work_dir/profile-source"
install -d -m 0755 "$result_dir"

profile_version=$(dpkg-parsechangelog -l"$profile_dir/debian/changelog" -SVersion)
# PROFILE_VERSION is loaded from validated release.env by load_release_env.
# shellcheck disable=SC2153
[[ $profile_version == "$PROFILE_VERSION" ]] ||
  die "profile changelog version $profile_version does not match $PROFILE_VERSION"

log "building the profile source package"
if [[ -e $build_source_dir ]]; then
  safe_output_directory "$build_source_dir"
  find "$build_source_dir" -depth -delete
fi
install -d -m 0755 "$build_source_dir"
cp -a "$profile_dir/." "$build_source_dir/"
(
  cd "$build_source_dir"
  dpkg-buildpackage --build=source -us -uc
)

readonly profile_dsc="$work_dir/unbound-pihole-profile_${PROFILE_VERSION}.dsc"
[[ -f $profile_dsc ]] || die "profile source build did not create $profile_dsc"

log "building and linting the architecture-independent package in Bookworm"
(
  cd "$result_dir"
  sbuild --dist="$TARGET_SUITE" --arch="$TARGET_ARCH" --arch-all --no-arch-any \
    --apt-update --apt-distupgrade --run-lintian "$profile_dsc"
)

changes_file=$(find "$result_dir" -maxdepth 1 -type f -name "unbound-pihole-profile_${PROFILE_VERSION}_all.changes" -print -quit)
[[ -n $changes_file ]] || die "profile build did not produce the expected .changes"
lintian --fail-on error --display-info --pedantic "$changes_file"
unbound_changes=$(find "$result_dir" -maxdepth 1 -type f -name "unbound_${BACKPORT_VERSION}_${TARGET_ARCH}.changes" -print -quit)
[[ -n $unbound_changes ]] || die "build the Unbound backport before testing the profile"
autopkgtest "$changes_file" "$unbound_changes" -- schroot "$SBUILD_CHROOT"

log "profile artifacts are in $result_dir"
