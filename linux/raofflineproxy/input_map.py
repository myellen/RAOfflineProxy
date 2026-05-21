"""Configurable controller button map for the SDL menu.

The menu reads raw evdev key codes from /dev/input. The mapping from physical
buttons to those codes varies across handhelds (e.g. muOS H700 devices do not
use the standard BTN_SOUTH=confirm layout), so the codes for each action are
configurable and can be set with the in-menu calibration screen. Saved choices
are merged over sensible defaults, with each code resolving to exactly one
action (a calibrated code is removed from every other action to avoid
ambiguity, e.g. when a device's confirm button reports BTN_EAST).
"""

import json

from .config import CONFIG_DIR
from .menu_input import (
    BTN_DPAD_DOWN,
    BTN_DPAD_LEFT,
    BTN_DPAD_RIGHT,
    BTN_DPAD_UP,
    BTN_EAST,
    BTN_SELECT,
    BTN_SOUTH,
    BTN_START,
    KEY_BACKSPACE,
    KEY_DOWN,
    KEY_ENTER,
    KEY_ESC,
    KEY_LEFT,
    KEY_Q,
    KEY_RIGHT,
    KEY_S,
    KEY_SPACE,
    KEY_UP,
)

INPUT_MAP_FILE = CONFIG_DIR / "input_map.json"

# Ordered actions the calibration screen walks through.
ACTIONS = ["confirm", "back", "up", "down", "left", "right"]
ACTION_LABELS = {
    "confirm": "Confirm / Select",
    "back": "Back / Cancel",
    "up": "D-pad Up",
    "down": "D-pad Down",
    "left": "D-pad Left",
    "right": "D-pad Right",
}

# Codes that work on most devices, including keyboard fallbacks that never
# collide with gamepad codes. Hat axes are decoded to the BTN_DPAD_* synthetics
# by menu_input.read_keys, so they appear here as the dpad codes.
DEFAULT_INPUT_MAP: dict[str, list[int]] = {
    "confirm": [KEY_ENTER, KEY_SPACE, KEY_S, BTN_SOUTH, BTN_START],
    "back": [KEY_ESC, KEY_BACKSPACE, KEY_Q, BTN_EAST, BTN_SELECT],
    "up": [KEY_UP, BTN_DPAD_UP],
    "down": [KEY_DOWN, BTN_DPAD_DOWN],
    "left": [KEY_LEFT, BTN_DPAD_LEFT],
    "right": [KEY_RIGHT, BTN_DPAD_RIGHT],
}


def resolve_input_map(saved: dict | None) -> dict[str, list[int]]:
    """Merge saved calibration over the defaults into a disjoint code->action map."""
    mapping = {action: list(codes) for action, codes in DEFAULT_INPUT_MAP.items()}
    if not saved:
        return mapping

    for action, codes in saved.items():
        if action not in mapping:
            continue
        codes = [int(c) for c in (codes if isinstance(codes, list) else [codes])]
        if not codes:
            continue
        # A calibrated code belongs to exactly one action: drop it everywhere
        # else, then put it first for this action (keeping default fallbacks).
        for other in mapping:
            mapping[other] = [c for c in mapping[other] if c not in codes]
        mapping[action] = codes + [c for c in mapping[action] if c not in codes]
    return mapping


def merge_calibration(
    captured: dict[str, list[int]], saved: dict | None
) -> dict[str, list[int]]:
    """Merge freshly-captured codes over a saved map for re-calibration.

    Untouched actions keep their saved codes, but every freshly-captured code is
    first removed from the other saved actions so a re-binding always wins.
    Without this, resolve_input_map's order-dependent disjoint merge could let an
    untouched action that already held the code keep it, silently dropping the
    new binding.
    """
    captured_codes = {code for codes in captured.values() for code in codes}
    base = {
        action: [code for code in codes if code not in captured_codes]
        for action, codes in (saved or {}).items()
    }
    return {**base, **captured}


def load_saved_input_map() -> dict | None:
    if not INPUT_MAP_FILE.exists():
        return None
    try:
        data = json.loads(INPUT_MAP_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def load_input_map() -> dict[str, list[int]]:
    return resolve_input_map(load_saved_input_map())


def save_input_map(custom: dict[str, list[int]]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = {
        action: [int(c) for c in codes]
        for action, codes in custom.items()
        if action in DEFAULT_INPUT_MAP and codes
    }
    INPUT_MAP_FILE.write_text(
        json.dumps(cleaned, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def action_for(code: int, mapping: dict[str, list[int]]) -> str | None:
    for action, codes in mapping.items():
        if code in codes:
            return action
    return None
