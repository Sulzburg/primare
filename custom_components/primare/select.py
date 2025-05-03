import logging
from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DSP_MAP, DSP_MAP_INV

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    entry_data = hass.data["primare"].get(config_entry.entry_id)
    if not entry_data:
        raise RuntimeError(f"Kein Eintrag für {config_entry.entry_id} gefunden")

    coordinator = entry_data["coordinator"]
    device_name = entry_data["device_name"]
    device_type = entry_data["device_type"]
    input_map = entry_data["input_map"]
    input_map_inv = entry_data["input_map_inv"]

    entities = [PrimareInputSelect(coordinator, device_name, input_map, input_map_inv)]

    if device_type == "Multichannel":
        entities.append(PrimareDSPSelect(coordinator, device_name))

    async_add_entities(entities)


class PrimareInputSelect(SelectEntity):
    def __init__(self, coordinator, device_name: str, input_map: dict, input_map_inv: dict):
        self._coordinator = coordinator
        self._device_name = device_name
        self._input_map = input_map
        self._input_map_inv = input_map_inv
        self._unique_id = f"primare_{device_name.lower().replace(' ', '_')}_input_select"
        self._attr_name = f"{device_name} Input"
        self._attr_options = list(input_map.values())
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
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
        return "mdi:audio-input-rca"

    async def async_select_option(self, option: str) -> None:
        num = self._input_map_inv.get(option)
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
        self._remove_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
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
        return "mdi:surround-sound"

    async def async_select_option(self, option: str) -> None:
        num = DSP_MAP_INV.get(option)
        if num is not None:
            command = f"!1sur.{num}"
            await self._coordinator.async_send_command(command)
