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
- One media player per device for everything: power, volume, mute, input and DSP mode – and what the built-in Prisma streamer is playing, with play, pause, stop, skip and seek within a track (where the device reports its length).
- The device page shows the model and the firmware the way the Prisma app does, e.g. `3.15 (Streaming 15644 · Cast 1.52)`.
- Input names, device type and a maximum volume can be set in the UI.
- Actions for stepping and fading the volume, e.g. for automations.

## Installation

### HACS

Primare is in the default HACS catalog, so you can just search for it:

1. In HACS, search for **Primare** and open it.
2. Download it and restart Home Assistant.

If it doesn't show up yet (it can take a little while after a release), add it as a custom repository instead: HACS → ⋮ → **Custom repositories** → add `https://github.com/Sulzburg/primare` as *Integration*, then search for **Primare**, download it and restart Home Assistant.

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
- **Inputs** – one line per input, e.g. `4 = HDMI ARC`. Preset to the factory names of the SP25 (multichannel) and Pre35 (stereo); other stereo models may number their inputs differently.

A new IP address can be entered under **Reconfigure**.

## Entities

| Entity | Multichannel | Stereo | Network player |
|---|---|---|---|
| Media player, named like the device (power, volume, mute, input, DSP mode, playback) | ✓ | ✓ | power, volume, playback |
| Power switch | ✓ | ✓ | ✓ |
| Mute switch | ✓ | ✓ | |
| Volume slider (0–99) | ✓ | ✓ | ✓ |
| Input selection | ✓ | ✓ | |
| DSP mode selection | ✓ | | |

There are also status sensors and volume up/down buttons. Entity names follow the language of Home Assistant (English or German).

## Actions

- `primare.volume_up` / `primare.volume_down` – a few steps louder or quieter
- `primare.volume_relative` – change the volume by a given amount
- `primare.volume_fade` – fade smoothly to a target volume

## Prisma playback

The media player shows what the built-in streamer is playing – title, artist, album, cover, audio format – and lets you play, pause, stop and skip, no matter which app started the music. Playback contributed by [yvos](https://github.com/yvos).

- On another input (e.g. a turntable) the player shows the input name.
- *Play* works from any input and even from standby: the device switches to the streamer and turns on by itself.

The media player also tells which service is playing, e.g. `Roon`, in its attribute `app_name` – handy for automations.

Tested on Pre35 and SP25:

| Source | Title & album | Cover | Audio format | Play / pause |
|---|---|---|---|---|
| Roon | ✓ | – | ✓ | ✓ (also skip) |
| Tidal (Prisma app) | ✓ | ✓ | ✓ | ✓ |
| Qobuz (Prisma app) | ✓ | ✓ | ✓ | |
| UPnP, e.g. MinimServer (Prisma app) | ✓ | ✓ | ✓ | ✓ |
| Chromecast | ✓ | | partly | |

Good to know:

- Switching directly between Tidal and Qobuz in the Prisma app can confuse the device. Stop playback before switching services; if it happens, unplug the device briefly.

## Upgrading

**From 2.x to 3.0:** the separate media player *Wiedergabe* is gone – everything is in the one media player (entity ID `media_player.<name>_steuerung` stays). Point cards or automations that used `media_player.<name>_wiedergabe` to it. Switched off now shows *Off* (Home Assistant no longer supports *Standby*).

**From 1.x:** your entity IDs stay the same, so automations and dashboards keep working. Restart Home Assistant after updating.

## Credits

- [yvos](https://github.com/yvos) – Prisma playback
- [aiolibresync](https://github.com/drsound/aiolibresync) and [ha-libre-luci](https://github.com/six3six/ha-libre-luci) – background on the Prisma streaming module

## License

MIT
