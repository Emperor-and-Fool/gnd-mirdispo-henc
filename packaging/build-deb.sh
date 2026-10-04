#!/bin/bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
version="3.8.0"
architecture="amd64"
package_name="mirdispo"
output_dir="${project_root}/outputs"
package_root="$(mktemp -d -t knd-package-XXXXXX)"

# Archives record when each file was last written, which is a record of when
# somebody sat at this machine. The release date from the AppStream metadata
# is used instead: it is already public, and it makes the archive the same
# whoever builds it.
release_date="$(sed -n 's/.*<release version="[^"]*" date="\([0-9-]*\)".*/\1/p' \
    "${project_root}/io.github.hencyber.Mirdispo.metainfo.xml" | head -n 1)"
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date -u -d "${release_date} 00:00:00" +%s)}"


cleanup() {
    case "${package_root}" in
        /tmp/knd-package-*) rm -rf "${package_root}" ;;
    esac
}
trap cleanup EXIT

install -d \
    "${package_root}/DEBIAN" \
    "${package_root}/usr/bin" \
    "${package_root}/usr/lib/mirdispo" \
    "${package_root}/usr/libexec" \
    "${package_root}/usr/share/applications" \
    "${package_root}/usr/share/icons" \
    "${package_root}/usr/share/metainfo" \
    "${package_root}/usr/share/doc/${package_name}" \
    "${output_dir}"

cp -R "${project_root}/src/mirdispo" \
    "${package_root}/usr/lib/mirdispo/"
find "${package_root}/usr/lib/mirdispo" -type d -name __pycache__ -prune -exec rm -rf {} +
find "${package_root}/usr/lib/mirdispo" -type f -exec chmod 0644 {} +

install -m 0755 "${project_root}/bin/mirdispo" \
    "${package_root}/usr/bin/mirdispo"
install -m 0755 "${project_root}/vendor/amd64/mirdispo-daemon" \
    "${package_root}/usr/libexec/mirdispo-daemon"
install -m 0755 "${project_root}/vendor/amd64/gnome-network-displays-stream" \
    "${package_root}/usr/libexec/gnome-network-displays-stream"
install -m 0644 "${project_root}/io.github.hencyber.Mirdispo.desktop" \
    "${package_root}/usr/share/applications/io.github.hencyber.Mirdispo.desktop"
install -m 0644 "${project_root}/io.github.hencyber.Mirdispo.metainfo.xml" \
    "${package_root}/usr/share/metainfo/io.github.hencyber.Mirdispo.metainfo.xml"
install -m 0644 "${project_root}/README.md" "${package_root}/usr/share/doc/${package_name}/README.md"
install -m 0644 "${project_root}/packaging/copyright" "${package_root}/usr/share/doc/${package_name}/copyright"
install -m 0644 "${project_root}/LICENSE" "${package_root}/usr/share/doc/${package_name}/LICENSE"
install -m 0644 "${project_root}/vendor/source/gnome-network-displays-0.99.0.tar.xz" \
    "${package_root}/usr/share/doc/${package_name}/gnome-network-displays-0.99.0.tar.xz"
for patch in "${project_root}"/packaging/patches/*.patch; do
    install -m 0644 "${patch}" "${package_root}/usr/share/doc/${package_name}/$(basename "${patch}")"
done

cp -R "${project_root}/assets/icons/hicolor" "${package_root}/usr/share/icons/"
find "${package_root}/usr/share/icons" -type d -exec chmod 0755 {} +
find "${package_root}/usr/share/icons" -type f -exec chmod 0644 {} +

cat >"${package_root}/DEBIAN/control" <<EOF
Package: ${package_name}
Version: ${version}
Section: kde
Priority: optional
Architecture: ${architecture}
Maintainer: Mirdispo contributors <229370513+hencyber@users.noreply.github.com>
Depends: python3 (>= 3.10), python3-pyqt6, python3-pyqt6.qtqml, python3-dbus, qml6-module-org-kde-kirigami, qml6-module-org-kde-desktop, network-manager, wpasupplicant | iwd, xdg-desktop-portal, xdg-desktop-portal-kde, libavahi-common3 (>= 0.6.16), libavahi-gobject0 (>= 0.6.22), libc6 (>= 2.34), libglib2.0-0t64 (>= 2.83.0), libgstreamer-plugins-base1.0-0 (>= 1.6.0), libgstreamer1.0-0 (>= 1.6.0), libgstrtspserver-1.0-0 (>= 1.8.0), libjson-glib-1.0-0 (>= 1.5.2), libnm0 (>= 1.40.4), libportal1 (>= 0.7), libprotobuf-c1 (>= 1.0.1), libpulse0 (>= 0.99.1), libsoup-3.0-0 (>= 3.0.3), gstreamer1.0-pipewire, gstreamer1.0-plugins-base, gstreamer1.0-plugins-good, gstreamer1.0-plugins-bad, gstreamer1.0-plugins-ugly
Recommends: gstreamer1.0-libav, gstreamer1.0-pulseaudio
Conflicts: gnome-network-displays, kde-network-displays
Replaces: kde-network-displays
Homepage: https://github.com/hencyber/mirdispo
Description: Plasma-native wireless display casting
 Discover and cast the Plasma desktop to Miracast and Chromecast receivers.
 The application uses Qt 6 and Kirigami and includes an open-source WFD
 streaming backend derived from GNOME Network Displays 0.99.0.
EOF

cat >"${package_root}/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    pkill -TERM -f '^/usr/libexec/mirdispo-daemon$' 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF

cat >"${package_root}/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    pkill -TERM -f '^/usr/libexec/mirdispo-daemon$' 2>/dev/null || true
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database -q /usr/share/applications || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
    gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor || true
fi
exit 0
EOF

chmod 0755 "${package_root}/DEBIAN/postinst" "${package_root}/DEBIAN/postrm"
(cd "${package_root}" && find usr -type f -print0 | sort -z | xargs -0 md5sum >DEBIAN/md5sums)
find "${package_root}" -exec touch -h -d "@${SOURCE_DATE_EPOCH}" {} +
dpkg-deb --root-owner-group --build "${package_root}" \
    "${output_dir}/${package_name}_${version}_${architecture}.deb"
