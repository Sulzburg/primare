# custom_components/primare/__init__.py

from .coordinator import PrimareDataCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, INPUT_MAPS

PLATFORMS = ["switch", "number", "select"]  # media_player ggf. aktivieren

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Basis-Setup, nur erforderlich für die Registrierung der Integration."""
    return True

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    ip_address = config_entry.data["ip_address"]
    device_name = config_entry.data["device_name"]
    device_type = config_entry.data.get("device_type", "SP25")  # Default = SP25

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
    return True
