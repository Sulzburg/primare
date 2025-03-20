import logging
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    coordinator = hass.data["primare"]["coordinator"]
    async_add_entities([
        PrimareMuteSwitch(coordinator, config_entry.data["device_name"]),
        PrimarePowerSwitch(coordinator, config_entry.data["device_name"]),
    ])

class PrimareMuteSwitch(SwitchEntity):
    def __init__(self, coordinator, device_name: str):
        self._coordinator = coordinator
        self._device_name = device_name
        self._unique_id = f"primare_{device_name.lower().replace(' ', '_')}_mute_switch"
        self._attr_name = f"{device_name} Mute"
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Registriere den Listener, damit der Schalter bei Statusänderungen aktualisiert wird."""
        self._remove_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entferne den Listener, wenn die Entität aus Home Assistant entfernt wird."""
        if self._remove_listener:
            self._remove_listener()

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def is_on(self):
        return self._coordinator.data.get("mute") == 1
        
    @property
    def icon(self) -> str:
        # Verwende ein Standard-MDI-Icon:
        return "mdi:volume-off"
        # Alternativ, wenn du ein eigenes Icon liefern möchtest:
        # Stelle sicher, dass du dein Icon z.B. in /config/www/primare/my_volume_icon.png abgelegt hast
        # return "/local/primare/my_volume_icon.png"        

    async def async_turn_on(self, **kwargs):
        await self._coordinator.async_send_command("!1mut.1")

    async def async_turn_off(self, **kwargs):
        await self._coordinator.async_send_command("!1mut.0")


class PrimarePowerSwitch(SwitchEntity):
    def __init__(self, coordinator, device_name: str):
        self._coordinator = coordinator
        self._device_name = device_name
        self._unique_id = f"primare_{device_name.lower().replace(' ', '_')}_power_switch"
        self._attr_name = f"{device_name} Power"
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Registriere den Listener, damit der Schalter bei Statusänderungen aktualisiert wird."""
        self._remove_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entferne den Listener, wenn die Entität aus Home Assistant entfernt wird."""
        if self._remove_listener:
            self._remove_listener()

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def is_on(self):
        return self._coordinator.data.get("power") == 1
        
    @property
    def icon(self) -> str:
        # Verwende ein Standard-MDI-Icon:
        return "mdi:power"
        # Alternativ, wenn du ein eigenes Icon liefern möchtest:
        # Stelle sicher, dass du dein Icon z.B. in /config/www/primare/my_volume_icon.png abgelegt hast
        # return "/local/primare/my_volume_icon.png"        

    async def async_turn_on(self, **kwargs):
        await self._coordinator.async_send_command("!1pow.1")

    async def async_turn_off(self, **kwargs):
        await self._coordinator.async_send_command("!1pow.0")
