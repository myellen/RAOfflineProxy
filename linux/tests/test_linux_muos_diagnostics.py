import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LINUX_DIR = Path(__file__).resolve().parents[1]
DIAGNOSTICS = LINUX_DIR / "muos" / "application" / "RAOfflineProxy" / "diagnostics.py"


def _seed(root: Path, *, requests: bool, custom_host: str, with_core: bool) -> Path:
    (root / "MUOS").mkdir()
    if with_core:
        (root / "app").symlink_to(LINUX_DIR)
    data = root / "data"
    data.mkdir()
    (data / "config.json").write_text(
        json.dumps({"proxy_host": "127.0.0.1", "proxy_port": 8080})
    )
    (data / "retroarch.cfg").write_text(
        'cheevos_enable = "true"\n'
        f'cheevos_custom_host = "{custom_host}"\n'
        'cheevos_token = "abc123"\n'
    )
    (data / "service_status.json").write_text(
        json.dumps({"running": True, "pid": 999999, "proxyPort": 8080})
    )
    (data / "service.pid").write_text("999999\n")
    (data / "retroarch_patch_state.json").write_text(json.dumps({"applied": True}))
    log = "2026-05-20 10:00:01 INFO raofflineproxy Service started\n"
    if requests:
        log += (
            "2026-05-20 10:00:05 INFO raofflineproxy Request: GET "
            "/dorequest.php?r=gameid&m=*** body= online=False\n"
            "2026-05-20 10:00:06 INFO raofflineproxy Request: POST "
            "/dorequest.php?r=awardachievement&a=111&t=*** body=*** online=False\n"
        )
    (data / "service.log").write_text(log)
    (root / "RAOFFLINEPROXY-NOTES.txt").write_text("no achievements popped while playing\n")
    return data


def _run_diagnostics(root: Path) -> str:
    env = dict(
        os.environ,
        APP_DIR=str(root),
        ROOT_DIR=str(root),
        RAOFFLINEPROXY_CONFIG_DIR=str(root / "data"),
        RAOFFLINEPROXY_RETROARCH_CFG=str(root / "data" / "retroarch.cfg"),
        RAOFFLINEPROXY_DIAG_SKIP_NETWORK="1",
        PYGAME_HIDE_SUPPORT_PROMPT="1",
    )
    subprocess.run([sys.executable, str(DIAGNOSTICS)], env=env,
                   capture_output=True, text=True, timeout=60)
    report = root / "RAOFFLINEPROXY-REPORT.txt"
    assert report.exists(), "diagnostics did not write the report file"
    return report.read_text(encoding="utf-8")


class MuosDiagnosticsReportTests(unittest.TestCase):
    @unittest.skipIf(sys.version_info[:2] < (3, 10), "core requires Python 3.10+")
    def test_flags_when_retroarch_never_connected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data = _seed(Path(tmp), requests=False, custom_host="127.0.0.1:9999",
                         with_core=True)
            report = _run_diagnostics(Path(tmp))

        self.assertIn("0 requests -> RetroArch never connected", report)
        self.assertIn("[WARN] cheevos_custom_host points at the proxy", report)
        self.assertIn("127.0.0.1:9999", report)
        self.assertIn("no achievements popped while playing", report)
        self.assertIn(str(data / "service.log"), report)

    @unittest.skipIf(sys.version_info[:2] < (3, 10), "core requires Python 3.10+")
    def test_confirms_when_retroarch_connected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _seed(Path(tmp), requests=True, custom_host="127.0.0.1:8080",
                  with_core=True)
            report = _run_diagnostics(Path(tmp))

        self.assertIn("[PASS] RetroArch reached the proxy", report)
        self.assertIn("request(s); last: Request:", report)
        self.assertIn("[PASS] cheevos_custom_host points at the proxy", report)
        self.assertIn("<- Start patched this one", report)

    def test_report_written_even_without_core(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _seed(Path(tmp), requests=False, custom_host="", with_core=False)
            report = _run_diagnostics(Path(tmp))

        self.assertIn("VERDICT:", report)
        self.assertIn("import raofflineproxy core", report)


if __name__ == "__main__":
    unittest.main()
