"""One media player per Primare device: amplifier (port 50006) and streamer (LUCI) together."""

from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import PrimareConfigEntry
from .client import VOLUME_MAX
from .const import DSP_MAP, DSP_MAP_INV
from .entity import PrimareEntity
from .luci import SOURCES, Playback
from .playback import STATES, StreamerPlayback, async_remove_old_playback_entity

# Play works in every state: the device switches to the streamer input (and wakes
# up) by itself as soon as playback starts, whatever starts it.
TRANSPORT = (
    MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.STOP
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.PREVIOUS_TRACK
)
POSITION_SLACK = 2


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PrimareConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_remove_old_playback_entity(hass, entry)
    streamer = StreamerPlayback(hass, entry)
    async_add_entities([PrimareMediaPlayer(entry, streamer)])
    streamer.async_start()


class PrimareMediaPlayer(PrimareEntity, MediaPlayerEntity):
    """Named like the device itself (main feature); entity ID stays *_steuerung."""

    _attr_name = None
    _attr_device_class = MediaPlayerDeviceClass.RECEIVER

    def __init__(self, entry: PrimareConfigEntry, streamer: StreamerPlayback) -> None:
        super().__init__(entry, "media_player")
        self._streamer = streamer
        self._was_streaming: bool | None = None
        self._track = None
        self._last_playback: Playback | None = None
        p = self._profile
        features = (
            MediaPlayerEntityFeature.TURN_ON
            | MediaPlayerEntityFeature.TURN_OFF
            | MediaPlayerEntityFeature.VOLUME_SET
            | MediaPlayerEntityFeature.VOLUME_STEP
            | TRANSPORT
        )
        if p.has_mute:
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        if p.has_input:
            features |= MediaPlayerEntityFeature.SELECT_SOURCE
            self._attr_source_list = list(p.inputs.values())
        if p.has_dsp:
            features |= MediaPlayerEntityFeature.SELECT_SOUND_MODE
            self._attr_sound_mode_list = list(DSP_MAP.values())
        self._base_features = features
        self._attr_supported_features = features

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._streamer.add_listener(self._handle_streamer_update))
        self._refresh()

    # ---------------------------------------------------------------- updates
    @callback
    def _handle_update(self) -> None:
        """Amplifier changed (port 50006)."""
        streaming = self._streaming
        if streaming and self._was_streaming is False:
            # Woke up or switched to the streamer: the old track is no longer valid
            self._streamer.async_invalidate()
        self._was_streaming = streaming
        self._refresh()
        self.async_write_ha_state()

    @callback
    def _handle_streamer_update(self) -> None:
        self._refresh()
        self.async_write_ha_state()

    @property
    def _streaming(self) -> bool:
        """Device on and on the streamer input (the NP5 always is)."""
        if not self._client.power:
            return False
        stream_input = self._profile.stream_input
        if not self._profile.has_input or stream_input is None:
            return True
        return self._client.input == stream_input

    @property
    def _playback(self) -> Playback | None:
        """Playback with a track (playing, paused, buffering) – only on the streamer input."""
        playback = self._streamer.playback if self._streaming else None
        if playback is None or STATES.get(playback.state) in (None, MediaPlayerState.IDLE):
            return None
        return playback

    @callback
    def _refresh(self) -> None:
        playback = self._playback
        # Another input (or the streamer idle): show the input name as title
        self._attr_media_title = playback.title if playback else (self.source if self._client.power else None)
        self._attr_media_artist = playback.artist if playback else None
        self._attr_media_album_name = playback.album if playback else None
        self._attr_media_image_url = playback.cover_art_url if playback else None
        self._attr_media_content_type = MediaType.MUSIC if playback and playback.title else None
        self._attr_media_duration = playback.duration if playback else None
        source_id = playback.source_id if playback else None
        if source_id is None and self._streaming and (data := self._streamer.playback):
            source_id = data.source_id
        self._attr_app_name = (playback.source_app if playback else None) or (
            SOURCES.get(source_id) if source_id is not None else None
        )
        self._attr_extra_state_attributes = (
            {
                key: value
                for key, value in {
                    "sample_rate_hz": playback.sample_rate_hz,
                    "bit_depth": playback.bit_depth,
                    "audio_format": playback.audio_format,
                    "bit_rate_bps": playback.bit_rate_bps,
                    "source_id": playback.source_id,
                }.items()
                if value is not None
            }
            if playback
            else {}
        )
        features = self._base_features
        if playback is not None:
            # Many devices (e.g. Pre35) do not report Next/Prev, yet the commands work –
            # only hide them when the device explicitly refuses.
            if playback.can_next is False:
                features &= ~MediaPlayerEntityFeature.NEXT_TRACK
            if playback.can_previous is False:
                features &= ~MediaPlayerEntityFeature.PREVIOUS_TRACK
            if playback.can_seek is True:
                features |= MediaPlayerEntityFeature.SEEK
        self._attr_supported_features = features
        # Amplifier updates leave the streamer data as it was; its position can be up
        # to one resync old (positions that follow the clock are not pushed), so only
        # new streamer data may move the position and its timestamp.
        if playback is not self._last_playback:
            self._last_playback = playback
            self._update_position(playback)

    def _update_position(self, playback: Playback | None) -> None:
        track = playback.track if playback else None
        position = playback.position if playback else None
        duration = playback.duration if playback else None
        if position is not None and duration and position > duration + POSITION_SLACK:
            # Device counts wrong (e.g. after switching Tidal↔Qobuz) – rather no position
            position = None
        playing = playback is not None and STATES.get(playback.state) == MediaPlayerState.PLAYING
        # While playing, even seeking back to the same number needs a new timestamp
        if track == self._track and not playing and (
            position == self._attr_media_position
            or (position is None and playback is not None and STATES.get(playback.state) == MediaPlayerState.PAUSED)
        ):
            return
        self._track = track
        self._attr_media_position = position
        self._attr_media_position_updated_at = dt_util.utcnow() if position is not None else None

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> MediaPlayerState | None:
        if self._client.power is None:
            return None
        if not self._client.power:
            return MediaPlayerState.OFF
        if self._streaming:
            if (playback := self._playback) is not None:
                return STATES[playback.state]
            if (data := self._streamer.playback) is not None and STATES.get(data.state) == MediaPlayerState.IDLE:
                return MediaPlayerState.IDLE
        return MediaPlayerState.ON

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

    # --------------------------------------------------------------- commands
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
            raise ServiceValidationError(f"Unknown input: {source}")
        await self._send(self._client.set_input(number))

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        number = DSP_MAP_INV.get(sound_mode)
        if number is None:
            raise ServiceValidationError(f"Unknown DSP mode: {sound_mode}")
        await self._send(self._client.set_dsp(number))

    async def async_media_play(self) -> None:
        await self._streamer.async_transport(
            "RESUME" if self.state == MediaPlayerState.PAUSED else "PLAY"
        )

    async def async_media_pause(self) -> None:
        await self._streamer.async_transport("PAUSE")

    async def async_media_stop(self) -> None:
        await self._streamer.async_transport("STOP")

    async def async_media_next_track(self) -> None:
        await self._streamer.async_transport("NEXT")

    async def async_media_previous_track(self) -> None:
        await self._streamer.async_transport("PREV")

    async def async_media_seek(self, position: float) -> None:
        await self._streamer.async_transport("SEEK", position)
