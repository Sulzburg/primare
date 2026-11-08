"""Input and DSP selectors for Primare devices."""

from homeassistant.components.select import SelectEntity

from .const import DOMAIN, DSP_MAP
from .entity import PrimareControlEntity


async def async_setup_entry(hass, entry, async_add_entities):
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    entities = [
        PrimareSelect(
            hass, entry, coordinator, "input", "inp", "Input", "mdi:audio-input-rca", data["input_map"]
        )
    ]
    if data["device_type"] == "Multichannel":
        entities.append(
            PrimareSelect(hass, entry, coordinator, "dsp", "sur", "DSP Mode", "mdi:surround-sound", DSP_MAP)
        )
    async_add_entities(entities)


class PrimareSelect(PrimareControlEntity, SelectEntity):
    def __init__(self, hass, entry, coordinator, field, command, label, icon, options):
        super().__init__(hass, entry, coordinator, "select", field, f"{field}_select", label)
        self._command = command
        self._attr_icon = icon
        self._attr_options = list(options.values())
        self._codes = {label: code for code, label in options.items()}

    @property
    def current_option(self):
        return self._coordinator.data[self._field]

    async def async_select_option(self, option):
        await self._coordinator.async_set(self._command, self._codes[option])
