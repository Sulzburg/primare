

# Primare
<img src="https://github.com/Sulzburg/primare/blob/3ad5e096263f1d63c12c37868fba4761c4a53cab/img/icon.png" alt ="Primare Logo" Title="Primare" height="100"/>

Unofficial HA Custom Integration for Primare devices.
<BR>Works only with SP25 & SPA25.
<hr>


<B> 5 Entities:</B>



- Power on/off
- Mute on/off 
- Volume
- Input select
- DSP Mode Select
<img src="https://github.com/Sulzburg/primare/blob/41f4845a108f92d3ddab8491c9cc0bf742541554/img/Primare_entities.jpg" alt="Primare entities" title="Primare" height="250" />
 

<hr>

# Manual Installation

1. Navigate to the [Primare](https://github.com/Sulzburg/primare/tree/main/custom_components/primare) directory.
1. Copy the `primare` folder (including all 8 files) to your Home Assistant `config/custom_components/` directory or use the [primare.zip](https://github.com/Sulzburg/primare/blob/5918922bf769a04a254f4ffbd496d1db2365e494/primare.zip) file and unpack it to your `custom_components/`folder.
1. Restart Home Assistant.
1. Just go to `Configuration` -> `Integrations` -> `Add Integration` and search for `Primare`.
1. You will be asked for the <B>fixed IP address</B> of your Primare device.
1. You will be asked for a name of your Primare device ('name' is part of the entity-ID like `switch.'name'_power`, `number.'name'_volume`).
1. Hit OK.
1. You will find the 5 entities:
 - switch.`name`_power
 - switch.`name`_mute
 - number.`name`_volume
 - select.`name`_input
 - select.`name`_dsp_mode.

That's it.
