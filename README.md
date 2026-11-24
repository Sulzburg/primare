# Primare

<img src="img/icon.png" alt="Primare" title="Primare" height="100"/>

Unofficial Home Assistant integration for Primare Prisma devices. Control power, volume, mute, input and DSP mode from Home Assistant – and optionally see what the built-in streamer is playing. Not affiliated with Primare.

## Supported devices

| Type | Models (Prisma) |
|---|---|
| Home cinema | SP25, SPA25 |
| Pre/integrated amplifier | I15, I25, I35, SC15, Pre35 |
| Network player | NP5, NP5 MKII |

Tested with SP25, Pre35 and NP5 MKII. CD15 / CD35 untested – assumed to behave like the network player.

## Features

- Changes made on the device, the remote or the Prisma app show up in Home Assistant immediately.
- Reconnects on its own if the device was switched off or the network was interrupted.
- One media player per device for everything: power, volume, mute, input and DSP mode – and what the built-in Prisma streamer is playing, with play, pause, stop, skip and seek within a track (where the device reports its length).
- When the active input or output is set to a fixed volume, the volume control is hidden automatically – with a `volume_fixed` attribute for automations.
- The device page shows the model and the firmware the way the Prisma app does, e.g. `3.15 (Streaming 15644 · Cast 1.52)`.
- Input names, device type and a maximum volume can be set in the UI.
- Actions for stepping and fading the volume, e.g. for automations.

## Installation

### HACS

Primare is in the default HACS catalog: search for **Primare**, download it and restart Home Assistant.

### Manual

If Primare doesn't show up in HACS yet (it can take a little while after a release), add it as a custom repository: HACS → ⋮ → **Custom repositories** → add `https://github.com/Sulzburg/primare` as *Integration*, then search for **Primare**, download it and restart Home Assistant.

Or install it by hand: download `primare.zip` from the [latest release](https://github.com/Sulzburg/primare/releases/latest), unpack it into the `custom_components` folder of your Home Assistant configuration, and restart Home Assistant.

## Setup

**Settings → Devices & services → Add integration → Primare**

- **IP address** of the device – reserve a fixed address for it in your router, otherwise the connection breaks when the address changes (fix it afterwards under **Reconfigure**).
- **Name** – e.g. `SP25`; your entities will be called `switch.sp25_power`, `number.sp25_volume` and so on
- **Device type** – Home cinema, Pre/integrated amplifier, CD player or Network player

### Options

Under **Configure** you can change:

- **Device type**
- **Maximum volume** – Home Assistant will never turn the volume higher than this, whether by slider, voice command or automation. The device itself is not limited.
- **Inputs** – one line per input, e.g. `4 = HDMI ARC`. Preset to the factory names of the SP25 (home cinema) and Pre35 (pre/integrated amplifier); other models may number their inputs differently.

A new IP address can be entered under **Reconfigure**.

## Entities

| Entity | Home cinema | Pre/integrated amp. | Network / CD player |
|---|---|---|---|
| Media player, named like the device (power, volume, mute, input, DSP mode, playback) | ✓ | ✓ | power, volume, playback |
| Power switch | ✓ | ✓ | ✓ |
| Mute switch | ✓ | ✓ | – |
| Volume slider (0–99) | ✓ | ✓ | ✓ |
| Volume up / down buttons | ✓ | ✓ | ✓ |
| Input selection | ✓ | ✓ | – |
| DSP mode selection | ✓ | – | – |
| Status sensor – volume | ✓ | ✓ | ✓ |
| Status sensor – input | ✓ | ✓ | – |
| Status sensor – DSP mode | ✓ | – | – |

Entity names follow the language of Home Assistant.

## Actions

- `primare.volume_up` / `primare.volume_down` – a few steps louder or quieter
- `primare.volume_relative` – change the volume by a given amount
- `primare.volume_fade` – fade smoothly to a target volume

## Prisma playback

The media player shows what the built-in streamer is playing – title, artist, album, cover, audio format – and lets you play, pause, stop and skip, no matter which app started the music. Playback contributed by [yvos](https://github.com/yvos).

- On another input (e.g. a turntable) the player shows the input name.
- When playback starts – from Roon, the Prisma app or any other source – the device switches to the streamer input and wakes from standby on its own.
- Home Assistant's *Play* resumes whatever the streamer last had queued; it can't pick the music by itself.

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
