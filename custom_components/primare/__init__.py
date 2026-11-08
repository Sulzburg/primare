# custom_components/primare/__init__.py

import homeassistant.helpers.config_validation as cv
from .coordinator import PrimareDataCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, INPUT_MAPS

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

PLATFORMS = ["switch", "number", "select", "media_player"]

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Basis-Setup, nur erforderlich für die Registrierung der Integration."""
    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    ip_address = config_entry.data["ip_address"]
    device_name = config_entry.data["device_name"]
    device_type = config_entry.data.get("device_type", "Multichannel")  # Default = SP25

    from . import const

    # Eingänge je nach Gerätetyp vorbereiten
    input_map = const.INPUT_MAPS.get(device_type, {})
    input_map_inv = {v: k for k, v in input_map.items()}

    coordinator = PrimareDataCoordinator(ip_address, device_name, hass.loop, hass, config_entry.entry_id)
    await coordinator.async_start()

    # Speichere alle Daten pro Config Entry
    hass.data.setdefault(DOMAIN, {})[config_entry.entry_id] = {
        "coordinator": coordinator,
        "device_type": device_type,
        "device_name": device_name,
        "input_map": input_map,
        "input_map_inv": input_map_inv,
    }

    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    config_entry.async_on_unload(config_entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    data = hass.data[DOMAIN].pop(entry.entry_id)
    await data["coordinator"].async_stop()
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
