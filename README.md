# Primare

Unofficial HA Custom_Integration for Primare.
<BR>Works only with SP25 & SPA25
<hr>


<B> 5 Entities:</B>


- Volume
- Power on/off
- Mute on/off 
- Input select
- DSP Select
<img src="https://github.com/Sulzburg/primare/blob/41f4845a108f92d3ddab8491c9cc0bf742541554/img/Primare_entities.jpg" alt="Primare entities" title="Primare" height="250" />
 

<hr>

# Manual Installation

1. Navigate to the [Primare](https://github.com/Sulzburg/primare/tree/main/custom_components/primare) directory.
1. Copy the `primare` folder (including all 8 files) to your Home Assistant `config/custom_components/` directory.
1. Restart Home Assistant.
1. Just go to `Configuration` -> `Integrations` -> `Add Integration` and search for `Primare`.
1. You will be asked for the <B>fixed IP address</B> of your Primare device.
1. You will be asked for a name of your Primare device ('name' is part of the entity-ID like `switch.'name'_power`, `number.'name'_volume`)
1. Hit OK

That's it.
