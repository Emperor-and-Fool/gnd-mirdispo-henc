#!/bin/bash
# Looks for traces of whoever built the tree.
#
# Build directories, Python caches, debug information and tar archives all
# record the account name and absolute paths they were produced under. None of
# that belongs to the project, so this reports anything that carries it.
#
# Run it before sharing the tree or publishing an archive.
set -uo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "${root}"

# The shell may define grep as a function that filters its own output, which
# is how an earlier audit of this tree reported a clean result it had not
# earned. Use the binary.
GREP=/usr/bin/grep
findings=0

report() {
    findings=$((findings + 1))
    printf '  %s\n' "$1"
}

echo "Scanning ${root}"

# Account names and home directory paths, including this machine's own.
for pattern in "$(id -un)" "$(hostname)" "/home/" "/root/" "/Users/"; do
    [ -n "${pattern}" ] || continue
    hits="$("${GREP}" -rl -- "${pattern}" . 2>/dev/null \
        | "${GREP}" -v -e '^./outputs/' -e '^./packaging/privacy-audit.sh$' || true)"
    [ -n "${hits}" ] && report "'${pattern}' appears in: $(echo "${hits}" | tr '\n' ' ')"
done

# Addresses that identify a network.
for pattern in '192\.168\.[0-9]+\.[0-9]+' '10\.[0-9]+\.[0-9]+\.[0-9]+' '([0-9a-f]{2}:){5}[0-9a-f]{2}'; do
    # 00:00:5E:00:53:xx is the range RFC 7042 sets aside for documentation.
    hits="$("${GREP}" -rlE -- "${pattern}" --exclude-dir=gnd-source --exclude-dir=outputs . 2>/dev/null \
        | "${GREP}" -v '^./packaging/privacy-audit.sh$' \
        | while read -r file; do
              "${GREP}" -oEi -- "${pattern}" "${file}" \
                  | "${GREP}" -qvi '^00:00:5e:00:53:' && echo "${file}"
          done || true)"
    [ -n "${hits}" ] && report "pattern ${pattern} appears in: $(echo "${hits}" | tr '\n' ' ')"
done

# Archives record the builder as the owner of every entry.
for archive in outputs/*.tar.gz; do
    [ -e "${archive}" ] || continue
    owners="$(tar tvzf "${archive}" 2>/dev/null | awk '{print $2}' | sort -u | tr '\n' ' ')"
    case "${owners}" in
        "0/0 "|"") ;;
        *) report "${archive} is owned by ${owners}instead of 0/0" ;;
    esac
done

for package in outputs/*.deb; do
    [ -e "${package}" ] || continue
    owners="$(dpkg-deb --fsys-tarfile "${package}" 2>/dev/null | tar tv 2>/dev/null | awk '{print $2}' | sort -u | tr '\n' ' ')"
    case "${owners}" in
        "root/root "|"") ;;
        *) report "${package} is owned by ${owners}instead of root/root" ;;
    esac
done

# Archives were excluded from the scan above because they are compressed, so
# their contents are checked by unpacking them.
staging="$(mktemp -d)"
trap 'rm -rf "${staging}"' EXIT
for archive in outputs/*.tar.gz; do
    [ -e "${archive}" ] || continue
    rm -rf "${staging:?}/x"; mkdir -p "${staging}/x"
    tar xzf "${archive}" -C "${staging}/x" 2>/dev/null || continue
    hits="$("${GREP}" -rl -- "$(id -un)" "${staging}/x" 2>/dev/null | head -n 3 || true)"
    [ -n "${hits}" ] && report "${archive} contains the account name"
done
for package in outputs/*.deb; do
    [ -e "${package}" ] || continue
    rm -rf "${staging:?}/y"; mkdir -p "${staging}/y"
    dpkg-deb -x "${package}" "${staging}/y" 2>/dev/null || continue
    hits="$("${GREP}" -rl -- "$(id -un)" "${staging}/y" 2>/dev/null | head -n 3 || true)"
    [ -n "${hits}" ] && report "${package} contains the account name"
done

# A spread of modification times is a record of when somebody was working.
for archive in outputs/*.tar.gz; do
    [ -e "${archive}" ] || continue
    stamps="$(tar tvzf "${archive}" 2>/dev/null | awk '{print $4" "$5}' | sort -u | wc -l)"
    [ "${stamps}" -gt 1 ] && report "${archive} carries ${stamps} different timestamps"
done
for package in outputs/*.deb; do
    [ -e "${package}" ] || continue
    stamps="$(dpkg-deb --fsys-tarfile "${package}" 2>/dev/null | tar tv 2>/dev/null | awk '{print $4" "$5}' | sort -u | wc -l)"
    [ "${stamps}" -gt 1 ] && report "${package} carries ${stamps} different timestamps"
done

# Generated images carry the time and tool they were made with.
python3 - <<'PY' || true
import struct, pathlib, sys
carriers = []
for path in sorted(pathlib.Path("assets").rglob("*.png")):
    data = path.read_bytes()
    offset = 8
    while offset < len(data) - 8:
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        kind = data[offset + 4:offset + 8]
        if kind in (b"tEXt", b"iTXt", b"zTXt", b"tIME"):
            carriers.append(str(path))
            break
        offset += 12 + length
if carriers:
    print("  images carry metadata: " + " ".join(carriers))
    sys.exit(1)
PY
[ $? -ne 0 ] && findings=$((findings + 1))

if [ "${findings}" -eq 0 ]; then
    echo "Clean: nothing identifying the machine or the account was found."
else
    echo "${findings} finding(s). 'make clean' removes build output, which is the usual cause."
    exit 1
fi
