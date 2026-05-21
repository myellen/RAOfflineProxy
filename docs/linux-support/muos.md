# muOS

muOS (MustardOS) is an **experimental** Linux target for `RAOfflineProxy`,
covering the Allwinner H700 Anbernic family (RG35XX H / Plus, RG40XX, and
similar).

It reuses the shared Linux core unchanged — RetroAchievements forwarding,
offline cache, softcore award queueing, RetroArch config patching, and the
controller-driven SDL menu are identical to the other Linux targets. Only the
install and launch integration is muOS-specific.

## Install

1. Download `RAOfflineProxy-<version>.muxapp`.
2. Copy it into the **`ARCHIVE`** folder on the SD card (`<SD>/ARCHIVE`).
3. On the device, open **Applications → Archive Manager** and install it.
4. Launch **RAOfflineProxy** from the **Applications** menu.

`<SD>` is the active card mount — SD1 (`/mnt/mmc`) or SD2 (`/mnt/sdcard`); the
launcher resolves it automatically.

## Usage

The on-device menu is the same as the other Linux targets: Start / Stop proxy,
Cached Games (with Add ROM), Pending Awards, Controls, and Uninstall.

- **Controls** runs a button-calibration screen. muOS button layouts differ
  between devices, so if confirm/back/d-pad don't behave as expected, open
  Controls and press each requested button — the menu then uses your device's
  actual codes. It finishes with a **Test Controls** screen that names the
  action for each button you press (press Back to finish), so you can confirm
  the mapping before relying on it.

- **Log into RetroAchievements in RetroArch first.** "Cached games" only appears
  once RetroArch has a `cheevos_token` (or username + password) configured.
- The proxy patches the muOS RetroArch config at
  `<SD>/MUOS/info/config/retroarch.cfg` while active and reverts it on stop /
  uninstall.
- All cache, login, token, and queue data lives inside the app folder
  (`<SD>/MUOS/application/RAOfflineProxy`), so it survives reboots and is fully
  removed on uninstall.

## Diagnostics

Every launch writes a single report to the SD card root,
`<SD>/RAOFFLINEPROXY-REPORT.txt`, with a top-line `VERDICT:` and a
`[PASS]`/`[WARN]`/`[FAIL]` line per startup check (Python, pygame/SDL, display,
controllers, fonts, RetroArch config + login, network). If the app does not
start, that one file explains why.

## Current limitations

- Experimental; verified in emulation against muOS's runtime constraints
  (aarch64, glibc ≥ 2.28, Python 3.11) but still maturing on physical hardware.
- Autostart is not wired for muOS yet — start the proxy from the menu.
- Hardcore mode is unsupported (softcore only), as on every target.

## Build

Build instructions, the offline-`pygame` bundling step, and the full layout are
documented in
[`linux/muos/README.md`](https://github.com/misantronic/RAOfflineProxy/blob/main/linux/muos/README.md).
