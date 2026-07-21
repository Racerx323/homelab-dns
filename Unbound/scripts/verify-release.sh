#!/usr/bin/env bash

set -Eeuo pipefail

# shellcheck disable=SC1091
source "$(dirname "$0")/lib/common.sh"

[[ $# -eq 1 ]] || die "usage: ${0##*/} BUNDLE_DIRECTORY"
require_commands gpg sha256sum dpkg-deb
load_release_env
verify_bundle "$1"

found_unbound=false
found_profile=false
while IFS= read -r -d '' package_file; do
  package_name=$(dpkg-deb -f "$package_file" Package)
  package_version=$(dpkg-deb -f "$package_file" Version)
  package_arch=$(dpkg-deb -f "$package_file" Architecture)
  [[ $package_arch == "$TARGET_ARCH" || $package_arch == all ]] || die "wrong architecture: $package_file"
  case $package_name in
    unbound)
      [[ $package_version == "$BACKPORT_VERSION" ]] || die "wrong Unbound version"
      found_unbound=true
      ;;
    unbound-pihole-profile)
      [[ $package_version == "$PROFILE_VERSION" && $package_arch == all ]] || die "wrong profile version"
      found_profile=true
      ;;
  esac
done < <(find "$1/packages" -maxdepth 1 -type f -name '*.deb' -print0)

[[ $found_unbound == true && $found_profile == true ]] || die "bundle is missing required packages"
log "release signature, hashes, versions, and architectures are valid"
