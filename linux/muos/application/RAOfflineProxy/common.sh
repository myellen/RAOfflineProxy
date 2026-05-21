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
export APP_DIR ROOT_DIR

PKG_DIR="${APP_DIR}/app"
DATA_DIR="${APP_DIR}/data"
VENDOR_DIR="${APP_DIR}/vendor"
WHEELS_DIR="${APP_DIR}/wheels"
HOME_DIR="${APP_DIR}/home"
LOG_DIR="${APP_DIR}/logs"
RUN_LOG="${LOG_DIR}/launch.log"
# Single, can't-miss report at the SD card root for easy retrieval.
REPORT="${ROOT_DIR}/RAOFFLINEPROXY-REPORT.txt"

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
	export RAOFFLINEPROXY_ROMS_ROOT="${ROOT_DIR}/ROMS"

	# Patch the SAME retroarch.cfg muOS's own launcher loads. muOS reads
	# ${MUOS_SHARE_DIR}/info/config/retroarch.cfg (see script/control/retroarch.sh),
	# which is the canonical path; the SD's MUOS/info/config is the fallback when
	# func.sh isn't present. Prefer whichever actually exists so our cheevos
	# patch lands in the file RetroArch reads.
	local ra_cfg="${ROOT_DIR}/MUOS/info/config/retroarch.cfg"
	if [[ -n "${MUOS_SHARE_DIR:-}" ]]; then
		ra_cfg="${MUOS_SHARE_DIR}/info/config/retroarch.cfg"
	fi
	if [[ ! -f "${ra_cfg}" && -f "${ROOT_DIR}/MUOS/info/config/retroarch.cfg" ]]; then
		ra_cfg="${ROOT_DIR}/MUOS/info/config/retroarch.cfg"
	fi
	export RAOFFLINEPROXY_RETROARCH_CFG="${ra_cfg}"

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
			# shellcheck disable=SC2034  # consumed by callers as ${RESOLVED_PYTHON}
			RESOLVED_PYTHON="${bin}"
			log "using python ${bin} (${version})"
			return 0
		fi
		log "skipping ${bin}: python ${version} is older than 3.10"
	done

	log "no compatible python3 (>=3.10) found on PATH"
	return 1
}

# With a multi-ABI offline bundle, prepend the vendored pygame matching this
# interpreter's ABI (e.g. vendor/cp311) so `import pygame` works with no pip and
# no network on whichever Python minor version muOS ships.
select_vendor() {
	local py="$1" abi
	abi="$("${py}" -c 'import sys; print("cp%d%d" % sys.version_info[:2])' 2>/dev/null || true)"
	if [[ -n "${abi}" && -d "${VENDOR_DIR}/${abi}" ]]; then
		export PYTHONPATH="${VENDOR_DIR}/${abi}:${PYTHONPATH}"
		log "selected bundled pygame for ${abi}"
	else
		log "no bundled pygame for abi=${abi:-unknown}; relying on vendor/ or pip"
	fi
}

# The pygame wheel bundles a desktop SDL (x11/wayland only). muOS renders on the
# framebuffer via its own /usr/lib SDL (built with kmsdrm/fbcon), so overlay the
# system SDL onto the bundled libs. Best-effort and self-healing: it skips when
# no system SDL is present, and reverts if the overlay breaks `import pygame`.
link_system_sdl() {
	local py="$1" abi pglibs sysdir cand b live d
	local candidates=()
	abi="$("${py}" -c 'import sys; print("cp%d%d" % sys.version_info[:2])' 2>/dev/null || true)"

	# pygame may be the bundled per-ABI copy (vendor/<abi>) or one pip-installed
	# into vendor/ (flat). Prefer the per-ABI copy when we know the ABI.
	[[ -n "${abi}" ]] && candidates+=("${VENDOR_DIR}/${abi}/pygame.libs")
	candidates+=("${VENDOR_DIR}/pygame.libs")
	pglibs=""
	for cand in "${candidates[@]}"; do
		[[ -d "${cand}" ]] && { pglibs="${cand}"; break; }
	done
	[[ -n "${pglibs}" ]] || { log "overlay: no pygame.libs found under ${VENDOR_DIR}"; return 0; }

	sysdir=""
	for d in /usr/lib /usr/lib/aarch64-linux-gnu /lib /usr/local/lib; do
		if [[ -e "${d}/libSDL2-2.0.so.0" ]]; then sysdir="${d}"; break; fi
	done
	if [[ -z "${sysdir}" ]]; then
		log "no system SDL found; using bundled SDL (ok on desktops, not muOS framebuffer)"
		return 0
	fi

	# Recover from an interrupted previous overlay: if a .bundled backup exists
	# but its live file is gone (process killed between mv and ln), restore it,
	# so a half-applied overlay can't permanently break pygame.
	for b in "${pglibs}"/*.bundled; do
		[[ -e "${b}" ]] || continue
		live="${b%.bundled}"
		[[ -e "${live}" || -L "${live}" ]] || mv -f "${b}" "${live}"
	done

	_overlay() {  # $1 = bundled-name glob, $2 = system soname
		local soname="$2" f m matches
		# shellcheck disable=SC2206  # $1 is an intentional glob pattern
		matches=( "${pglibs}"/$1 )
		f=""
		for m in "${matches[@]}"; do
			[[ -e "${m}" && "${m}" != *.bundled ]] && { f="${m}"; break; }
		done
		if [[ -z "${f}" ]]; then
			log "overlay: no bundled ${soname} matched in ${pglibs}"
			return 0
		fi
		[[ -L "${f}" ]] && return 0  # already overlaid (idempotent)
		[[ -e "${sysdir}/${soname}" ]] || return 0
		mv -f "${f}" "${f}.bundled" 2>/dev/null || true
		ln -sf "${sysdir}/${soname}" "${f}"
		log "overlaid $(basename "${f}") -> ${sysdir}/${soname}"
	}
	# Overlay ONLY the core libSDL2 -- it is the lib that carries the video
	# driver (mali/fbcon). pygame's bundled SDL2_image/ttf/mixer are NOT
	# overlaid: they link the core SDL by the filename we symlink, so they end
	# up running against muOS's core SDL (ABI-stable) while we keep pygame's own
	# image/ttf/mixer rather than forcing muOS's possibly-older ones.
	# Glob matches both auditwheel name forms (libSDL2-2-<hash>.0.so... and
	# libSDL2-2.0-<hash>.so...).
	_overlay 'libSDL2-2*.so.*' libSDL2-2.0.so.0

	# If the system SDL is ABI-incompatible and breaks the import, roll back.
	if ! "${py}" -c 'import pygame' >/dev/null 2>&1; then
		log "system SDL overlay broke pygame import; reverting to bundled"
		for b in "${pglibs}"/*.bundled; do
			[[ -e "${b}" ]] && mv -f "${b}" "${b%.bundled}"
		done
		if "${py}" -c 'import pygame' >/dev/null 2>&1; then
			log "revert ok; using bundled SDL (menu may lack a framebuffer driver)"
		else
			log "WARNING: pygame import still failing after revert"
		fi
	fi
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

# Insurance only: if SDL's default video driver does not initialize, force the
# first alternative that does. Runs in a separate process (so the framebuffer is
# fully released before the menu starts) and is a strict no-op when the default
# works -- e.g. "mali" on muOS -- so it cannot break a device that already
# renders. It never selects dummy/offscreen (those are not a real display).
resolve_video_driver() {
	local py="$1" drv
	drv="$("${py}" - 2>/dev/null <<'PY'
import os, sys
os.environ.pop("SDL_VIDEODRIVER", None)
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
try:
    import pygame
except Exception:
    sys.exit(0)

def works(driver):
    if driver is None:
        os.environ.pop("SDL_VIDEODRIVER", None)
    else:
        os.environ["SDL_VIDEODRIVER"] = driver
    try:
        pygame.display.quit()
        pygame.display.init()
        used = pygame.display.get_driver()
        pygame.display.quit()
        return used
    except Exception:
        return None

default = works(None)
if default and default not in ("dummy", "offscreen"):
    sys.exit(0)  # default is a real display -> print nothing, keep it
for cand in ("kmsdrm", "fbcon", "mali", "x11", "wayland"):
    if works(cand):
        print(cand)
        break
PY
)"
	if [ -n "${drv}" ]; then
		export SDL_VIDEODRIVER="${drv}"
		log "default SDL video driver unusable; forcing SDL_VIDEODRIVER=${drv}"
	else
		log "using SDL default video driver"
	fi
}

# Always-on self-test: writes RAOFFLINEPROXY-REPORT.txt to the SD root + logs/.
run_diagnostics() {
	local py="$1"
	"${py}" "${APP_DIR}/diagnostics.py" >>"${RUN_LOG}" 2>&1 || true
}

# Last-resort report when diagnostics.py can't run (no Python at all). When a
# Python exists but is too old, prefer running diagnostics.py with it instead.
write_shell_report() {
	local found_py="" found_ver="" bin
	for bin in "${RAOFFLINEPROXY_PYTHON:-}" python3 python; do
		[[ -z "${bin}" ]] && continue
		command -v "${bin}" >/dev/null 2>&1 || continue
		found_py="$(command -v "${bin}")"
		found_ver="$("${bin}" -c 'import sys;print("%d.%d"%sys.version_info[:2])' 2>/dev/null || echo '?')"
		break
	done
	{
		echo "RAOfflineProxy muOS diagnostics report"
		echo "VERDICT: FAILED (no usable python3 >= 3.10)"
		echo "Send this whole file to debug."
		echo "============================================================"
		echo "time: $(date '+%Y-%m-%d %H:%M:%S')"
		echo "machine: $(uname -m)"
		echo "ROOT_DIR (SD mount): ${ROOT_DIR}"
		echo "APP_DIR: ${APP_DIR}"
		if [[ -n "${found_py}" ]]; then
			echo "[FAIL] python >= 3.10: found ${found_ver} at ${found_py} (need >= 3.10)"
		else
			echo "[FAIL] python: none of python3/python found on PATH"
		fi
		echo "PATH=${PATH}"
	} >"${REPORT}" 2>/dev/null || true
	cp -f "${REPORT}" "${LOG_DIR}/diagnostics.txt" 2>/dev/null || true
}
