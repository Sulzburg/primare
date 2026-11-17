"""Lautstärke-Regler 0–99 (bleibt für bestehende Automationen erhalten)."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PrimareConfigEntry
from .entity import PrimareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([PrimareVolume(entry)])


class PrimareVolume(PrimareEntity, NumberEntity):
    _attr_name = "Volume"
    _attr_icon = "mdi:volume-high"
    _attr_native_min_value = 0
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "volume")
        # Regler endet bei der eingestellten Obergrenze (Vorgabe 99)
        self._attr_native_max_value = self._client.max_volume

    @property
    def native_value(self) -> int | None:
        return self._client.volume

    async def async_set_native_value(self, value: float) -> None:
        await self._send(self._client.set_volume(value))
