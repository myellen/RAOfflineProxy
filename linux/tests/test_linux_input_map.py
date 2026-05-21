import unittest
from unittest import mock

from linux.raofflineproxy import input_map
from linux.raofflineproxy import menu_input as KI


class LinuxInputMapTests(unittest.TestCase):
    def test_defaults_when_no_saved_map(self) -> None:
        m = input_map.resolve_input_map(None)
        self.assertIn(KI.BTN_SOUTH, m["confirm"])
        self.assertIn(KI.BTN_EAST, m["back"])
        self.assertIn(KI.KEY_ENTER, m["confirm"])

    def test_calibrated_code_is_disjoint(self) -> None:
        m = input_map.resolve_input_map({"confirm": [KI.BTN_EAST]})
        self.assertIn(KI.BTN_EAST, m["confirm"])
        self.assertNotIn(KI.BTN_EAST, m["back"])
        self.assertIn(KI.KEY_ENTER, m["confirm"])
        self.assertIn(KI.KEY_ESC, m["back"])

    def test_swap_confirm_and_back(self) -> None:
        m = input_map.resolve_input_map(
            {"confirm": [KI.BTN_EAST], "back": [KI.BTN_SOUTH]}
        )
        self.assertEqual(input_map.action_for(KI.BTN_EAST, m), "confirm")
        self.assertEqual(input_map.action_for(KI.BTN_SOUTH, m), "back")

    def test_action_for_unknown_code(self) -> None:
        m = input_map.resolve_input_map(None)
        self.assertIsNone(input_map.action_for(99999, m))

    def test_same_code_under_two_actions_resolves_to_one(self) -> None:
        m = input_map.resolve_input_map(
            {"confirm": [KI.BTN_SOUTH], "back": [KI.BTN_SOUTH]}
        )
        self.assertEqual(input_map.action_for(KI.BTN_SOUTH, m), "back")
        self.assertNotIn(KI.BTN_SOUTH, m["confirm"])

    def test_save_then_load_resolves_via_action_for(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input_map.json"
            with mock.patch.object(input_map, "INPUT_MAP_FILE", path):
                input_map.save_input_map({"confirm": [KI.BTN_EAST]})
                m = input_map.load_input_map()
        self.assertEqual(input_map.action_for(KI.BTN_EAST, m), "confirm")
        self.assertNotIn(KI.BTN_EAST, m["back"])

    def test_merge_calibration_preserves_untouched_buttons(self) -> None:
        saved = {"confirm": [700], "back": [701], "up": [702],
                 "down": [703], "left": [704], "right": [705]}
        m = input_map.resolve_input_map(
            input_map.merge_calibration({"confirm": [800]}, saved)
        )
        self.assertEqual(input_map.action_for(800, m), "confirm")
        self.assertEqual(input_map.action_for(701, m), "back")
        self.assertEqual(input_map.action_for(705, m), "right")

    def test_merge_calibration_rebinding_onto_another_code_wins(self) -> None:
        saved = {"confirm": [200], "up": [999]}
        merged = input_map.merge_calibration({"confirm": [999]}, saved)
        m = input_map.resolve_input_map(merged)
        self.assertEqual(input_map.action_for(999, m), "confirm")
        self.assertNotEqual(input_map.action_for(999, m), "up")

    def test_save_and_load_roundtrip(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input_map.json"
            with mock.patch.object(input_map, "INPUT_MAP_FILE", path):
                input_map.save_input_map(
                    {"confirm": [KI.BTN_EAST], "bogus": [1], "empty": []}
                )
                saved = input_map.load_saved_input_map()
        self.assertEqual(saved, {"confirm": [KI.BTN_EAST]})


if __name__ == "__main__":
    unittest.main()
