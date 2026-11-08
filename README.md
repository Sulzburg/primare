

# Primare
<img src="https://github.com/Sulzburg/primare/blob/3ad5e096263f1d63c12c37868fba4761c4a53cab/img/icon.png" alt ="Primare Logo" Title="Primare" height="100"/>

Unofficial HA Custom Integration for Primare devices.
<BR>Works only with X5 Serie Models.


<B>Multichannel:</B>
 - SP25
 - SPA25

<B>Stereo:</B>
 - I15 Prisma
 - I25 Prisma
 - I35 Prisma
 - SC15 Prisma
 - Pre35 Prisma

<B>Streamer:</B>
 - NP5
 - NP5 MKII
 
<hr>

<B> 5 Entities:</B>



- Power on/off
- Mute on/off 
- Volume
- Input select
- DSP Mode Select (only Multichannel devices)
  
<img src="https://github.com/Sulzburg/primare/blob/b0a8f18e2001d32019d3e91c47b31b0269a3d4f7/img/Primare_multichannel_entities.jpg" alt="Primare entities" title="Primare" height="250" width="380" /> <img src="https://github.com/Sulzburg/primare/blob/b05c867286f1b113bce947fe3ea56dcff6d2b2a5/img/Primare_stereo_entities.jpg" alt="Primare entities" title="Primare" height="230" width="380" />
 

<hr>

# Manual Installation

1. Navigate to the [Primare](https://github.com/Sulzburg/primare/tree/main/custom_components/primare) directory.
1. Copy the entire lowercase `primare` folder into your Home Assistant `/config/custom_components/` directory. You can also download the [current source ZIP](https://github.com/Sulzburg/primare/archive/refs/heads/main.zip) and copy `custom_components/primare` from the extracted archive. Create `custom_components` if needed.
1. Restart Home Assistant.
1. Just go to `Configuration` -> `Integrations` -> `Add Integration` and search for `Primare`.
1. You will be asked for the <B>fixed IP address or hostname</B> of your Primare device.
1. Choose a display name. Home Assistant uses it to suggest entity IDs such as `switch.living_room_power` and `number.living_room_volume`.
1. Select Multichannel or Stereo device.
1. Hit OK.
1. You will find the following entities:
 - switch.`name`_power
 - switch.`name`_mute
 - number.`name`_volume
 - select.`name`_input
 - select.`name`_dsp_mode (Multichannel only).

Controls show unavailable until the device reports their values. If the device is offline, the integration reconnects automatically. An unconfirmed control command is reported as an error and is not sent again.

The old `v0.0.1` release predates the current integration layout. Use the current source for manual installation until a new release is published.

<hr>

<B>Hints:</B>

If you want to rename the inputs:
open `custom_components/primare/const.py` with the file editor and replace the names.
e.g.:

`   1: “Preset1”, `  ->  `   1: “BluRay”, `

if you want to exclude an entry, place a # in front of the corresponding line.
e.g.:

`#  7: "SAT/Receiver",`

Hit save.

Restart HA to take effect.

