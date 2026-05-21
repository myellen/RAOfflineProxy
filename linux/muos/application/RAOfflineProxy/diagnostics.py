#!/usr/bin/env python3
"""Self-contained, stdlib-only diagnostics for the RAOfflineProxy muOS app.

Run by mux_launch.sh on every launch. It writes ONE plain-text report with a
top-line VERDICT and a [PASS]/[WARN]/[FAIL] line per check, so that when
something goes wrong the tester only has to send a single file. The report is
written to the SD card root (visible the moment the card is mounted on a
computer) and copied into the app's logs/ dir as a backup.

It must keep working even when the heavy core or pygame are broken, so every
risky probe is wrapped, the app package import is optional, and even an
unexpected error in this script still results in a written report. The
`from __future__ import annotations` line keeps this parseable on Python 3.7+
so it can still report a too-old interpreter as a failure.
"""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import socket
import sys
import time
import traceback
from pathlib import Path

APP_DIR = Path(os.environ.get("APP_DIR", Path(__file__).resolve().parent))
ROOT_DIR = Path(os.environ.get("ROOT_DIR", "/mnt/mmc"))
PKG_DIR = APP_DIR / "app"

lines: list[str] = []
fails: list[str] = []
warns: list[str] = []


def check(name: str, ok: bool, detail: str = "", warn_only: bool = False) -> None:
    tag = "PASS" if ok else ("WARN" if warn_only else "FAIL")
    lines.append(f"[{tag}] {name}: {detail}" if detail else f"[{tag}] {name}")
    if not ok:
        (warns if warn_only else fails).append(name)


def section(title: str) -> None:
    lines.append("")
    lines.append(f"--- {title} ---")


def probe(fn):
    """Run a probe, turning any exception into a readable string."""
    try:
        return fn(), None
    except Exception as exc:  # noqa: BLE001 - we want every failure as text
        return None, f"{type(exc).__name__}: {exc}"


def read_text_safe(path) -> str:
    """Read a file as text, never raising (returns '' on any error)."""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - diagnostics must never crash on a read
        return ""


def read_json_safe(path):
    """Parse a JSON file, returning None on any error."""
    import json

    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def cfg_value(text: str, key: str) -> str | None:
    """Return the value of a retroarch.cfg `key = "value"` line, or None if absent."""
    for raw in text.splitlines():
        s = raw.strip()
        if s.startswith(f"{key} ") or s.startswith(f"{key}="):
            return s.split("=", 1)[1].strip().strip('"') if "=" in s else ""
    return None


def collect() -> None:
    section("environment")
    lines.append(f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"uname: {platform.platform()}")
    lines.append(f"machine: {platform.machine()}")
    lines.append(f"APP_DIR: {APP_DIR}")
    lines.append(f"ROOT_DIR (SD mount): {ROOT_DIR}")
    check("muOS tree present", (ROOT_DIR / "MUOS").is_dir(), str(ROOT_DIR / "MUOS"))

    # muOS version (/opt/muos/config/system/version, e.g. "2601_0"). The proxy
    # redirect needs "RetroArch Config Freedom", which only exists since 2508 --
    # so an older muOS can't persist the patch at all, no matter the settings.
    muos_version_lines = read_text_safe("/opt/muos/config/system/version").splitlines()
    muos_version = muos_version_lines[0].strip() if muos_version_lines else ""
    if muos_version:
        muos_build = read_text_safe("/opt/muos/config/system/build").strip() or "?"
        lines.append(f"muOS version: {muos_version.replace('_', ' ')}  build: {muos_build}")
        head = muos_version.split("_")[0].split(".")[0]
        if head.isdigit():
            check("muOS >= 2508 (has 'RetroArch Config Freedom', required for the proxy)",
                  int(head) >= 2508,
                  muos_version if int(head) >= 2508 else
                  f"{muos_version} -> older than 2508; RetroArch Config Freedom does not "
                  f"exist here, so the proxy redirect cannot be made to persist",
                  warn_only=True)

    section("tester notes (optional, written by you)")
    note_found = False
    for nf in (ROOT_DIR / "RAOFFLINEPROXY-NOTES.txt", APP_DIR / "NOTES.txt"):
        if Path(nf).exists():
            note_found = True
            lines.append(f"# {nf}")
            lines.extend(f"  {ln}" for ln in read_text_safe(nf).splitlines()[:50])
    if not note_found:
        lines.append("(none) To describe what happened, create a text file named "
                     "RAOFFLINEPROXY-NOTES.txt at the SD-card root and relaunch; "
                     "whatever you write there is included in this report.")

    section("python")
    ver = sys.version_info
    lines.append(f"executable: {sys.executable}")
    lines.append(f"version: {sys.version.split()[0]}")
    check("python >= 3.10", ver[:2] >= (3, 10), f"found {ver.major}.{ver.minor}")
    has_pip = importlib.util.find_spec("pip") is not None
    check("pip available", has_pip,
          "" if has_pip else "absent -- not required (pygame is bundled)",
          warn_only=True)

    section("pygame / SDL")
    pg, err = probe(lambda: importlib.import_module("pygame"))
    if pg is not None:
        check("pygame import", True,
              f"{pg.version.ver} (SDL {'.'.join(map(str, pg.get_sdl_version()))})")
        # Probe ONLY the default driver (SDL's own pick) to confirm a real
        # display. We deliberately do NOT force-init kmsdrm/fbcon here: those
        # take the real framebuffer/DRM master, and doing it on every diagnostics
        # run (in addition to the launcher's own probe and the menu) risks
        # leaving a handheld's screen in a bad state. On muOS the default is
        # "mali".
        os.environ.pop("SDL_VIDEODRIVER", None)
        probe(pg.display.quit)
        used, init_err = probe(lambda: (pg.display.init(), pg.display.get_driver())[1])
        probe(pg.display.quit)
        if used is not None:
            check("SDL can open a real display", used not in ("dummy", "offscreen"),
                  f"default video driver: {used}")
        else:
            check("SDL can open a real display", False, f"default init failed: {init_err}")
    else:
        check("pygame import", False, err)

    section("system SDL (framebuffer-capable, for the overlay)")
    import glob as _glob
    sys_sdl = []
    for d in ("/usr/lib", "/usr/lib/aarch64-linux-gnu", "/lib", "/usr/local/lib"):
        sys_sdl += _glob.glob(os.path.join(d, "libSDL2-2.0.so*"))
    check("system libSDL2 present", bool(sys_sdl),
          ", ".join(sys_sdl) or "none found", warn_only=True)

    # Read the system SDL's exact runtime version via ctypes -> SDL_GetVersion.
    # pygame 2.6.1 is built against SDL 2.28.4, so the overlay needs the system
    # SDL to be >= 2.28.4; this records the precise version regardless.
    def _system_sdl_version() -> str:
        import ctypes

        class _V(ctypes.Structure):
            _fields_ = [("major", ctypes.c_uint8),
                        ("minor", ctypes.c_uint8),
                        ("patch", ctypes.c_uint8)]

        for cand in sys_sdl:
            try:
                lib = ctypes.CDLL(cand)
                ver = _V()
                lib.SDL_GetVersion(ctypes.byref(ver))
                return f"{ver.major}.{ver.minor}.{ver.patch}"
            except Exception:  # noqa: BLE001 - try the next candidate
                continue
        raise FileNotFoundError("no loadable system libSDL2")

    if sys_sdl:
        ver, ver_err = probe(_system_sdl_version)
        if ver is not None:
            ok = tuple(int(x) for x in ver.split(".")) >= (2, 28, 4)
            check("system SDL >= 2.28.4 (overlay-compatible with pygame 2.6.1)",
                  ok, f"system SDL {ver}", warn_only=not ok)
        else:
            lines.append(f"system SDL version: unreadable ({ver_err})")

    section("display backends")
    check("/dev/fb0 (framebuffer)", Path("/dev/fb0").exists(), warn_only=True)
    dri = sorted(str(p) for p in Path("/dev/dri").glob("card*")) if Path("/dev/dri").exists() else []
    check("/dev/dri/card* (KMSDRM)", bool(dri), ", ".join(dri), warn_only=True)

    section("fonts")
    has_fc = shutil.which("fc-list") is not None
    check("fc-list (fontconfig)", has_fc,
          "present" if has_fc else "absent -> menu uses built-in font (still works)",
          warn_only=True)

    section("input")
    events = sorted(str(p) for p in Path("/dev/input").glob("event*")) if Path("/dev/input").exists() else []
    check("/dev/input/event* present", bool(events),
          f"{len(events)} device(s): {', '.join(events)}", warn_only=True)

    section("retroarch")
    sys.path.insert(0, str(PKG_DIR))
    core, core_err = probe(lambda: importlib.import_module("raofflineproxy.config"))
    if core is not None:
        cfg = os.environ.get("RAOFFLINEPROXY_RETROARCH_CFG") or core.detect_retroarch_cfg()
        lines.append(f"retroarch.cfg: {cfg}")
        check("retroarch.cfg exists", Path(cfg).exists(), warn_only=True)
        text = read_text_safe(cfg) if Path(cfg).exists() else ""
        has_token = 'cheevos_token = "' in text and 'cheevos_token = ""' not in text
        has_pw = 'cheevos_password = "' in text and 'cheevos_password = ""' not in text
        has_creds = has_token or has_pw
        check("RA credentials present (Cached Games will appear)", has_creds,
              "ok" if has_creds else "log into RetroAchievements in RetroArch first",
              warn_only=True)

        # Report the cheevos values from the file RetroArch actually reads, so a
        # "didn't connect" report shows whether Start patched the right file.
        # (cheevos_custom_host stays empty until "Start proxy" is run.)
        lines.append(
            f"cheevos_enable={cfg_value(text, 'cheevos_enable')!r}  "
            f"cheevos_custom_host={cfg_value(text, 'cheevos_custom_host')!r}  "
            f"cheevos_hardcore_mode_enable="
            f"{cfg_value(text, 'cheevos_hardcore_mode_enable')!r}  "
            f"cheevos_unlock_notifications="
            f"{cfg_value(text, 'cheevos_unlock_notifications')!r}"
        )
        lines.append(
            "(Start proxy sets custom_host and turns hardcore OFF -- offline "
            "unlocks are softcore; if unlock_notifications is false you won't see "
            "the on-screen popups even when unlocks are recorded.)"
        )

        # Enumerate EVERY retroarch.cfg we can find with its cheevos host/enable
        # AND its login (username + whether a token is set). Two classic muOS
        # bugs become visible here: RetroArch reading a different cfg than the one
        # Start patched, and the login token living in a cfg we don't read
        # ("logged in but says not"). The token value itself is never printed.
        lines.append("all retroarch.cfg found (enable / host / user / token / password):")
        seen: set[str] = set()
        creds_in: list[str] = []
        any_user_password = False
        for cand in (cfg,
                     "/opt/muos/share/info/config/retroarch.cfg",
                     "/opt/muos/share/info/config/retroarch.cheevos.cfg",
                     f"{ROOT_DIR}/MUOS/info/config/retroarch.cfg",
                     f"{ROOT_DIR}/MUOS/info/config/retroarch.cheevos.cfg",
                     "/mnt/mmc/MUOS/info/config/retroarch.cfg",
                     "/mnt/mmc/MUOS/info/config/retroarch.cheevos.cfg",
                     "/mnt/sdcard/MUOS/info/config/retroarch.cfg",
                     "/mnt/sdcard/MUOS/info/config/retroarch.cheevos.cfg"):
            if not cand or cand in seen:
                continue
            seen.add(cand)
            if not Path(cand).exists():
                continue
            ctext = read_text_safe(cand)
            user = cfg_value(ctext, "cheevos_username")
            has_token = bool(cfg_value(ctext, "cheevos_token"))
            has_password = bool(cfg_value(ctext, "cheevos_password"))
            if user and has_token:
                creds_in.append(cand)
            if user and has_password:
                any_user_password = True
            marker = "  <- Start patched this one" if cand == cfg else ""
            lines.append(
                f"  {cand}: enable={cfg_value(ctext, 'cheevos_enable')!r} "
                f"host={cfg_value(ctext, 'cheevos_custom_host')!r} "
                f"user={user!r} token={'set' if has_token else 'EMPTY'} "
                f"password={'set' if has_password else 'none'}{marker}"
            )

        # Hunt for a login saved in a cfg we DON'T list (RetroArch's own config
        # dir, a per-frontend path, ...) so "logged in but says not" is never a
        # mystery. Lazy + capped + wrapped so it can't stall or crash the report.
        def _find_unlisted_login_cfgs():
            import glob as _g
            hits, scanned = [], 0
            for pat in ("/opt/muos/share/retroarch/**/*.cfg",
                        f"{ROOT_DIR}/MUOS/**/*.cfg",
                        "/mnt/mmc/MUOS/**/*.cfg",
                        "/mnt/sdcard/MUOS/**/*.cfg"):
                for hit in _g.iglob(pat, recursive=True):
                    scanned += 1
                    if scanned > 300:
                        return hits
                    if hit in seen:
                        continue
                    t = read_text_safe(hit)
                    if cfg_value(t, "cheevos_username") and cfg_value(t, "cheevos_token"):
                        hits.append(hit)
            return hits

        for hit in sorted(set(probe(_find_unlisted_login_cfgs)[0] or [])):
            if hit not in creds_in:
                creds_in.append(hit)
                lines.append(f"  (unlisted) {hit}: has cheevos_username + cheevos_token")

        if creds_in:
            login_detail = "found in: " + ", ".join(creds_in)
        elif any_user_password:
            login_detail = (
                "username+password present but NO token (muOS stores only "
                "username/password) -> START THE PROXY ONCE WHILE ONLINE so it "
                "fetches and caches a token; offline login works after that"
            )
        else:
            login_detail = (
                "no RetroAchievements login in any cfg -> log into "
                "RetroAchievements in RetroArch, save, then relaunch"
            )
        check("RetroAchievements login found in a cfg", bool(creds_in),
              login_detail, warn_only=True)

        # Does the patched custom host actually point at the configured proxy?
        conf = probe(core.load_config)[0] or {}
        want_host = f"{conf.get('proxy_host', '127.0.0.1')}:{conf.get('proxy_port', 8080)}"
        host_set = cfg_value(text, "cheevos_custom_host") or ""
        if host_set:
            check("cheevos_custom_host points at the proxy", want_host in host_set,
                  f"cfg has {host_set!r}, configured proxy is {want_host!r}", warn_only=True)
        else:
            lines.append(
                f"note: cheevos_custom_host is empty -> press 'Start proxy' "
                f"(it should become {want_host!r}), then relaunch RetroArch"
            )

        # muOS "RetroArch Config Freedom" (Settings > Advanced). REQUIRED for the
        # proxy: with it OFF (default), muOS deletes + re-copies the global
        # retroarch.cfg from its template every launch (func.sh CONFIGURE_RETROARCH),
        # wiping our cheevos_custom_host patch so the redirect never persists.
        retrofree = read_text_safe("/opt/muos/config/settings/advanced/retrofree").strip()
        check("RetroArch Config Freedom ON (Settings > Advanced) [required for proxy]",
              retrofree == "1",
              "on" if retrofree == "1" else
              f"{retrofree or 'absent'} -> turn it ON in Settings > Advanced, or muOS "
              f"resets retroarch.cfg and wipes the proxy redirect at every launch",
              warn_only=True)

        section("proxy service (most recent run)")
        # A full or read-only SD silently breaks caching, the award queue, and
        # cfg patching -- check the data dir is writable and has room.
        data_dir = Path(core.CONFIG_DIR)
        check("data dir writable", data_dir.exists() and os.access(str(data_dir), os.W_OK),
              str(data_dir), warn_only=True)
        usage = probe(lambda: shutil.disk_usage(str(data_dir)))[0]
        if usage is not None:
            lines.append(f"data dir free space: {usage.free // (1024 * 1024)} MiB")

        # Does the proxy already hold a cached RA login (a token)? This is the
        # real offline-readiness signal -- it persists in the cache DB regardless
        # of whether the proxy is running right now. With muOS storing only
        # username+password, the token is only obtained by starting the proxy
        # while online; this confirms whether that has happened.
        def _cached_login_users():
            import sqlite3
            con = sqlite3.connect(f"file:{core.DATABASE_FILE}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT cacheKey FROM api_cache WHERE cacheKey LIKE 'login2::%'"
                ).fetchall()
            finally:
                con.close()
            return [row[0].split("::", 1)[1] for row in rows if "::" in row[0]]

        cached_users = probe(_cached_login_users)[0] or []
        check("proxy has a cached RA login (offline-ready)", bool(cached_users),
              ("cached for: " + ", ".join(cached_users)) if cached_users else
              "none -> start the proxy once WHILE ONLINE so it fetches+caches a token",
              warn_only=True)

        status = read_json_safe(core.STATUS_FILE)
        lines.append(
            f"service_status.json: {status}" if status else
            "service_status.json: absent (proxy not running now -- normal at launch "
            "or after a clean stop)"
        )
        pid = None
        raw_pid = read_text_safe(core.PID_FILE).strip()
        if raw_pid.isdigit():
            pid = int(raw_pid)
        if pid:
            check("service.pid process still alive", Path(f"/proc/{pid}").exists(),
                  f"pid={pid}", warn_only=True)
        patch_state = read_json_safe(core.STATE_FILE)
        if patch_state:
            lines.append(f"retroarch_patch_state.json: {patch_state}")

        # The decisive signal for "didn't connect": every proxy request is logged
        # here, so if RetroArch talked to the proxy at all there are 'Request:'
        # lines. Zero requests after a play session => RetroArch never reached it.
        log_path = Path(core.LOG_FILE)
        if log_path.exists():
            log_text = read_text_safe(log_path)
            log_lines = log_text.splitlines()
            reqs = [ln for ln in log_lines if "Request:" in ln]
            problems = [ln for ln in log_lines if " ERROR " in ln or " WARNING " in ln]
            if reqs:
                last = reqs[-1]
                cut = last.find("Request:")
                snippet = (last[cut:] if cut >= 0 else last)[:100]
                req_detail = f"{len(reqs)} request(s); last: {snippet}"
            else:
                req_detail = ("0 requests -> RetroArch never connected (wrong cfg, "
                              "or RetroArch was not relaunched after Start proxy)")
            check("RetroArch reached the proxy (requests logged)", bool(reqs),
                  req_detail, warn_only=True)
            if problems:
                lines.append(f"service.log ERROR/WARNING lines: {len(problems)}")
            lines.append(f"# tail {log_path} (proxy request log)")
            lines.extend(f"  {ln}" for ln in log_lines[-20:])
        else:
            lines.append(f"service.log absent ({log_path}) -> proxy has not run yet")
    else:
        check("import raofflineproxy core", False, core_err)

    section("network")
    if os.environ.get("RAOFFLINEPROXY_DIAG_SKIP_NETWORK"):
        lines.append("(skipped via RAOFFLINEPROXY_DIAG_SKIP_NETWORK)")
    else:
        def reachable(host: str, port: int = 443) -> str:
            sock = socket.create_connection((host, port), timeout=4)
            sock.close()
            return "reachable"

        for host in ("pypi.org", "retroachievements.org"):
            res, e = probe(lambda h=host: reachable(h))
            check(f"reach {host}", res is not None, res or e, warn_only=True)

    section("recent logs (tail)")
    for log in (APP_DIR / "logs" / "launch.log", APP_DIR / "data" / "menu-sdl.log"):
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="replace").splitlines()[-15:]
            lines.append(f"# {log}")
            lines.extend(f"  {ln}" for ln in tail)


# Run the collection; an unexpected error here must NOT prevent a report.
try:
    collect()
except Exception:  # noqa: BLE001
    fails.append("diagnostics-internal-error")
    lines.append("")
    lines.append("--- diagnostics internal error ---")
    lines.extend(traceback.format_exc().rstrip().splitlines())

verdict = "OK" if not fails else f"FAILED ({', '.join(fails)})"
if not fails and warns:
    verdict = f"OK (warnings: {', '.join(warns)})"

report = "\n".join([
    "RAOfflineProxy muOS diagnostics report",
    f"VERDICT: {verdict}",
    "Send this whole file to debug. Newest run overwrites the previous one.",
    "=" * 60,
] + lines) + "\n"

written = []
for target in (ROOT_DIR / "RAOFFLINEPROXY-REPORT.txt", APP_DIR / "logs" / "diagnostics.txt"):
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(report, encoding="utf-8")
        written.append(str(target))
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"could not write {target}: {exc}\n")

print(f"VERDICT: {verdict}")
for path in written:
    print(f"report: {path}")
sys.exit(0 if not fails else 2)
