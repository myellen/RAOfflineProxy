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
log "mux_launch start (ROOT_DIR=${ROOT_DIR:-}, APP_DIR=${APP_DIR})"

# Restore the muOS framebuffer/resolution on ANY exit (early failure or menu
# crash), so the device is never left on a black screen.
# shellcheck disable=SC2329  # invoked indirectly via `trap restore_fb EXIT`
restore_fb() {
	command -v FB_SWITCH >/dev/null 2>&1 || return 0
	command -v GET_VAR >/dev/null 2>&1 || return 0
	local stype="internal" mode w h
	mode="$(GET_VAR "global" "boot/device_mode" 2>/dev/null || echo 0)"
	[[ "${mode}" == "1" ]] && stype="external"
	w="$(GET_VAR "device" "screen/${stype}/width" 2>/dev/null || true)"
	h="$(GET_VAR "device" "screen/${stype}/height" 2>/dev/null || true)"
	[[ -n "${w}" && -n "${h}" ]] && FB_SWITCH "${w}" "${h}" 32 || true
}
trap restore_fb EXIT

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
	# No interpreter >= 3.10. Still produce the richest report we can: run
	# diagnostics.py with any python that exists (it flags the old version),
	# otherwise fall back to the pure-shell report.
	ANY_PY="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
	if [[ -n "${ANY_PY}" ]]; then
		run_diagnostics "${ANY_PY}"
	else
		write_shell_report
	fi
	log "FATAL: no usable python3 (>=3.10). Report: ${REPORT}"
	exit 1
fi

# Select the bundled pygame for this interpreter's ABI, then ensure pygame is
# importable (bundled, or pip-installed into vendor/ as a fallback).
select_vendor "${RESOLVED_PYTHON}"

if ! ensure_pygame "${RESOLVED_PYTHON}"; then
	run_diagnostics "${RESOLVED_PYTHON}"
	log "FATAL: pygame unavailable; cannot open the menu. Report: ${REPORT}"
	exit 1
fi

# Overlay muOS's framebuffer-capable system SDL onto whichever pygame we ended
# up with (must run AFTER ensure_pygame so a pip-installed pygame is covered).
link_system_sdl "${RESOLVED_PYTHON}"

# Write the diagnostics report (reflects the post-overlay state), then keep
# SDL's default video driver unless it can't init.
run_diagnostics "${RESOLVED_PYTHON}"
resolve_video_driver "${RESOLVED_PYTHON}"

log "launching menu"
"${RESOLVED_PYTHON}" -u -m raofflineproxy.main menu >>"${RUN_LOG}" 2>&1
status=$?
log "menu exited with status ${status}"
exit "${status}"
