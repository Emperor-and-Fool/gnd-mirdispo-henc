#!/bin/bash
# Build and run the C regression tests against the patched upstream backend.
#
# Usage: tests/run-c-tests.sh [build-dir]
#
# The build directory defaults to work/gnd-build, which is produced by
# configuring work/gnd-source with meson.
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
build_dir="${1:-${project_root}/work/gnd-build}"
source_dir="${project_root}/work/gnd-source"
out_dir="${project_root}/work"

if [ ! -f "${build_dir}/build.ninja" ]; then
    echo "No backend build found at ${build_dir}" >&2
    exit 1
fi

ninja -C "${build_dir}" >/dev/null

# Reuse the compiler and linker arguments meson generated for the backend.
cflags="$(python3 - "${build_dir}/compile_commands.json" <<'PY'
import json, shlex, sys
db = json.load(open(sys.argv[1]))
for entry in db:
    if entry["file"].endswith("nd-pulseaudio.c") and "stream" in entry["output"]:
        args = shlex.split(entry["command"])
        keep, skip = [], False
        for i, a in enumerate(args[1:]):
            if skip:
                skip = False
                continue
            if a in ("-c", "-o", "-MD", "-MQ", "-MF"):
                skip = a not in ("-c", "-MD")
                continue
            if a.endswith(".c") or a.endswith(".o") or a.endswith(".o.d"):
                continue
            keep.append(a)
        print(" ".join(keep))
        break
PY
)"
link_args="$(awk '/^build src\/gnome-network-displays-stream:/ {found=1} found && /^ LINK_ARGS = / {sub(/^ LINK_ARGS = /, ""); print; exit}' "${build_dir}/build.ninja")"

objects=()
for obj in "${build_dir}"/src/gnome-network-displays-stream.p/*.o; do
    case "$(basename "${obj}")" in
        stream_main.c.o) continue ;;
    esac
    objects+=("${obj}")
done
for obj in "${build_dir}"/src/gnome-network-displays-daemon.p/nd-systemd-helpers.c.o \
           "${build_dir}"/src/gnome-network-displays-daemon.p/meson-generated_.._nd-dbus-systemd.c.o \
           "${build_dir}"/src/gnome-network-displays-daemon.p/meson-generated_.._nd-dbus-manager.c.o; do
    [ -f "${obj}" ] && objects+=("${obj}")
done

failures=0
for test_source in "${project_root}"/tests/*.c; do
    name="$(basename "${test_source}" .c)"
    binary="${out_dir}/${name}"

    # The linker arguments meson generated are relative to the build
    # directory, so the link has to run from there.
    # shellcheck disable=SC2086
    (cd "${build_dir}" && cc ${cflags} \
        -I"${source_dir}/src" -I"${source_dir}/src/wfd" -I"${source_dir}/src/cc" \
        -I"${build_dir}" -I"${build_dir}/src" \
        -o "${binary}" "${test_source}" "${objects[@]}" \
        ${link_args})

    set +e
    (cd "${build_dir}" && "${binary}")
    status=$?
    set -e

    case ${status} in
        0) echo "PASS ${name}" ;;
        77) echo "SKIP ${name} (environment unavailable)" ;;
        *) echo "FAIL ${name} (exit ${status})"; failures=$((failures + 1)) ;;
    esac
done

if [ ${failures} -ne 0 ]; then
    echo "${failures} C test(s) failed" >&2
    exit 1
fi
