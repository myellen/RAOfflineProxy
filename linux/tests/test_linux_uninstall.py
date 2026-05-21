import unittest
from pathlib import Path

from linux.raofflineproxy.menu_sdl import build_uninstall_argv


class BuildUninstallArgvTests(unittest.TestCase):
    def test_paths_passed_as_args_not_interpolated(self) -> None:
        argv = build_uninstall_argv(
            [
                Path("/mnt/mmc/MUOS/application/RAOfflineProxy"),
                Path("/mnt/mmc/RAOFFLINEPROXY-REPORT.txt"),
            ]
        )
        # rm targets are positional args after the `sh` $0 -- never spliced into
        # the shell string, so they can't be re-parsed by the shell.
        self.assertEqual(argv[:4], ["/bin/sh", "-c", 'sleep 1; exec rm -rf "$@"', "sh"])
        self.assertIn("/mnt/mmc/MUOS/application/RAOfflineProxy", argv[4:])
        self.assertNotIn("rm", " ".join(argv[4:]))  # no command text mixed with paths

    def test_dangerous_targets_filtered(self) -> None:
        self.assertIsNone(
            build_uninstall_argv(
                [
                    Path("/"),
                    Path("/mnt"),
                    Path("/mnt/mmc"),
                    Path("/mnt/sdcard"),
                    Path("/usr"),
                    Path("relative/path"),
                ]
            )
        )

    def test_mix_keeps_only_safe_targets(self) -> None:
        argv = build_uninstall_argv(
            [Path("/mnt/mmc"), Path("/mnt/mmc/MUOS/application/RAOfflineProxy")]
        )
        self.assertEqual(argv[4:], ["/mnt/mmc/MUOS/application/RAOfflineProxy"])

    def test_parent_traversal_cannot_escape_to_a_root(self) -> None:
        # `..` must not let a path normalize up to a mount/filesystem root.
        self.assertIsNone(
            build_uninstall_argv(
                [Path("/mnt/mmc/MUOS/application/RAOfflineProxy/../../../..")]
            )
        )
        self.assertIsNone(build_uninstall_argv([Path("/mnt/mmc/MUOS/../..")]))
        self.assertIsNone(build_uninstall_argv([Path("/a/b/../../..")]))

    def test_paths_are_normalized_before_deletion(self) -> None:
        argv = build_uninstall_argv(
            [Path("/mnt/mmc/MUOS/application/RAOfflineProxy/./logs/..")]
        )
        self.assertEqual(argv[4:], ["/mnt/mmc/MUOS/application/RAOfflineProxy"])


if __name__ == "__main__":
    unittest.main()
