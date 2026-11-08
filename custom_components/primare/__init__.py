"""Set up local Primare controls."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant

from .const import DOMAIN, INPUT_MAPS
from .coordinator import PrimareDataCoordinator

PLATFORMS = ["switch", "number", "select"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    device_type = entry.data.get("device_type", "Multichannel")
    input_map = INPUT_MAPS.get(device_type, {})
    coordinator = PrimareDataCoordinator(
        entry.data["ip_address"], input_map, device_type == "Multichannel"
    )
    entries = hass.data.setdefault(DOMAIN, {})
    entries[entry.entry_id] = {
        "coordinator": coordinator,
        "device_type": device_type,
        "input_map": input_map,
    }

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except BaseException:
        entries.pop(entry.entry_id, None)
        raise

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, coordinator.async_stop))
    coordinator.async_start(hass, entry)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    data = hass.data[DOMAIN].pop(entry.entry_id)
    await data["coordinator"].async_stop()
    return True
