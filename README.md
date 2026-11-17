# Primare

<img src="img/icon.png" alt="Primare" title="Primare" height="100"/>

Unofficial Home Assistant integration for Primare devices of the Prisma generation. Control power, volume, mute, input and DSP mode from Home Assistant – and optionally see what the built-in streamer is playing. Not affiliated with Primare.

## Supported devices

| Type | Models |
|---|---|
| Multichannel | SP25, SPA25 |
| Stereo | I15, I25, I35, SC15, Pre35 (Prisma) |
| Network player | NP5, NP5 MKII |

Tested with SP25, Pre35 and NP5 MKII.

## Features

- Changes made on the device, the remote or the Prisma app show up in Home Assistant immediately.
- Reconnects on its own if the device was switched off or the network was interrupted.
- One device per Primare with a media player for power, volume, mute, input and DSP mode.
- Input names, device type and a maximum volume can be set in the UI.
- Optional: what the built-in Prisma streamer is playing – title, artist, album, cover, audio format – with play, pause and stop.
- Actions for stepping and fading the volume, e.g. for automations.

## Installation

### HACS

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/Sulzburg/primare` as *Integration*.
2. Search for **Primare**, download it and restart Home Assistant.

### Manual

1. Download `primare.zip` from the [latest release](https://github.com/Sulzburg/primare/releases/latest).
2. Unpack it into the `custom_components` folder of your Home Assistant configuration.
3. Restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → Primare**

- **IP address** of the device – best give it a fixed address in your router
- **Port** – leave it at `50006`
- **Name** – e.g. `SP25`; your entities will be called `switch.sp25_power`, `number.sp25_volume` and so on
- **Device type** – Multichannel, Stereo or Network player

### Options

Under **Configure** you can change:

- **Device type**
- **Maximum volume** – Home Assistant will never turn the volume higher than this, whether by slider, voice command or automation. The device itself is not limited.
- **Inputs** – one line per input, e.g. `4 = HDMI ARC`
- **Show Prisma streamer playback** – see below

A new IP address can be entered under **Reconfigure**.

## Entities

| Entity | Multichannel | Stereo | Network player |
|---|---|---|---|
| Media player "Steuerung" (power, volume, mute, input, DSP mode) | ✓ | ✓ | power and volume |
| Power switch | ✓ | ✓ | ✓ |
| Mute switch | ✓ | ✓ | |
| Volume slider (0–99) | ✓ | ✓ | ✓ |
| Input selection | ✓ | ✓ | |
| DSP mode selection | ✓ | | |
| Media player "Wiedergabe" (Prisma playback, optional) | ✓ | ✓ | ✓ |

There are also status sensors and volume up/down buttons.

## Actions

- `primare.volume_up` / `primare.volume_down` – a few steps louder or quieter
- `primare.volume_relative` – change the volume by a given amount
- `primare.volume_fade` – fade smoothly to a target volume

## Prisma playback

Turn it on per device under **Configure → Show Prisma streamer playback**. You get a media player that shows what the streamer is playing and lets you play, pause and stop – no matter which app started the music. Contributed by [yvos](https://github.com/yvos).

Tested on a Pre35:

| Source | Title & album | Cover | Audio format | Play / pause |
|---|---|---|---|---|
| Roon | ✓ | – | ✓ | ✓ |
| Tidal (Prisma app) | ✓ | ✓ | ✓ | ✓ |
| Qobuz (Prisma app) | ✓ | ✓ | ✓ | |
| UPnP, e.g. MinimServer (Prisma app) | ✓ | ✓ | ✓ | ✓ |
| Chromecast | ✓ | | partly | |

Good to know:

- Next, previous and seeking are not available on the Pre35.
- Switching directly between Tidal and Qobuz in the Prisma app can confuse the device (wrong track time). Stop playback before switching services.

## Upgrading from version 1

Your entity IDs stay the same, so automations and dashboards keep working. Restart Home Assistant after updating.

## Credits

- [yvos](https://github.com/yvos) – Prisma playback
- [aiolibresync](https://github.com/drsound/aiolibresync) and [ha-libre-luci](https://github.com/six3six/ha-libre-luci) – background on the Prisma streaming module

## License

MIT
