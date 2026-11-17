"""Status-Sensoren (doppeln Regler/Auswahl; nur für bestehende Automationen,
Dashboards und den Verlauf erhalten – können später entfallen)."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PrimareConfigEntry
from .const import DSP_MAP
from .entity import PrimareEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    profile = entry.runtime_data.profile
    entities: list[SensorEntity] = [PrimareVolumeSensor(entry)]
    if profile.has_input:
        entities.append(PrimareInputSensor(entry))
    if profile.has_dsp:
        entities.append(PrimareDspSensor(entry))
    async_add_entities(entities)


class PrimareVolumeSensor(PrimareEntity, SensorEntity):
    _attr_translation_key = "volume_status"
    _attr_icon = "mdi:volume-high"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "volume_sensor")

    @property
    def native_value(self) -> int | None:
        return self._client.volume


class PrimareInputSensor(PrimareEntity, SensorEntity):
    _attr_translation_key = "input_status"
    _attr_icon = "mdi:audio-input-rca"
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "input_sensor")
        self._attr_options = list(self._profile.inputs.values())

    @property
    def native_value(self) -> str | None:
        if self._client.input is None:
            return None
        return self._profile.inputs.get(self._client.input)


class PrimareDspSensor(PrimareEntity, SensorEntity):
    _attr_translation_key = "dsp_mode_status"
    _attr_icon = "mdi:surround-sound"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(DSP_MAP.values())

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "dsp_sensor")

    @property
    def native_value(self) -> str | None:
        if self._client.dsp is None:
            return None
        return DSP_MAP.get(self._client.dsp)
