#!/bin/bash
# HELP: Earn softcore RetroAchievements offline (RAOfflineProxy)
# ICON: raofflineproxy
#
# muOS entry point for RAOfflineProxy. muOS lists every
# MUOS/application/<Name>/mux_launch.sh under Applications and runs this script
# fullscreen when the entry is selected.

set -u

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
export APP_DIR

# func.sh gives us GET_VAR / FB_SWITCH on a real muOS device. Guard the source
# so this script can also be exercised off-device.
FUNC_FILE="/opt/muos/script/var/func.sh"
if [[ -f "${FUNC_FILE}" ]]; then
	# shellcheck disable=SC1090
	. "${FUNC_FILE}"
	echo app >/tmp/act_go
	ROOT_DIR="$(GET_VAR "device" "storage/rom/mount" 2>/dev/null || true)"
	export ROOT_DIR
fi

# shellcheck source=common.sh
. "${APP_DIR}/common.sh"

prepare_env
log "mux_launch start (ROOT_DIR=${ROOT_DIR}, APP_DIR=${APP_DIR})"

# Refresh the Applications-list glyph so the entry shows an icon.
GLYPH_DIR="/opt/muos/default/MUOS/theme/active/glyph/muxapp"
if [[ -d "${GLYPH_DIR}" && -f "${APP_DIR}/resources/raofflineproxy.png" ]]; then
	cp -f "${APP_DIR}/resources/raofflineproxy.png" "${GLYPH_DIR}/raofflineproxy.png" 2>/dev/null || true
fi

cd "${PKG_DIR}" || {
	log "FATAL: package dir ${PKG_DIR} missing"
	exit 1
}

if ! resolve_python; then
	log "FATAL: no usable python3 (>=3.10); aborting. See ${RUN_LOG}"
	exit 1
fi

if ! ensure_pygame "${RESOLVED_PYTHON}"; then
	log "FATAL: pygame unavailable; cannot open the menu. See ${RUN_LOG}"
	exit 1
fi

log "launching menu"
"${RESOLVED_PYTHON}" -u -m raofflineproxy.main menu >>"${RUN_LOG}" 2>&1
status=$?
log "menu exited with status ${status}"

# Restore the muOS framebuffer/resolution after our fullscreen SDL session.
if command -v FB_SWITCH >/dev/null 2>&1 && command -v GET_VAR >/dev/null 2>&1; then
	SCREEN_TYPE="internal"
	DEVICE_MODE="$(GET_VAR "global" "boot/device_mode" 2>/dev/null || echo 0)"
	[[ "${DEVICE_MODE}" == "1" ]] && SCREEN_TYPE="external"
	FB_W="$(GET_VAR "device" "screen/${SCREEN_TYPE}/width" 2>/dev/null || true)"
	FB_H="$(GET_VAR "device" "screen/${SCREEN_TYPE}/height" 2>/dev/null || true)"
	if [[ -n "${FB_W}" && -n "${FB_H}" ]]; then
		FB_SWITCH "${FB_W}" "${FB_H}" 32 || true
	fi
fi

exit "${status}"
