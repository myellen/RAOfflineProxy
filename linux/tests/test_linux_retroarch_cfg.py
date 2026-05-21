import tempfile
import unittest
from pathlib import Path

from linux.raofflineproxy import retroarch_cfg
from linux.raofflineproxy import state


class LinuxRetroarchCfgTests(unittest.TestCase):
    def test_revert_without_patch_state_removes_proxy_host_and_preserves_cheevos_enable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "retroarch.cfg"
            state_path = Path(temp_dir) / "retroarch_patch_state.json"

            cfg_path.write_text(
                'cheevos_custom_host = "127.0.0.1:8080"\n'
                'cheevos_enable = "true"\n'
                'cheevos_hardcore_mode_enable = "false"\n',
                encoding="utf-8",
            )

            original_state_file = state.STATE_FILE
            try:
                state.STATE_FILE = state_path
                result = retroarch_cfg.revert_retroarch_cfg(str(cfg_path))

                self.assertTrue(result["changed"])
                content = cfg_path.read_text(encoding="utf-8")
                self.assertIn('cheevos_custom_host = ""', content)
                self.assertIn('cheevos_enable = "true"', content)
                self.assertIn('cheevos_hardcore_mode_enable = "false"', content)
            finally:
                state.STATE_FILE = original_state_file


    def test_appended_cheevos_cfg_is_patched_and_reverted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "retroarch.cfg"
            cfg_path.write_text('cheevos_enable = "true"\n', encoding="utf-8")
            cheevos = Path(temp_dir) / "retroarch.cheevos.cfg"
            cheevos.write_text(
                'cheevos_enable = "true"\ncheevos_custom_host = ""\n'
                'cheevos_username = "kamenhikari"\ncheevos_password = "pw"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                retroarch_cfg.appended_cheevos_cfg_path(str(cfg_path)), str(cheevos)
            )

            self.assertTrue(
                retroarch_cfg.patch_appended_cheevos_cfg(
                    str(cfg_path), {"proxy_host": "127.0.0.1", "proxy_port": 8080}
                )
            )
            patched = cheevos.read_text(encoding="utf-8")
            self.assertIn('cheevos_custom_host = "127.0.0.1:8080"', patched)
            self.assertIn('cheevos_username = "kamenhikari"', patched)  # creds kept

            self.assertTrue(retroarch_cfg.revert_appended_cheevos_cfg(str(cfg_path)))
            reverted = cheevos.read_text(encoding="utf-8")
            self.assertIn('cheevos_custom_host = ""', reverted)
            self.assertIn('cheevos_username = "kamenhikari"', reverted)

    def test_appended_cheevos_cfg_helpers_noop_without_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cfg_path = Path(temp_dir) / "retroarch.cfg"
            cfg_path.write_text('cheevos_enable = "true"\n', encoding="utf-8")
            self.assertIsNone(retroarch_cfg.appended_cheevos_cfg_path(str(cfg_path)))
            self.assertFalse(retroarch_cfg.patch_appended_cheevos_cfg(str(cfg_path), {}))
            self.assertFalse(retroarch_cfg.revert_appended_cheevos_cfg(str(cfg_path)))


if __name__ == "__main__":
    unittest.main()
