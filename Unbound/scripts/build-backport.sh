#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

usage() {
  printf 'Usage: %s [--skip-autopkgtest]\n' "${0##*/}"
}

run_autopkgtest=true
case ${1:-} in
  "") ;;
  --skip-autopkgtest) run_autopkgtest=false ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

require_root
load_release_env
assert_bookworm_arm64
require_commands dget dscverify dpkg-source dpkg-buildpackage dpkg-parsechangelog dch sbuild lintian

readonly work_dir="$UNBOUND_ROOT/packaging/work"
readonly download_dir="$work_dir/download"
readonly source_dir="$work_dir/unbound-$UPSTREAM_VERSION"
readonly result_dir="$work_dir/results"
safe_output_directory "$work_dir"
install -d -m 0755 "$download_dir" "$result_dir"

readonly dsc_name="unbound_${UPSTREAM_VERSION}-${DEBIAN_REVISION}.dsc"
readonly downloaded_dsc="$download_dir/$dsc_name"

if [[ ! -f $downloaded_dsc ]]; then
  log "downloading the pinned Debian source package"
  (cd "$download_dir" && dget --download-only "$SOURCE_DSC_URL")
fi

log "verifying Debian's source signature and signed file hashes"
dscverify "$downloaded_dsc"

log "resetting the generated source and result directories"
if [[ -e $source_dir ]]; then
  safe_output_directory "$source_dir"
  find "$source_dir" -depth -delete
fi
find "$result_dir" -mindepth 1 -delete
while IFS= read -r -d '' source_file; do
  cp -a "$source_file" "$work_dir/"
done < <(find "$download_dir" -maxdepth 1 -type f -name "unbound_${UPSTREAM_VERSION}*" -print0)
dpkg-source --extract "$work_dir/$dsc_name" "$source_dir"

current_version=$(dpkg-parsechangelog -l"$source_dir/debian/changelog" -SVersion)
[[ $current_version == "$UPSTREAM_VERSION-$DEBIAN_REVISION" ]] || die "unexpected source version: $current_version"
log "creating the exact Bookworm backport changelog entry"
(
  cd "$source_dir"
  DEBFULLNAME='Racerx323' \
    DEBEMAIL='Racerx323@users.noreply.github.com' \
    dch --newversion "$BACKPORT_VERSION" --distribution "$TARGET_SUITE" \
    'Rebuild Debian 1.25.1 for Debian 12 arm64 without packaging changes.'
)

log "building the signed-source candidate"
(
  cd "$source_dir"
  dpkg-buildpackage --build=source -us -uc
)

readonly backport_dsc="$work_dir/unbound_${BACKPORT_VERSION}.dsc"
[[ -f $backport_dsc ]] || die "source build did not create $backport_dsc"

log "running native arm64 build and package tests in the updated Bookworm chroot"
unset DEB_BUILD_OPTIONS
(
  cd "$result_dir"
  sbuild --dist="$TARGET_SUITE" --arch="$TARGET_ARCH" --arch-all --source \
    --apt-update --apt-distupgrade --run-lintian "$backport_dsc"
)

changes_file=$(find "$result_dir" -maxdepth 1 -type f -name "unbound_${BACKPORT_VERSION}_${TARGET_ARCH}.changes" -print -quit)
[[ -n $changes_file ]] || die "sbuild did not produce the expected arm64 .changes"
lintian --fail-on error --display-info --pedantic "$changes_file"

if [[ $run_autopkgtest == true ]]; then
  require_commands autopkgtest
  log "running Debian autopkgtests in the clean Bookworm arm64 schroot"
  autopkgtest "$changes_file" -- schroot "$SBUILD_CHROOT"
fi

log "backport artifacts are in $result_dir"
