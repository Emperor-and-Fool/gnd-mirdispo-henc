#!/bin/bash
# Writes outputs/mirdispo-<version>-flatpak-sources.tar: the source of every
# library the Flatpak bundles besides Mirdispo and its engine, which the
# licences of those libraries require to be offered alongside it. Attach it
# to each release.
#
# Every archive is taken from the URL in the Flatpak manifest and checked
# against the checksum there. PyQt6 and PyQt6-sip come from the PyQt base app
# and are fetched from PyPI.
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
version="$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "${project_root}/src/mirdispo/__init__.py")"
name="mirdispo-${version}-flatpak-sources"
work="$(mktemp -d)"
trap 'rm -rf "${work:?}"' EXIT
dest="${work}/${name}"
mkdir -p "${dest}" "${project_root}/outputs"

python3 - "${dest}" "${project_root}/flatpak/io.github.hencyber.Mirdispo.yml" <<'EOF'
import hashlib, json, pathlib, sys, urllib.request
import yaml

dest = pathlib.Path(sys.argv[1])
manifest = yaml.safe_load(open(sys.argv[2]))
renamed = {"libndp": "libndp-1.9.tar.gz"}

def fetch(url, sha256, filename):
    data = urllib.request.urlopen(url, timeout=120).read()
    if hashlib.sha256(data).hexdigest() != sha256:
        sys.exit(f"checksum mismatch for {url}")
    (dest / filename).write_bytes(data)

for module in manifest["modules"]:
    for source in module.get("sources", []):
        if source.get("type") == "archive" and "url" in source:
            fetch(source["url"], source["sha256"],
                  renamed.get(module["name"], source["url"].rsplit("/", 1)[1]))

for package, release in (("PyQt6", "6.11.0"), ("PyQt6-sip", "13.12.0")):
    info = json.load(urllib.request.urlopen(f"https://pypi.org/pypi/{package}/{release}/json", timeout=60))
    sdist = next(u for u in info["urls"] if u["packagetype"] == "sdist")
    fetch(sdist["url"], sdist["digests"]["sha256"], sdist["filename"])
EOF

cp "${project_root}/vendor/source/gnome-network-displays-0.99.0.tar.xz" \
   "${project_root}"/packaging/patches/*.patch \
   "${project_root}/flatpak/io.github.hencyber.Mirdispo.yml" "${dest}/"
last_patch="$(basename "$(ls "${project_root}"/packaging/patches/*.patch | tail -n 1)" | cut -c1-4)"

cat >"${dest}/README" <<EOF
Complete source for the Mirdispo ${version} Flatpak

The Flatpak published at https://hencyber.github.io/mirdispo is built from
flatpak/io.github.hencyber.Mirdispo.yml in the Mirdispo repository at tag
v${version}, on the org.kde.Platform 6.11 runtime and the
com.riverbankcomputing.PyQt.BaseApp 6.11 base, both from Flathub.

This archive holds the source of everything the Flatpak itself contains that
is not Mirdispo's own code (which is the repository at that tag):

  GNOME Network Displays 0.99.0 and patches 0001-${last_patch}   GPL-3.0-or-later
  avahi 0.8                                              LGPL-2.1-or-later
  NetworkManager 1.52.2 (only libnm is shipped)          LGPL-2.1-or-later
  libportal 0.11.0                                       LGPL-3.0-only
  gst-rtsp-server 1.26.11                                LGPL-2.1-or-later
  libndp 1.9                                             LGPL-2.1-or-later
  protobuf-c 1.5.2                                       BSD-2-Clause
  dbus-python 1.5.0                                      MIT
  PyGObject 3.58.0                                       LGPL-2.1-or-later
  PyQt6 6.11.0 (from the base app)                       GPL-3.0-only
  PyQt6-sip 13.12.0 (from the base app)                  BSD-2-Clause

Each library's licence is inside its archive, and is also installed in the
Flatpak under /app/share/licenses/io.github.hencyber.Mirdispo/.
EOF

release_date="$(sed -n 's/.*<release version="[^"]*" date="\([0-9-]*\)".*/\1/p' \
    "${project_root}/io.github.hencyber.Mirdispo.metainfo.xml" | head -n 1)"
tar --owner=0 --group=0 --numeric-owner --sort=name \
    --mtime="@$(date -u -d "${release_date} 00:00:00" +%s)" \
    -C "${work}" -cf "${project_root}/outputs/${name}.tar" "${name}"
echo "${project_root}/outputs/${name}.tar"
