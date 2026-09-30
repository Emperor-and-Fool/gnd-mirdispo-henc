#!/bin/bash
# Builds Mirdispo into the Flatpak repository that GitHub Pages serves, and
# writes the files people install it from.
#
# Usage: packaging/publish-flatpak-repo.sh <site-dir> [<gpg-key-id> <gpg-homedir>]
#
# <site-dir> holds the published site. An existing repository in
# <site-dir>/repo is updated in place, so installed copies see a new commit
# and update rather than reinstall. Without a key the repository is left
# unsigned, which is only good for testing: the published one is always
# signed, and the key's public half is flatpak/mirdispo-repo.gpg.
#
# FLATPAK_BUILDER may name the builder to use, for instance
# "flatpak run org.flatpak.Builder" on a machine without flatpak-builder.
set -euo pipefail

site="$(realpath -m "$1")"
key="${2:-}"
gpg_home="${3:-}"
project_root="$(cd "$(dirname "$0")/.." && pwd)"
builder="${FLATPAK_BUILDER:-flatpak-builder}"
url="${MIRDISPO_REPO_URL:-https://hencyber.github.io/mirdispo}"
app_id="io.github.hencyber.Mirdispo"

sign=()
if [ -n "${key}" ]; then
    sign=(--gpg-sign="${key}")
    [ -n "${gpg_home}" ] && sign+=(--gpg-homedir="${gpg_home}")
fi

mkdir -p "${site}"
# The published repository comes back from git, which keeps no empty
# directories, and OSTree refuses a repository without them.
if [ -d "${site}/repo" ]; then
    mkdir -p "${site}/repo/refs/heads" "${site}/repo/refs/mirrors" "${site}/repo/refs/remotes" \
        "${site}/repo/objects" "${site}/repo/state" "${site}/repo/tmp/cache" "${site}/repo/extensions"
fi
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo

# shellcheck disable=SC2086
${builder} --user --install-deps-from=flathub --disable-rofiles-fuse --force-clean \
    --default-branch=stable --state-dir="${project_root}/work/flatpak-state" \
    "${sign[@]}" --repo="${site}/repo" \
    "${project_root}/work/flatpak-publish" "${project_root}/flatpak/${app_id}.yml"

# Two versions are kept, so an update can be served as a small delta and a
# broken release can still be rolled back from, without the site growing
# with every release.
flatpak build-update-repo "${sign[@]}" --title="Mirdispo" --default-branch=stable \
    --generate-static-deltas --prune --prune-depth=2 "${site}/repo"

# The install files carry the public key, so installing needs no step
# beyond opening one of them.
gpg_line=""
if [ -f "${project_root}/flatpak/mirdispo-repo.gpg" ]; then
    gpg_line="GPGKey=$(base64 -w0 "${project_root}/flatpak/mirdispo-repo.gpg")"
fi

cat >"${site}/mirdispo.flatpakref" <<EOF
[Flatpak Ref]
Name=${app_id}
Branch=stable
Title=Mirdispo
Url=${url}/repo/
SuggestRemoteName=mirdispo
Homepage=https://github.com/hencyber/mirdispo
Icon=${url}/icon.png
RuntimeRepo=https://dl.flathub.org/repo/flathub.flatpakrepo
IsRuntime=false
${gpg_line}
EOF

cat >"${site}/mirdispo.flatpakrepo" <<EOF
[Flatpak Repo]
Title=Mirdispo
Url=${url}/repo/
Homepage=https://github.com/hencyber/mirdispo
Comment=Share a Plasma desktop with Miracast and Chromecast displays
Icon=${url}/icon.png
${gpg_line}
EOF

cp "${project_root}/flatpak/site/index.html" "${site}/index.html"
cp "${project_root}/assets/icons/hicolor/256x256/apps/${app_id}.png" "${site}/icon.png"
# GitHub Pages would otherwise hide paths that start with an underscore.
touch "${site}/.nojekyll"
