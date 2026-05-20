#!/usr/bin/env bash
# Build the muOS .muxapp installer for RAOfflineProxy.
#
# Output: linux/muos/dist/RAOfflineProxy-<version>.muxapp
#
# A .muxapp is a plain zip whose contents are extracted relative to the muOS SD
# root, so the archive carries a top-level MUOS/application/RAOfflineProxy tree.
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
APP_REL="MUOS/application/${APP_NAME}"
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

# Shared Python core (stdlib-only proxy/service + SDL menu)
cp -r "${LINUX_DIR}/raofflineproxy" "${APP_DIR}/app/raofflineproxy"
cp "${LINUX_DIR}/requirements.txt" "${APP_DIR}/app/requirements.txt"
cp "${REPO_DIR}/docs/public/logo-320.png" "${APP_DIR}/app/raofflineproxy/logo-320.png"

# Applications-list glyph
cp "${REPO_DIR}/docs/public/logo-320.png" "${APP_DIR}/resources/raofflineproxy.png"

# Optional offline pygame wheels
if [[ -n "${WHEELS_SRC}" ]]; then
	mkdir -p "${APP_DIR}/wheels"
	cp "${WHEELS_SRC}"/*.whl "${APP_DIR}/wheels/"
	echo "Bundled $(ls "${APP_DIR}/wheels" | wc -l) wheel(s) from ${WHEELS_SRC}"
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
    for root, _dirs, files in os.walk(stage_dir):
        for name in files:
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
