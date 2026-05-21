import os
from pathlib import Path

from .config import (
    DEFAULT_ONION_STARTUP_SCRIPT,
    MUOS_APP_SUBPATH,
    detect_muos_mount,
    detect_retroarch_cfg,
    retroarch_cfg_candidates,
)

DEFAULT_KNULLI_ROMS_ROOT = Path("/userdata/roms")
MUOS_GLYPH_PATH = Path(
    "/opt/muos/default/MUOS/theme/active/glyph/muxapp/raofflineproxy.png"
)
MUOS_CONFIG_FREEDOM_FLAG = Path("/opt/muos/config/settings/advanced/retrofree")
DEFAULT_KNULLI_STARTUP_SCRIPT = Path("/userdata/system/custom.sh")
ROM_DIRECTORY_KEYS = [
    "rgui_browser_directory",
    "content_directory",
]
AUTOSTART_SENTINEL_START = "# RAOfflineProxy autostart start"
AUTOSTART_SENTINEL_END = "# RAOfflineProxy autostart end"


def resolve_retroarch_cfg(config_data: dict) -> str:
    return str(config_data.get("retroarch_cfg") or detect_retroarch_cfg())


def resolve_retroarch_cfg_search(config_data: dict) -> list[str]:
    paths = [resolve_retroarch_cfg(config_data)]
    for candidate in retroarch_cfg_candidates():
        if candidate not in paths:
            paths.append(candidate)
    return paths


def resolve_rom_root(config_data: dict) -> Path:
    configured = config_data.get("roms_root") or os.environ.get(
        "RAOFFLINEPROXY_ROMS_ROOT"
    )
    if configured:
        candidate = Path(str(configured)).expanduser()
        if candidate.exists() and candidate.is_dir():
            return candidate

    cfg_path = Path(resolve_retroarch_cfg(config_data))
    values = read_retroarch_cfg_values(cfg_path)
    for key in ROM_DIRECTORY_KEYS:
        value = values.get(key)
        if not value:
            continue
        candidate = Path(value).expanduser()
        if candidate.exists() and candidate.is_dir():
            return candidate

    if DEFAULT_KNULLI_ROMS_ROOT.exists() and DEFAULT_KNULLI_ROMS_ROOT.is_dir():
        return DEFAULT_KNULLI_ROMS_ROOT

    muos_mount = detect_muos_mount()
    if muos_mount is not None:
        muos_roms = muos_mount / "ROMS"
        if muos_roms.exists() and muos_roms.is_dir():
            return muos_roms

    return cfg_path.parent


def read_retroarch_cfg_values(cfg_path: Path) -> dict[str, str]:
    if not cfg_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in cfg_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"')
    return values


def autostart_supported(config_data: dict) -> bool:
    return resolve_startup_script_path(config_data) is not None


def autostart_enabled(config_data: dict) -> bool:
    startup_script = resolve_startup_script_path(config_data)
    if startup_script is None or not startup_script.exists():
        return False

    if startup_script == DEFAULT_ONION_STARTUP_SCRIPT:
        return True

    content = startup_script.read_text(encoding="utf-8", errors="replace")
    return AUTOSTART_SENTINEL_START in content and AUTOSTART_SENTINEL_END in content


def enable_autostart(config_data: dict) -> None:
    startup_script = resolve_startup_script_path(config_data)
    if startup_script is None:
        raise ValueError("Autostart is not supported on this platform")

    if startup_script == DEFAULT_ONION_STARTUP_SCRIPT:
        startup_script.parent.mkdir(parents=True, exist_ok=True)
        startup_script.write_text(onion_autostart_script(), encoding="utf-8")
        return

    startup_script.parent.mkdir(parents=True, exist_ok=True)
    existing = (
        startup_script.read_text(encoding="utf-8", errors="replace")
        if startup_script.exists()
        else ""
    )
    cleaned = strip_autostart_block(existing).rstrip()
    block = autostart_block(config_data)
    new_content = f"{cleaned}\n\n{block}\n" if cleaned else f"{block}\n"
    startup_script.write_text(new_content, encoding="utf-8")


def disable_autostart(config_data: dict) -> None:
    startup_script = resolve_startup_script_path(config_data)
    if startup_script is None or not startup_script.exists():
        return

    if startup_script == DEFAULT_ONION_STARTUP_SCRIPT:
        startup_script.unlink()
        return

    existing = startup_script.read_text(encoding="utf-8", errors="replace")
    cleaned = strip_autostart_block(existing).strip()
    startup_script.write_text(f"{cleaned}\n" if cleaned else "", encoding="utf-8")


def resolve_startup_script_path(config_data: dict) -> Path | None:
    configured = config_data.get("startup_script")
    if configured:
        return Path(str(configured))

    if Path("/mnt/SDCARD/.tmp_update").exists():
        return DEFAULT_ONION_STARTUP_SCRIPT

    if Path("/userdata/system").exists():
        return DEFAULT_KNULLI_STARTUP_SCRIPT

    return None


def autostart_block(config_data: dict) -> str:
    startup_command = autostart_command(config_data)
    return "\n".join(
        [
            AUTOSTART_SENTINEL_START,
            f'if [ -x "{startup_command[0]}" ]; then',
            f"  {startup_command[0]} start-proxy >/dev/null 2>&1 || true",
            "fi",
            AUTOSTART_SENTINEL_END,
        ]
    )


def autostart_command(config_data: dict) -> tuple[str]:
    startup_script = resolve_startup_script_path(config_data)
    if startup_script == DEFAULT_ONION_STARTUP_SCRIPT:
        return ("/mnt/SDCARD/App/RAOfflineProxy/autostart-launch.sh",)

    launcher = str(
        config_data.get("autostart_launcher")
        or "/userdata/system/raofflineproxy/bin/raofflineproxy"
    )
    return (launcher,)


def strip_autostart_block(content: str) -> str:
    start = content.find(AUTOSTART_SENTINEL_START)
    if start < 0:
        return content

    end = content.find(AUTOSTART_SENTINEL_END, start)
    if end < 0:
        return content[:start]

    end += len(AUTOSTART_SENTINEL_END)
    return f"{content[:start]}{content[end:]}"


def muos_retroarch_config_freedom() -> bool | None:
    try:
        return MUOS_CONFIG_FREEDOM_FLAG.read_text(encoding="utf-8").strip() == "1"
    except OSError:
        return None


def muos_app_dir() -> Path | None:
    configured = os.environ.get("APP_DIR")
    if configured:
        return Path(configured)

    mount = detect_muos_mount()
    if mount is None:
        return None
    return mount / MUOS_APP_SUBPATH


def muos_uninstall_paths() -> list[Path] | None:
    mount = detect_muos_mount()
    app_dir = muos_app_dir()
    if mount is None or app_dir is None:
        return None
    return [
        app_dir,
        mount / "RAOFFLINEPROXY-REPORT.txt",
        MUOS_GLYPH_PATH,
    ]


def onion_autostart_script() -> str:
    return "\n".join(
        [
            "#!/bin/sh",
            "set -eu",
            "",
            "APP_DIR=/mnt/SDCARD/App/RAOfflineProxy",
            'if [ -x "$APP_DIR/autostart-launch.sh" ]; then',
            '  sh "$APP_DIR/autostart-launch.sh"',
            "fi",
            "",
        ]
    )
