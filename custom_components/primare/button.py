"""Lauter/Leiser-Knöpfe (bleiben für bestehende Dashboards erhalten)."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PrimareConfigEntry
from .entity import PrimareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([PrimareVolumeUp(entry), PrimareVolumeDown(entry)])


class PrimareVolumeUp(PrimareEntity, ButtonEntity):
    _attr_name = "Vol Up"
    _attr_icon = "mdi:volume-plus"

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "volume_up")

    async def async_press(self) -> None:
        await self._send(self._client.volume_up())


class PrimareVolumeDown(PrimareEntity, ButtonEntity):
    _attr_name = "Vol Down"
    _attr_icon = "mdi:volume-minus"

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "volume_down")

    async def async_press(self) -> None:
        await self._send(self._client.volume_down())
