import struct
import unittest

from linux.raofflineproxy import menu_input


class FakeHandle:
    def __init__(self, events: list[bytes]) -> None:
        self._events = list(events)

    def read(self, size: int) -> bytes:
        if not self._events:
            raise BlockingIOError
        return self._events.pop(0)


class FakeNoneHandle:
    def read(self, size: int):
        return None


def key_event(code: int, value: int = 1) -> bytes:
    return struct.pack("llHHi", 0, 0, menu_input.EV_KEY, code, value)


def abs_event(code: int, value: int) -> bytes:
    return struct.pack("llHHi", 0, 0, menu_input.EV_ABS, code, value)


def drain(events: list[bytes]) -> list[int]:
    handle = FakeHandle(events)
    original_select = menu_input.select.select
    try:
        menu_input.select.select = lambda handles, _w, _x, _t: (handles, [], [])
        return menu_input.read_keys([handle])
    finally:
        menu_input.select.select = original_select


class LinuxMenuInputTests(unittest.TestCase):
    def test_read_keys_drains_all_available_events(self) -> None:
        handle = FakeHandle(
            [
                key_event(menu_input.KEY_DOWN),
                key_event(menu_input.KEY_DOWN),
            ]
        )

        original_select = menu_input.select.select
        try:
            menu_input.select.select = lambda handles, _w, _x, _t: (handles, [], [])

            keys = menu_input.read_keys([handle])

            self.assertEqual(keys, [menu_input.KEY_DOWN, menu_input.KEY_DOWN])
        finally:
            menu_input.select.select = original_select

    def test_read_keys_returns_empty_when_handle_would_block(self) -> None:
        handle = FakeHandle([])

        original_select = menu_input.select.select
        try:
            menu_input.select.select = lambda handles, _w, _x, _t: (handles, [], [])

            keys = menu_input.read_keys([handle])

            self.assertEqual(keys, [])
        finally:
            menu_input.select.select = original_select

    def test_read_keys_returns_empty_when_handle_returns_none(self) -> None:
        handle = FakeNoneHandle()

        original_select = menu_input.select.select
        try:
            menu_input.select.select = lambda handles, _w, _x, _t: (handles, [], [])

            keys = menu_input.read_keys([handle])

            self.assertEqual(keys, [])
        finally:
            menu_input.select.select = original_select


    def test_dpad_hat_maps_to_directions(self) -> None:
        self.assertEqual(drain([abs_event(menu_input.ABS_HAT0Y, -1)]), [menu_input.BTN_DPAD_UP])
        self.assertEqual(drain([abs_event(menu_input.ABS_HAT0Y, 1)]), [menu_input.BTN_DPAD_DOWN])
        self.assertEqual(drain([abs_event(menu_input.ABS_HAT0X, -1)]), [menu_input.BTN_DPAD_LEFT])
        self.assertEqual(drain([abs_event(menu_input.ABS_HAT0X, 1)]), [menu_input.BTN_DPAD_RIGHT])

    def test_dpad_hat_release_is_ignored(self) -> None:
        self.assertEqual(drain([abs_event(menu_input.ABS_HAT0Y, 0)]), [])
        self.assertEqual(drain([abs_event(menu_input.ABS_HAT0X, 0)]), [])

    def test_key_release_and_autorepeat_are_ignored(self) -> None:
        self.assertEqual(drain([key_event(menu_input.KEY_ENTER, 0)]), [])
        self.assertEqual(drain([key_event(menu_input.KEY_ENTER, 2)]), [])
        self.assertEqual(drain([key_event(menu_input.KEY_ENTER, 1)]), [menu_input.KEY_ENTER])


if __name__ == "__main__":
    unittest.main()
