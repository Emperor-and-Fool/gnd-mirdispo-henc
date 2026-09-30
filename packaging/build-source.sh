#!/bin/bash
# Builds the source archive.
#
# tar records the account name of whoever ran it as the owner of every file,
# which is information about that person rather than about the project, so the
# ownership is flattened and the entries are sorted for a stable result.
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${project_root}/src/mirdispo/__init__.py")"
output="${project_root}/outputs/mirdispo-${version}-source.tar.gz"

# Archives record when each file was last written, which is a record of when
# somebody sat at this machine. The release date from the AppStream metadata
# is used instead: it is already public, and it makes the archive the same
# whoever builds it.
release_date="$(sed -n 's/.*<release version="[^"]*" date="\([0-9-]*\)".*/\1/p' \
    "${project_root}/io.github.hencyber.Mirdispo.metainfo.xml" | head -n 1)"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date -u -d "${release_date} 00:00:00" +%s)}"


cd "${project_root}"
mkdir -p outputs

tar czf "${output}" \
    --owner=0 --group=0 --numeric-owner \
    --sort=name \
    --mtime="@${SOURCE_DATE_EPOCH}" \
    --exclude=__pycache__ \
    --exclude='*.pyc' \
    src bin tests packaging assets docs vendor/source Makefile README.md LICENSE \
    io.github.hencyber.Mirdispo.desktop \
    io.github.hencyber.Mirdispo.metainfo.xml

echo "Wrote ${output}"
