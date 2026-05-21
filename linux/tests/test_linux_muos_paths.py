import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from linux.raofflineproxy import config
from linux.raofflineproxy import platform as platform_module


MUOS_ENV_KEYS = (
    "RAOFFLINEPROXY_CONFIG_DIR",
    "XDG_CONFIG_HOME",
    "RAOFFLINEPROXY_MUOS_MOUNT",
    "RAOFFLINEPROXY_RETROARCH_CFG",
    "RAOFFLINEPROXY_ROMS_ROOT",
    "APP_DIR",
)


class LinuxMuosPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {key: os.environ.get(key) for key in MUOS_ENV_KEYS}
        for key in MUOS_ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_detect_muos_mount_prefers_env_override(self) -> None:
        os.environ["RAOFFLINEPROXY_MUOS_MOUNT"] = "/mnt/sdcard"
        self.assertEqual(config.detect_muos_mount(), Path("/mnt/sdcard"))

    def test_detect_muos_mount_picks_card_with_muos_tree(self) -> None:
        def fake_is_dir(self: Path) -> bool:
            return str(self) == "/mnt/sdcard/MUOS"

        with mock.patch.object(Path, "is_dir", fake_is_dir):
            self.assertEqual(config.detect_muos_mount(), Path("/mnt/sdcard"))

    def test_detect_muos_mount_returns_none_off_device(self) -> None:
        with mock.patch.object(Path, "is_dir", lambda self: False):
            self.assertIsNone(config.detect_muos_mount())

    def test_config_dir_uses_muos_app_data_dir(self) -> None:
        with mock.patch.object(
            config, "detect_muos_mount", return_value=Path("/mnt/mmc")
        ), mock.patch.object(config.Path, "exists", lambda self: False):
            self.assertEqual(
                config.resolve_config_dir(),
                Path("/mnt/mmc/MUOS/application/RAOfflineProxy/data"),
            )

    def test_retroarch_cfg_falls_back_to_muos_mount(self) -> None:
        with mock.patch.object(config.Path, "exists", lambda self: False), \
                mock.patch.object(
                    config, "detect_muos_mount", return_value=Path("/mnt/sdcard")
                ):
            self.assertEqual(
                config.detect_retroarch_cfg(),
                "/mnt/sdcard/MUOS/info/config/retroarch.cfg",
            )

    def test_rom_root_honors_env_override(self) -> None:
        with mock.patch.object(platform_module.Path, "exists", lambda self: True), \
                mock.patch.object(platform_module.Path, "is_dir", lambda self: True):
            os.environ["RAOFFLINEPROXY_ROMS_ROOT"] = "/mnt/mmc/ROMS"
            self.assertEqual(
                platform_module.resolve_rom_root({}),
                Path("/mnt/mmc/ROMS"),
            )

    def test_muos_app_dir_prefers_app_dir_env(self) -> None:
        os.environ["APP_DIR"] = "/mnt/sdcard/MUOS/application/RAOfflineProxy"
        self.assertEqual(
            platform_module.muos_app_dir(),
            Path("/mnt/sdcard/MUOS/application/RAOfflineProxy"),
        )

    def test_muos_app_dir_from_mount_when_no_env(self) -> None:
        with mock.patch.object(
            platform_module, "detect_muos_mount", return_value=Path("/mnt/mmc")
        ):
            self.assertEqual(
                platform_module.muos_app_dir(),
                Path("/mnt/mmc/MUOS/application/RAOfflineProxy"),
            )

    def test_uninstall_paths_on_muos(self) -> None:
        os.environ["APP_DIR"] = "/mnt/mmc/MUOS/application/RAOfflineProxy"
        with mock.patch.object(
            platform_module, "detect_muos_mount", return_value=Path("/mnt/mmc")
        ):
            paths = platform_module.muos_uninstall_paths()
        self.assertEqual(
            paths,
            [
                Path("/mnt/mmc/MUOS/application/RAOfflineProxy"),
                Path("/mnt/mmc/RAOFFLINEPROXY-REPORT.txt"),
                platform_module.MUOS_GLYPH_PATH,
            ],
        )

    def test_uninstall_paths_none_off_device(self) -> None:
        with mock.patch.object(
            platform_module, "detect_muos_mount", return_value=None
        ):
            self.assertIsNone(platform_module.muos_uninstall_paths())

    def test_config_freedom_reads_the_retrofree_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "retrofree"
            with mock.patch.object(
                platform_module, "MUOS_CONFIG_FREEDOM_FLAG", flag
            ):
                # Absent flag file -> unknown (None), not False.
                self.assertIsNone(platform_module.muos_retroarch_config_freedom())
                flag.write_text("1\n")
                self.assertIs(platform_module.muos_retroarch_config_freedom(), True)
                flag.write_text("0\n")
                self.assertIs(platform_module.muos_retroarch_config_freedom(), False)


if __name__ == "__main__":
    unittest.main()
