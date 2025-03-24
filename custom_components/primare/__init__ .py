from .coordinator import PrimareDataCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

PLATFORMS = ["switch", "number", "select", "media_player"]

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    ip_address = config_entry.data["ip_address"]
    device_name = config_entry.data["device_name"]
    coordinator = PrimareDataCoordinator(ip_address, device_name, hass.loop)
    await coordinator.async_start()
    hass.data.setdefault("primare", {})["coordinator"] = coordinator

    # Leite alle in PLATFORMS definierten Plattformen weiter
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)
    return True
