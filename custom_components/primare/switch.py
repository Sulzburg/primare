"""Power and mute switches for Primare devices."""

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .entity import PrimareControlEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        PrimareSwitch(hass, entry, coordinator, "mute", "mut", "Mute", "mdi:volume-off"),
        PrimareSwitch(hass, entry, coordinator, "power", "pow", "Power", "mdi:power"),
    ])


class PrimareSwitch(PrimareControlEntity, SwitchEntity):
    def __init__(self, hass, entry, coordinator, field, command, label, icon):
        super().__init__(hass, entry, coordinator, "switch", field, f"{field}_switch", label)
        self._command = command
        self._attr_icon = icon

    @property
    def is_on(self):
        value = self._coordinator.data[self._field]
        return None if value is None else value == 1

    async def async_turn_on(self, **kwargs):
        await self._coordinator.async_set(self._command, 1)

    async def async_turn_off(self, **kwargs):
        await self._coordinator.async_set(self._command, 0)
