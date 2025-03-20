import logging
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import INPUT_MAP, INPUT_MAP_INV, DSP_MAP, DSP_MAP_INV

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator = hass.data["primare"]["coordinator"]
    async_add_entities([
        PrimareInputSelect(coordinator, config_entry.data["device_name"]),
        PrimareDSPSelect(coordinator, config_entry.data["device_name"]),
    ])

class PrimareInputSelect(SelectEntity):
    def __init__(self, coordinator, device_name: str):
        self._coordinator = coordinator
        self._device_name = device_name
        self._unique_id = f"primare_{device_name.lower().replace(' ', '_')}_input_select"
        self._attr_name = f"{device_name} Input"
        self._attr_options = list(INPUT_MAP.values())
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Registriert den Listener, damit die Entität bei Statusänderungen aktualisiert wird."""
        self._remove_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entfernt den Listener beim Entfernen der Entität."""
        if self._remove_listener:
            self._remove_listener()

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def current_option(self):
        return self._coordinator.data.get("input")
        
    @property
    def icon(self) -> str:
        # Verwende ein Standard-MDI-Icon:
        return "mdi:audio-input-rca"
        # Alternativ, wenn du ein eigenes Icon liefern möchtest:
        # Stelle sicher, dass du dein Icon z.B. in /config/www/primare/my_volume_icon.png abgelegt hast
        # return "/local/primare/my_volume_icon.png"        

    async def async_select_option(self, option: str) -> None:
        num = INPUT_MAP_INV.get(option)
        if num is not None:
            command = f"!1inp.{num}"
            await self._coordinator.async_send_command(command)

class PrimareDSPSelect(SelectEntity):
    def __init__(self, coordinator, device_name: str):
        self._coordinator = coordinator
        self._device_name = device_name
        self._unique_id = f"primare_{device_name.lower().replace(' ', '_')}_dsp_select"
        self._attr_name = f"{device_name} DSP Mode"
        self._attr_options = list(DSP_MAP.values())
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Registriert den Listener, damit die Entität bei Statusänderungen aktualisiert wird."""
        self._remove_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entfernt den Listener beim Entfernen der Entität."""
        if self._remove_listener:
            self._remove_listener()

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def current_option(self):
        return self._coordinator.data.get("dsp")
        
    @property
    def icon(self) -> str:
        # Verwende ein Standard-MDI-Icon:
        return "mdi:surround-sound"
        # Alternativ, wenn du ein eigenes Icon liefern möchtest:
        # Stelle sicher, dass du dein Icon z.B. in /config/www/primare/my_volume_icon.png abgelegt hast
        # return "/local/primare/my_volume_icon.png"        

    async def async_select_option(self, option: str) -> None:
        num = DSP_MAP_INV.get(option)
        if num is not None:
            command = f"!1sur.{num}"
            await self._coordinator.async_send_command(command)
