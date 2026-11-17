"""Power- und Mute-Schalter (bleiben für bestehende Automationen erhalten)."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PrimareConfigEntry
from .entity import PrimareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    entities: list[SwitchEntity] = [PrimarePowerSwitch(entry)]
    if entry.runtime_data.profile.has_mute:
        entities.append(PrimareMuteSwitch(entry))
    async_add_entities(entities)


class PrimarePowerSwitch(PrimareEntity, SwitchEntity):
    _attr_name = "Power"
    _attr_icon = "mdi:power"

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "power_switch")

    @property
    def is_on(self) -> bool | None:
        return self._client.power

    async def async_turn_on(self, **kwargs) -> None:
        await self._send(self._client.set_power(True))

    async def async_turn_off(self, **kwargs) -> None:
        await self._send(self._client.set_power(False))


class PrimareMuteSwitch(PrimareEntity, SwitchEntity):
    _attr_name = "Mute"
    _attr_icon = "mdi:volume-off"

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "mute_switch")

    @property
    def is_on(self) -> bool | None:
        return self._client.mute

    async def async_turn_on(self, **kwargs) -> None:
        await self._send(self._client.set_mute(True))

    async def async_turn_off(self, **kwargs) -> None:
        await self._send(self._client.set_mute(False))
