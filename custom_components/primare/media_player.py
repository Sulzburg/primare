"""Eine Media-Player-Entität pro Primare-Gerät, die alles bündelt."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PrimareConfigEntry
from .client import VOLUME_MAX
from .const import DSP_MAP, DSP_MAP_INV
from .entity import PrimareEntity
from .playback import async_create_playback


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    entities: list[MediaPlayerEntity] = [PrimareMediaPlayer(entry)]
    if playback := async_create_playback(hass, entry):
        entities.append(playback)
    async_add_entities(entities)


class PrimareMediaPlayer(PrimareEntity, MediaPlayerEntity):
    _attr_name = "Steuerung"
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(self, entry: PrimareConfigEntry) -> None:
        super().__init__(entry, "media_player")
        p = self._profile
        features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
        )
        if p.has_mute:
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        if p.has_input:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
            self._attr_source_list = list(p.inputs.values())
        if p.has_dsp:
            features |= MediaPlayerEntityFeature.SELECT_SOUND_MODE
            self._attr_sound_mode_list = list(DSP_MAP.values())
        self._attr_supported_features = features

    # ------------------------------------------------------------------ Zustand
    @property
    def state(self) -> MediaPlayerState | None:
        if self._client.power is None:
            return None
        return MediaPlayerState.ON if self._client.power else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        vol = self._client.volume
        return None if vol is None else vol / VOLUME_MAX

    @property
    def is_volume_muted(self) -> bool | None:
        return self._client.mute if self._profile.has_mute else None

    @property
    def source(self) -> str | None:
        if not self._profile.has_input or self._client.input is None:
            return None
        return self._profile.inputs.get(self._client.input)

    @property
    def sound_mode(self) -> str | None:
        if not self._profile.has_dsp or self._client.dsp is None:
            return None
        return DSP_MAP.get(self._client.dsp)

    # ------------------------------------------------------------------ Befehle
    async def async_turn_on(self) -> None:
        await self._send(self._client.set_power(True))

    async def async_turn_off(self) -> None:
        await self._send(self._client.set_power(False))

    async def async_set_volume_level(self, volume: float) -> None:
        await self._send(self._client.set_volume(volume * VOLUME_MAX))

    async def async_volume_up(self) -> None:
        await self._send(self._client.volume_up())

    async def async_volume_down(self) -> None:
        await self._send(self._client.volume_down())

    async def async_mute_volume(self, mute: bool) -> None:
        await self._send(self._client.set_mute(mute))

    async def async_select_source(self, source: str) -> None:
        number = self._profile.inputs_inv.get(source)
        if number is None:
            raise ServiceValidationError(f"Unbekannter Eingang: {source}")
        await self._send(self._client.set_input(number))

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        number = DSP_MAP_INV.get(sound_mode)
        if number is None:
            raise ServiceValidationError(f"Unbekannter DSP-Modus: {sound_mode}")
        await self._send(self._client.set_dsp(number))
