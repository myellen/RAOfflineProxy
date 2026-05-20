#!/bin/bash
# Shared environment + runtime resolution for the RAOfflineProxy muOS app.
#
# This file is sourced by mux_launch.sh (and may be reused by future autostart
# or diagnostic hooks). It assumes APP_DIR is already exported by the caller; if
# not, it derives it from this script's own location.

if [[ -z "${APP_DIR:-}" ]]; then
	APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# muOS mounts SD1 at /mnt/mmc and SD2 at /mnt/sdcard. Prefer the mount this app
# was actually installed on so dual-SD setups resolve the right card.
detect_root_dir() {
	case "${APP_DIR}" in
	/mnt/sdcard/*) echo "/mnt/sdcard" ;;
	/mnt/mmc/*) echo "/mnt/mmc" ;;
	*)
		if [[ -d /mnt/sdcard/MUOS ]]; then
			echo "/mnt/sdcard"
		else
			echo "/mnt/mmc"
		fi
		;;
	esac
}

if [[ -z "${ROOT_DIR:-}" ]]; then
	ROOT_DIR="$(detect_root_dir)"
fi

PKG_DIR="${APP_DIR}/app"
DATA_DIR="${APP_DIR}/data"
VENDOR_DIR="${APP_DIR}/vendor"
WHEELS_DIR="${APP_DIR}/wheels"
HOME_DIR="${APP_DIR}/home"
LOG_DIR="${APP_DIR}/logs"
RUN_LOG="${LOG_DIR}/launch.log"

RESOLVED_PYTHON=""

log() {
	mkdir -p "${LOG_DIR}"
	printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"${RUN_LOG}"
}

prepare_env() {
	mkdir -p "${DATA_DIR}" "${VENDOR_DIR}" "${HOME_DIR}" "${LOG_DIR}"

	# Keep RAOfflineProxy's HOME inside the app dir so cache/login/token data
	# persists with the app instead of polluting the muOS system rootfs.
	export HOME="${HOME_DIR}"
	export XDG_CONFIG_HOME="${HOME_DIR}/.config"
	export RAOFFLINEPROXY_CONFIG_DIR="${DATA_DIR}"

	# Tell the shared Linux core which muOS card and paths to use, so it does
	# not have to guess between SD1 and SD2.
	export RAOFFLINEPROXY_MUOS_MOUNT="${ROOT_DIR}"
	export RAOFFLINEPROXY_RETROARCH_CFG="${ROOT_DIR}/MUOS/info/config/retroarch.cfg"
	export RAOFFLINEPROXY_ROMS_ROOT="${ROOT_DIR}/ROMS"

	# muOS keeps SDL libraries in /usr/lib; pygame finds them there.
	export PYSDL2_DLL_PATH="${PYSDL2_DLL_PATH:-/usr/lib}"

	# Make the bundled Python package and any locally installed wheels importable.
	export PYTHONPATH="${PKG_DIR}:${VENDOR_DIR}${PYTHONPATH:+:${PYTHONPATH}}"
}

# Pick a Python 3.10+ interpreter. muOS ships python3 on PATH; this also accepts
# an explicit override via RAOFFLINEPROXY_PYTHON for unusual builds.
resolve_python() {
	local candidates=()
	[[ -n "${RAOFFLINEPROXY_PYTHON:-}" ]] && candidates+=("${RAOFFLINEPROXY_PYTHON}")
	candidates+=("python3" "python")

	local bin version
	for bin in "${candidates[@]}"; do
		command -v "${bin}" >/dev/null 2>&1 || continue
		version="$("${bin}" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)" || continue
		if "${bin}" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3, 10) else 1)' 2>/dev/null; then
			RESOLVED_PYTHON="${bin}"
			log "using python ${bin} (${version})"
			return 0
		fi
		log "skipping ${bin}: python ${version} is older than 3.10"
	done

	log "no compatible python3 (>=3.10) found on PATH"
	return 1
}

# The proxy/service core is stdlib-only; only the on-device menu needs pygame.
# Try, in order: already importable -> bundled offline wheels -> pip from PyPI.
ensure_pygame() {
	local py="$1"

	if "${py}" -c 'import pygame' >/dev/null 2>&1; then
		log "pygame already importable"
		return 0
	fi

	if [[ -d "${WHEELS_DIR}" ]] && ls "${WHEELS_DIR}"/*.whl >/dev/null 2>&1; then
		log "installing pygame from bundled wheels"
		if "${py}" -m pip install --no-index --find-links "${WHEELS_DIR}" \
			--target "${VENDOR_DIR}" pygame >>"${RUN_LOG}" 2>&1; then
			"${py}" -c 'import pygame' >/dev/null 2>&1 && return 0
		fi
	fi

	log "installing pygame via pip (requires Wi-Fi)"
	if "${py}" -m pip install --target "${VENDOR_DIR}" pygame >>"${RUN_LOG}" 2>&1; then
		"${py}" -c 'import pygame' >/dev/null 2>&1 && return 0
	fi

	log "pygame is unavailable; the menu cannot start"
	return 1
}
