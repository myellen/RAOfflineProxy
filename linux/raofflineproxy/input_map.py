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

ACTIONS = ["confirm", "back", "up", "down", "left", "right"]
ACTION_LABELS = {
    "confirm": "Confirm / Select",
    "back": "Back / Cancel",
    "up": "D-pad Up",
    "down": "D-pad Down",
    "left": "D-pad Left",
    "right": "D-pad Right",
}

DEFAULT_INPUT_MAP: dict[str, list[int]] = {
    "confirm": [KEY_ENTER, KEY_SPACE, KEY_S, BTN_SOUTH, BTN_START],
    "back": [KEY_ESC, KEY_BACKSPACE, KEY_Q, BTN_EAST, BTN_SELECT],
    "up": [KEY_UP, BTN_DPAD_UP],
    "down": [KEY_DOWN, BTN_DPAD_DOWN],
    "left": [KEY_LEFT, BTN_DPAD_LEFT],
    "right": [KEY_RIGHT, BTN_DPAD_RIGHT],
}


def resolve_input_map(saved: dict | None) -> dict[str, list[int]]:
    mapping = {action: list(codes) for action, codes in DEFAULT_INPUT_MAP.items()}
    if not saved:
        return mapping

    for action, codes in saved.items():
        if action not in mapping:
            continue
        codes = [int(c) for c in (codes if isinstance(codes, list) else [codes])]
        if not codes:
            continue
        for other in mapping:
            mapping[other] = [c for c in mapping[other] if c not in codes]
        mapping[action] = codes + [c for c in mapping[action] if c not in codes]
    return mapping


def merge_calibration(
    captured: dict[str, list[int]], saved: dict | None
) -> dict[str, list[int]]:
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
