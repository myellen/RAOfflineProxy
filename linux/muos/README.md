# RAOfflineProxy on muOS

Experimental [muOS (MustardOS)](https://muos.dev) support for `RAOfflineProxy`.

muOS is a Linux firmware for aarch64 handhelds, so this target reuses the shared
Linux core in [`linux/raofflineproxy/`](../raofflineproxy) unchanged. Only the
install and launch integration is muOS-specific.

> **Status: verified on hardware (beta).** Confirmed end-to-end on an Anbernic
> RG35XX-H running muOS 2601 "Jacaranda": the menu renders on the framebuffer, the
> proxy patches the RetroArch config (global + the appended `retroarch.cheevos.cfg`),
> and offline RetroAchievements — login and cached games — works through the proxy.
> See [Beta testing](#beta-testing).

## What it does

- Installs as a muOS **Application** at `<SD>/MUOS/application/RAOfflineProxy`
- Adds a controller-driven menu (Start/Stop proxy, Cached Games, Pending Awards,
  Add ROM, Controls, Uninstall) — the same SDL menu used by the KNULLI target,
  plus a muOS-only Controls (button calibration) screen
- Patches the muOS RetroArch config while active:
  - `cheevos_enable = "true"`
  - `cheevos_custom_host = "<proxy_host>:<proxy_port>"`
  - `cheevos_hardcore_mode_enable = "false"`
- Keeps all cache/login/token/queue data inside the app folder so it survives
  reboots and firmware updates and never writes to the system rootfs

Hardcore mode is **not** supported (softcore only), same as every other target.

> **Required muOS setting — turn on "RetroArch Config Freedom"** (muOS 2508 or newer).
> Settings > Advanced > *RetroArch Config Freedom* must be **On**. With it off
> (the muOS default), muOS deletes and re-copies the global `retroarch.cfg` from
> its template on every launch (`func.sh` `CONFIGURE_RETROARCH`), which wipes the
> `cheevos_custom_host` patch — so RetroArch launches pointing at the real RA
> server and never reaches the proxy. The app surfaces a warning on the main
> screen and in the diagnostics report when it's off.
>
> muOS keeps the RetroAchievements **login** (`cheevos_username`/`cheevos_token`)
> in a *separate* `retroarch.cheevos.cfg` that it `--appendconfig`s at launch (and
> it blanks `cheevos_*` in the global cfg). The app reads that sibling file
> directly, so login is detected without Freedom mode — only the redirect needs it.

## muOS specifics this target relies on

| Concern            | muOS location (resolved at runtime)                  |
| ------------------ | ---------------------------------------------------- |
| App folder         | `<SD>/MUOS/application/RAOfflineProxy`                |
| RetroArch config   | `<SD>/MUOS/info/config/retroarch.cfg`                |
| ROMs               | `<SD>/ROMS`                                          |
| App data / cache   | `<SD>/MUOS/application/RAOfflineProxy/data`           |
| Glyph (icon)       | `/opt/muos/default/MUOS/theme/active/glyph/muxapp/`  |

`<SD>` is the active card mount: SD1 = `/mnt/mmc`, SD2 = `/mnt/sdcard`. On a real
device `mux_launch.sh` resolves it with `GET_VAR "device" "storage/rom/mount"`;
off-device it falls back to whichever card carries a `MUOS/` tree. Dual-SD setups
work because the launcher keys off the card the app was installed on.

## Build

From the repo root:

```bash
./linux/muos/build_bundle.sh
```

This produces:

```text
linux/muos/dist/RAOfflineProxy-<version>.muxapp
```

A `.muxapp` is just a zip that muOS Archive Manager extracts **into**
`MUOS/application/`, so the archive carries the app folder at its root —
`RAOfflineProxy/mux_launch.sh`, not `MUOS/application/RAOfflineProxy/...`
(matching how RomM and other muOS apps are packaged). The build script uses
Python's `zipfile`, so no `zip` binary is required.

### Bundling pygame for a fully offline build (recommended for releases)

The proxy/service core is stdlib-only; only the on-device **menu** needs
`pygame`. Without bundling, the launcher installs it via `pip` on first run,
which requires a one-time Wi-Fi connection — and if Wi-Fi is off the menu can't
open. The **released `.muxapp` bundles pygame** so it needs no network and no
pip at all.

Fetch aarch64 wheels for the CPython ABIs you want to support (muOS is glibc
>= 2.28 / Python 3.11, but bundling cp310–cp313 makes the build work regardless
of the device's exact Python minor version), then build:

```bash
for v in 310 311 312 313; do
  pip download pygame --no-deps --only-binary=:all: \
    --platform manylinux_2_28_aarch64 --platform manylinux2014_aarch64 \
    --python-version $v --implementation cp --abi cp$v -d /tmp/pgwheels
done

./linux/muos/build_bundle.sh --with-pygame /tmp/pgwheels
```

`--with-pygame` unpacks each wheel into `vendor/<abi>/` (e.g. `vendor/cp311`),
stripping examples/tests/docs. At launch the script selects the `vendor/<abi>`
matching the device's interpreter, so the menu imports pygame directly — no pip,
no network. If the device's ABI isn't bundled, the launcher falls back to a
network `pip install`. Bundling all four ABIs adds only ~3 MB versus one (the
native libraries dominate), keeping the `.muxapp` around 30 MB.

## Install on muOS

1. Copy `RAOfflineProxy-<version>.muxapp` into the **`ARCHIVE`** folder on the SD
   card (`<SD>/ARCHIVE`).
2. On the device: **Applications > Archive Manager**, select the archive, install.
3. Launch **RAOfflineProxy** from the **Applications** menu.

First launch may take a moment if `pygame` is being installed.

## Layout

```text
linux/muos/
  build_bundle.sh                       # produces the .muxapp
  application/RAOfflineProxy/
    mux_launch.sh                        # muOS entry point (HELP/ICON header)
    common.sh                            # env + python/pygame resolution
    resources/raofflineproxy.png         # Applications-list glyph (added at build)
    app/raofflineproxy/                  # shared Linux core (copied at build)
```

## Uninstall

Use **Uninstall** inside the RAOfflineProxy menu. It stops the proxy and reverts
the RetroArch config patch. To remove the app entirely, delete
`<SD>/MUOS/application/RAOfflineProxy` (this also clears cached game/login/queue
data, since everything lives under the app folder).

## Beta testing

This target needs a pass on real hardware. The frictionless loop:

1. Build the `.muxapp` and send it to the tester.
2. They drop it in `ARCHIVE`, install via Archive Manager, and run it.
3. **Every launch writes one diagnostics file to the SD card root:**

   ```text
   <SD>/RAOFFLINEPROXY-REPORT.txt
   ```

   It's at the top level on purpose — when the tester pops the SD card into any
   computer it's right there, no folder digging. The first line is a `VERDICT:`
   (`OK` or `FAILED (<what failed>)`), followed by a `[PASS]`/`[WARN]`/`[FAIL]`
   line per check (python version, pygame import + SDL driver, framebuffer/KMS
   devices, controllers, fonts, RetroArch config + login state, network reach).
   **Sending back that single file diagnoses almost any startup failure in one
   round trip** — even a black screen or instant exit, because the report is
   written before the menu starts and again on any fatal launcher error.

   Backup copies live at `.../logs/diagnostics.txt`, `.../logs/launch.log`, and
   the menu's own `.../data/menu-sdl.log`.

### Heads-up for the tester

- **Required: enable RetroArch Config Freedom** (Settings > Advanced). Off by
  default; without it muOS resets `retroarch.cfg` every launch and the proxy
  redirect never sticks. The main screen shows `ENABLE RA CONFIG FREEDOM` and the
  report flags it when it's off.
- **"Cached games" only appears after you've logged into RetroAchievements in
  RetroArch.** muOS saves the login to `MUOS/info/config/retroarch.cheevos.cfg`
  (a separate file from `retroarch.cfg`); the app reads it there. Before you log
  in, the menu shows Start / Controls / Uninstall / Exit (no Cached games) — this
  is expected, not a bug. Log in first, then re-open the app.

### Validated off-device (x86 + emulated aarch64)

- Core logic: the full Linux unit-test suite passes on both x86_64 and aarch64
- The arm64 `pygame` wheel (2.6.1 / SDL 2.28.4) imports and the menu renders
  under emulation
- Font handling degrades gracefully: if `fontconfig`/`fc-list` or DejaVu/Noto
  fonts are absent, the menu falls back to pygame's built-in font instead of
  crashing (confirmed on a fontless aarch64 image)
- The muOS env overrides flow into the live UI (the ROM browser uses
  `RAOFFLINEPROXY_ROMS_ROOT`)
- The bundled pygame's SDL was inspected: it ships x11/wayland/dummy but not
  kmsdrm/fbcon, which is why the launcher overlays muOS's system SDL (see below)
- **muOS's SDL was extracted from the official 2601.1 image and verified: SDL
  2.28.5** (`/usr/lib/libSDL2-2.0.so.0.2800.5`), which is **>= the 2.28.4 our
  pygame is built against** — so the system-SDL overlay is symbol-compatible.
  muOS's own UI renders with this SDL, confirming it drives the framebuffer.
  (muOS also ships SDL2_image 2.8.2 / SDL2_ttf 2.22.0; only the core SDL2 is
  overlaid, so pygame keeps its own image/ttf/mixer.)
- **Symbol/ABI compatibility proven, not assumed:** pygame's modules reference
  202 core SDL symbols (its bundled SDL2_image/ttf another 63); muOS's libSDL2
  exports 842 and is missing **0** of them — checked against the extracted lib.
- **muOS's SDL video driver is `mali`** (a single Allwinner vendor backend; no
  kmsdrm/fbcon/dummy compiled in). Confirmed by loading the extracted libSDL2
  under aarch64 emulation and calling `SDL_GetVideoDriver`. This is why the
  overlay is *required* (pygame's desktop SDL has no driver that works on muOS)
  and why the diagnostics probe tries the default driver, not just kmsdrm/fbcon.
- **The overlay was exercised end-to-end** against muOS's real SDL: running the
  production `link_system_sdl` flips pygame from its bundled SDL 2.28.4 to muOS's
  2.28.5, `import pygame` succeeds, and pygame then exposes the `mali` driver.
  The only thing left untested is the physical render on real H700 hardware
  (Mali GPU + framebuffer), which no emulator can reproduce.

### Still device-only — confirm on real muOS hardware

- Whether `python3` on the device is >= 3.10 (the launcher checks and logs if not)
- **SDL framebuffer display.** The pygame wheel bundles a *desktop* SDL (no
  kmsdrm/fbcon), so the launcher (`link_system_sdl`) overlays muOS's own
  framebuffer-capable core `/usr/lib/libSDL2` (verified SDL 2.28.5 on 2601.1,
  see above). Best-effort and self-healing: reverts if the system SDL is ever
  ABI-incompatible, and the diagnostics report shows which video drivers
  actually initialize. Confirmed compatible for 2601.1; a future muOS that
  ships an older SDL would be caught by the diagnostics `>= 2.28.4` check.
  As extra insurance, the launcher also probes SDL's default video driver
  before starting the menu and only forces an alternative if the default fails
  to initialize (a no-op on muOS, where the default `mali` driver works).
- Controller mapping: the menu reads raw evdev codes with sensible multi-code
  defaults (`BTN_SOUTH`/`START`/Enter to confirm, `BTN_EAST`/`SELECT`/Backspace
  to go back, d-pad via arrows/hat/`BTN_DPAD_*`). muOS button layouts vary, so if
  a device's buttons don't match, the **Controls** menu item runs a calibration
  screen that records each device's actual codes (saved to
  `<data>/input_map.json`), then a **Test Controls** screen that names the action
  for each button pressed so the mapping can be verified. This makes the mapping
  device-independent rather than a hardcoded guess.
- The exact active `retroarch.cfg` path on the tester's muOS version (the launcher
  exports the documented `<SD>/MUOS/info/config/retroarch.cfg`; override with
  `RAOFFLINEPROXY_RETROARCH_CFG` if it differs)
- Autostart is intentionally left unwired for muOS in this first cut

### Useful overrides (for debugging)

The launcher honors these environment variables:

- `RAOFFLINEPROXY_PYTHON` — explicit python interpreter
- `RAOFFLINEPROXY_RETROARCH_CFG` — override the RetroArch config path
- `RAOFFLINEPROXY_ROMS_ROOT` — override the ROM root
- `RAOFFLINEPROXY_MUOS_MOUNT` — force the SD mount (`/mnt/mmc` or `/mnt/sdcard`)
