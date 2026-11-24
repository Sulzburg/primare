"""Eingangs- und DSP-Auswahl (bleiben für bestehende Automationen erhalten)."""

from __future__ import annotations

from typing import ClassVar

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PrimareConfigEntry
from .const import DOMAIN, DSP_MAP, DSP_MAP_INV
from .entity import PrimareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    profile = entry.runtime_data.profile
    entities: list[SelectEntity] = []
    if profile.has_input:
        entities.append(PrimareInputSelect(entry))
    if profile.has_dsp:
        entities.append(PrimareDspSelect(entry))
    async_add_entities(entities)


class PrimareInputSelect(PrimareEntity, SelectEntity):
    _attr_translation_key = "input"
    _attr_icon = "mdi:audio-input-rca"

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "input_select")
        self._attr_options = list(self._profile.inputs.values())

    @property
    def current_option(self) -> str | None:
        if self._client.input is None:
            return None
        return self._profile.inputs.get(self._client.input)

    async def async_select_option(self, option: str) -> None:
        number = self._profile.inputs_inv.get(option)
        if number is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_input",
                translation_placeholders={"option": option},
            )
        await self._send(self._client.set_input(number))


class PrimareDspSelect(PrimareEntity, SelectEntity):
    _attr_translation_key = "dsp_mode"
    _attr_icon = "mdi:surround-sound"
    _attr_options: ClassVar[list[str]] = list(DSP_MAP.values())

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "dsp_select")

    @property
    def current_option(self) -> str | None:
        if self._client.dsp is None:
            return None
        return DSP_MAP.get(self._client.dsp)

    async def async_select_option(self, option: str) -> None:
        number = DSP_MAP_INV.get(option)
        if number is None:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="unknown_dsp_mode",
                translation_placeholders={"option": option},
            )
        await self._send(self._client.set_dsp(number))
