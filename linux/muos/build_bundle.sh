#!/usr/bin/env bash
# Build the muOS .muxapp installer for RAOfflineProxy.
#
# Output: linux/muos/dist/RAOfflineProxy-<version>.muxapp
#
# A .muxapp is a plain zip that muOS Archive Manager extracts INTO
# MUOS/application/, so the archive must carry the app folder at its root:
# RAOfflineProxy/mux_launch.sh (NOT MUOS/application/RAOfflineProxy/...).
# Install it by copying the .muxapp into the ARCHIVE folder on the card and
# running it from Applications > Archive Manager.
#
# Optional: bundle pygame wheels for fully offline first-run (no Wi-Fi needed):
#   ./build_bundle.sh --with-pygame /path/to/aarch64/wheel/dir
# The directory must contain a pygame aarch64 wheel matching the device's
# CPython ABI (e.g. cp311) plus its dependencies.
set -euo pipefail

VERSION="1.0.0-alpha1"
APP_NAME="RAOfflineProxy"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LINUX_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_DIR="$(cd "${LINUX_DIR}/.." && pwd)"
DIST_DIR="${SCRIPT_DIR}/dist"
STAGE_DIR="${DIST_DIR}/stage"
# App folder sits at the archive root; Archive Manager drops it into
# MUOS/application/ on the device.
APP_REL="${APP_NAME}"
APP_DIR="${STAGE_DIR}/${APP_REL}"
MUXAPP_PATH="${DIST_DIR}/${APP_NAME}-${VERSION}.muxapp"

WHEELS_SRC=""
if [[ "${1:-}" == "--with-pygame" ]]; then
	WHEELS_SRC="${2:?--with-pygame requires a wheel directory}"
fi

rm -rf "${STAGE_DIR}"
rm -f "${MUXAPP_PATH}"
mkdir -p "${APP_DIR}/app" "${APP_DIR}/resources"

export COPYFILE_DISABLE=1

# muOS launcher + shared shell helpers
cp "${SCRIPT_DIR}/application/${APP_NAME}/mux_launch.sh" "${APP_DIR}/mux_launch.sh"
cp "${SCRIPT_DIR}/application/${APP_NAME}/common.sh" "${APP_DIR}/common.sh"
cp "${SCRIPT_DIR}/application/${APP_NAME}/diagnostics.py" "${APP_DIR}/diagnostics.py"

# Shared Python core (stdlib-only proxy/service + SDL menu)
cp -r "${LINUX_DIR}/raofflineproxy" "${APP_DIR}/app/raofflineproxy"
cp "${LINUX_DIR}/requirements.txt" "${APP_DIR}/app/requirements.txt"
cp "${REPO_DIR}/docs/public/logo-320.png" "${APP_DIR}/app/raofflineproxy/logo-320.png"

# Applications-list glyph
cp "${REPO_DIR}/docs/public/logo-320.png" "${APP_DIR}/resources/raofflineproxy.png"

# Optional offline pygame: unpack each wheel into vendor/<pytag>/ (e.g.
# vendor/cp311) so the device can `import pygame` directly with no pip and no
# network, regardless of which Python minor version muOS ships. The launcher
# picks the matching vendor/<abi> dir at runtime. The .whl files are also kept
# in wheels/ as a pip-based fallback. Pass a directory containing wheels for one
# or more ABIs (cp310..cp313). This mirrors how RomM ships its deps on muOS.
if [[ -n "${WHEELS_SRC}" ]]; then
	mkdir -p "${APP_DIR}/vendor"
	python3 - "${WHEELS_SRC}" "${APP_DIR}/vendor" <<'PY'
import glob, os, shutil, sys, zipfile
src, vendor = sys.argv[1], sys.argv[2]
for whl in sorted(glob.glob(os.path.join(src, "*.whl"))):
    name = os.path.basename(whl)
    # filename: <pkg>-<ver>[-<build>]-<pytag>-<abitag>-<platform>.whl
    # The python tag is always the 3rd field from the end.
    parts = name[: -len(".whl")].split("-")
    pytag = parts[-3] if len(parts) >= 5 else "any"
    # cpXY wheels go in a per-ABI dir (selected at runtime by select_vendor);
    # pure-python (pyN) deps go in the flat vendor/ root, which is on PYTHONPATH,
    # so they're importable regardless of the device's ABI.
    dest = os.path.join(vendor, pytag) if pytag.startswith("cp") else vendor
    os.makedirs(dest, exist_ok=True)
    with zipfile.ZipFile(whl) as zf:
        zf.extractall(dest)
    # Drop weight the on-device menu never needs.
    for junk in ("pygame/examples", "pygame/tests", "pygame/docs", "pygame/include"):
        shutil.rmtree(os.path.join(dest, junk), ignore_errors=True)
    print(f"unpacked {name} -> {os.path.relpath(dest, os.path.dirname(vendor))}/")
PY
	echo "Bundled pygame for ABIs: $(ls "${APP_DIR}/vendor")"
fi

find "${APP_DIR}/app" -name "__pycache__" -type d -prune -exec rm -rf {} +
find "${APP_DIR}/app" -name "*.pyc" -delete

chmod +x "${APP_DIR}/mux_launch.sh" "${APP_DIR}/common.sh"

# Zip the staged tree into the .muxapp (no external `zip` dependency).
python3 - "$STAGE_DIR" "$MUXAPP_PATH" <<'PY'
import os
import stat
import sys
import zipfile

stage_dir, out_path = sys.argv[1], sys.argv[2]
with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
    # Sorted walk so the archive's member order is reproducible.
    for root, dirs, files in os.walk(stage_dir):
        dirs.sort()
        for name in sorted(files):
            abs_path = os.path.join(root, name)
            arcname = os.path.relpath(abs_path, stage_dir)
            info = zipfile.ZipInfo(arcname)
            mode = os.stat(abs_path).st_mode
            # Preserve the executable bit on the shell scripts.
            info.external_attr = (mode & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with open(abs_path, "rb") as fh:
                zf.writestr(info, fh.read())
print(f"Wrote {out_path}")
PY

rm -rf "${STAGE_DIR}"
echo "Created ${MUXAPP_PATH}"
