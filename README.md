# Primare

<img src="img/icon.png" alt="Primare" title="Primare" height="100"/>

Unofficial Home Assistant integration for Primare amplifiers, preamplifiers and streamers of the Prisma generation, controlled over the local network. Not affiliated with Primare.

## Supported devices

| Type | Models | Tested |
|---|---|---|
| Multichannel (presets + DSP) | SP25, SPA25 | SP25 |
| Stereo (inputs) | I15, I25, I35, SC15, Pre35 (Prisma) | Pre35 |
| Network player (power + volume) | NP5, NP5 MKII | NP5 MKII |

Other Prisma models that speak the same TCP/IP API on port 50006 should work but are untested.

## Features

- **Local push:** the device reports every change itself (remote, front panel, app) – no polling.
- **Robust connection:** automatic reconnect with backoff, keepalive that detects silent connections, entities become *unavailable* while the device cannot be reached.
- **One device per Primare** with a **media player** ("Control") that bundles power, volume, mute, source and DSP mode (sound mode).
- **Options in the UI:** device type, input/preset names, maximum volume – no code changes needed.
- **Maximum volume:** Home Assistant never sets a higher volume, whatever the source (slider, voice, automation, action). The device itself is not restricted.
- **Prisma playback (optional):** what the built-in streamer is playing – title, artist, album, cover, position, sample rate, bit depth, format – plus play/pause/stop. See [below](#prisma-playback-luci).
- **Actions** for stepping and fading the volume.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories** → `https://github.com/Sulzburg/primare`, category *Integration*.
2. Download **Primare** and restart Home Assistant.

### Manual

1. Download the ZIP of the [latest release](https://github.com/Sulzburg/primare/releases).
2. Copy the `primare` folder to `custom_components/` in your Home Assistant configuration directory.
3. Restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → Primare**, then enter:

- **IP address** of the device (give it a fixed address in your router)
- **Port** – default `50006`
- **Name** – becomes the device name and entity prefix, e.g. `SP25` → `switch.sp25_power`
- **Device type** – Multichannel, Stereo or Network player

The connection is tested before the entry is created.

### Options ("Configure")

| Option | Meaning |
|---|---|
| Device type | Multichannel / Stereo / Network player |
| Maximum volume | 1–99, default 99 (no limit) |
| Inputs / presets | one line per input: `number = name`, e.g. `4 = HDMI ARC` (numbers 1–17) |
| Show Prisma streamer playback | adds the playback media player (off by default) |

IP address and port can be changed with **Reconfigure**.

## Entities

| Entity | Multichannel | Stereo | Network player |
|---|---|---|---|
| `media_player.<name>_steuerung` – control (power, volume, mute, source, sound mode) | ✓ | ✓ | power + volume |
| `switch.<name>_power` | ✓ | ✓ | ✓ |
| `switch.<name>_mute` | ✓ | ✓ | |
| `number.<name>_volume` (0–99, ends at the maximum volume) | ✓ | ✓ | ✓ |
| `select.<name>_input` | ✓ | ✓ | |
| `select.<name>_dsp_mode` | ✓ | | |
| `sensor.<name>_volume` (status, kept for compatibility) | ✓ | ✓ | ✓ |
| `sensor.<name>_input` (status, kept for compatibility) | ✓ | ✓ | |
| `sensor.<name>_dsp_mode` (status, kept for compatibility) | ✓ | | |
| `button.<name>_vol_up` / `_vol_down` (kept for compatibility) | ✓ | ✓ | ✓ |
| `media_player.<name>_wiedergabe` – Prisma playback (optional) | ✓ | ✓ | ✓ |

Volume is always the device's own value (0–99); the media player shows it as 0–100 %. The two media players are currently named in German ("Steuerung" = control, "Wiedergabe" = playback).

## Actions

| Action | Purpose |
|---|---|
| `primare.volume_up` / `primare.volume_down` | step the volume, `times` 1–10 |
| `primare.volume_relative` | change by `delta`, as steps or absolute |
| `primare.volume_fade` | fade to `target` over `duration_ms` with easing; a running fade on the same device is cancelled |

Select the device with `device_id` (recommended). `entry_id` and `device_name` still work.

## Prisma playback (LUCI)

The Prisma streaming module has a second interface besides the documented API: **LUCI** on TCP port 7777. It reports what the streamer is playing, independent of which app or account started it. This part was written by **[yvos](https://github.com/yvos)** – thank you!

Enable it per device under **Configure → Show Prisma streamer playback**.

Tested on a Pre35:

| Source | Title/album | Cover | Sample rate / bits | Format | Bit rate | Play/pause |
|---|---|---|---|---|---|---|
| Roon | ✓ | – | ✓ | pcm | – | ✓ (Roon follows) |
| Tidal (Prisma app) | ✓ | ✓ | ✓ | FLAC | ✓ | ✓ |
| Qobuz (Prisma app) | ✓ | ✓ | ✓ | FLAC | ✓ | not tested |
| UPnP / MinimServer (Prisma app) | ✓ | ✓ | ✓ | FLAC | see below | ✓ |
| Qobuz via Chromecast | ✓ | ? | bits only | – | – | not tested |

Known limitations:

- **Next / previous / seek** are not offered on the Pre35 – the device never reports them as available.
- **Bit rate** appears to be reported in bytes/s for UPnP sources.
- **Switching directly between Tidal and Qobuz** in the Prisma app confuses the device: position and track changes are wrong afterwards – the Prisma app shows the same. Stop playback before switching services.
- LUCI has **no authentication**; anyone on the local network can talk to it. The integration only sends the few messages whose effect is known.

Background on LUCI: [aiolibresync](https://github.com/drsound/aiolibresync) (detailed protocol documentation) and [ha-libre-luci](https://github.com/six3six/ha-libre-luci).

## Upgrading from 1.x

Entity IDs are kept. On first start the internal IDs are migrated and the entities are attached to a new device per Primare. Your automations and dashboards keep working. Input names are taken over; set them under **Configure** if you used different ones.

## Tests

```bash
python -m unittest discover -s tests
```

The tests run against simulated devices and do not need Home Assistant.

## Credits

- [yvos](https://github.com/yvos) – Prisma playback via LUCI, tests and HACS validation
- [aiolibresync](https://github.com/drsound/aiolibresync) and [ha-libre-luci](https://github.com/six3six/ha-libre-luci) – LUCI documentation

## License

MIT
