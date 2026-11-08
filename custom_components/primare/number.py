"""Volume control for Primare devices."""

from homeassistant.components.number import NumberEntity, NumberMode

from .const import DOMAIN
from .entity import PrimareControlEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([PrimareVolumeControl(hass, entry, coordinator)])


class PrimareVolumeControl(PrimareControlEntity, NumberEntity):
    _attr_native_min_value = 0
    _attr_native_max_value = 99
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:volume-high"

    def __init__(self, hass, entry, coordinator):
        super().__init__(hass, entry, coordinator, "number", "volume", "volume_control", "Volume")

    @property
    def native_value(self):
        return self._coordinator.data["volume"]

    async def async_set_native_value(self, value):
        await self._coordinator.async_set("vol", int(value))
