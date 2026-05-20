# RAOfflineProxy on muOS

Experimental [muOS (MustardOS)](https://muos.dev) support for `RAOfflineProxy`.

muOS is a Linux firmware for aarch64 handhelds, so this target reuses the shared
Linux core in [`linux/raofflineproxy/`](../raofflineproxy) unchanged. Only the
install and launch integration is muOS-specific.

> **Status: beta / unverified on hardware.** The packaging and path handling are
> built against documented muOS conventions and tested in a simulated layout, but
> have not yet been confirmed on a physical device. See
> [Beta testing](#beta-testing).

## What it does

- Installs as a muOS **Application** at `<SD>/MUOS/application/RAOfflineProxy`
- Adds a controller-driven menu (Start/Stop proxy, Cached Games, Pending Awards,
  Add ROM, Uninstall) — the same SDL menu used by the KNULLI target
- Patches the muOS RetroArch config while active:
  - `cheevos_enable = "true"`
  - `cheevos_custom_host = "<proxy_host>:<proxy_port>"`
  - `cheevos_hardcore_mode_enable = "false"`
- Keeps all cache/login/token/queue data inside the app folder so it survives
  reboots and firmware updates and never writes to the system rootfs

Hardcore mode is **not** supported (softcore only), same as every other target.

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

A `.muxapp` is just a zip whose contents extract relative to the SD root (it
carries a top-level `MUOS/application/RAOfflineProxy/` tree). The build script
uses Python's `zipfile`, so no `zip` binary is required.

### Optional: bundle pygame for fully offline first-run

The proxy/service core is stdlib-only; only the on-device **menu** needs
`pygame`. By default the launcher installs it via `pip` on first run (a one-time
Wi-Fi step). To ship a `.muxapp` that needs no network at all, bundle aarch64
wheels matching the device's CPython ABI:

```bash
# wheels must match the device's python (e.g. cp311) and aarch64
./linux/muos/build_bundle.sh --with-pygame /path/to/aarch64/wheels
```

The launcher then prefers the bundled wheels (`--no-index`) before touching the
network.

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
3. If anything misbehaves, the launcher writes a single log here:

   ```text
   <SD>/MUOS/application/RAOfflineProxy/logs/launch.log
   ```

   plus the menu's own log at `.../data/menu-sdl.log`. Sending those two files
   back is enough to diagnose most issues.

### Known unknowns to confirm on-device

- Whether `python3` on the device is >= 3.10 (the launcher checks and logs if not)
- Whether `pygame` installs/imports cleanly with muOS's SDL libraries in `/usr/lib`
- Whether the SDL menu reads controller input via `/dev/input` without muOS
  grabbing the devices first
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
