"""Expose the Primare's local playback state and stream metadata."""

from datetime import timedelta
import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerState,
    MediaType,
)
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import CONF_PLAYBACK_STATUS
from .luci import LuciPlaybackClient

_LOGGER = logging.getLogger(__name__)
_STATES = {
    0: MediaPlayerState.PLAYING,
    1: MediaPlayerState.IDLE,
    2: MediaPlayerState.PAUSED,
    5: MediaPlayerState.BUFFERING,
}


async def async_setup_entry(hass, entry, async_add_entities):
    if not entry.options.get(CONF_PLAYBACK_STATUS, False):
        return

    client = LuciPlaybackClient(entry.data["ip_address"])
    entry.async_on_unload(client.close)

    async def async_read_playback():
        try:
            return await client.async_read(), dt_util.utcnow()
        except (OSError, EOFError, ValueError) as err:
            raise UpdateFailed(f"Could not read Primare playback: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Primare playback",
        update_interval=timedelta(seconds=5),
        update_method=async_read_playback,
    )
    await coordinator.async_refresh()
    async_add_entities([PrimarePlayback(coordinator, entry)])


class PrimarePlayback(CoordinatorEntity, MediaPlayerEntity):
    """A read-only player, independent of the Spotify account or sender."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._attr_name = f'{entry.data["device_name"]} Playback'
        self._attr_unique_id = entry.entry_id

    @property
    def _playback(self):
        return self.coordinator.data[0] if self.available else None

    @property
    def state(self):
        return _STATES[self._playback.state] if self._playback else None

    @property
    def media_content_type(self):
        return MediaType.MUSIC if self._playback and self._playback.title else None

    @property
    def media_title(self):
        return self._playback.title if self._playback else None

    @property
    def media_artist(self):
        return self._playback.artist if self._playback else None

    @property
    def media_album_name(self):
        return self._playback.album if self._playback else None

    @property
    def media_image_url(self):
        return self._playback.cover_art_url if self._playback else None

    @property
    def app_name(self):
        return self._playback.source_app if self._playback else None

    @property
    def media_duration(self):
        return self._playback.duration if self._playback else None

    @property
    def media_position(self):
        return self._playback.position if self._playback else None

    @property
    def media_position_updated_at(self):
        if self.media_position is not None:
            return self.coordinator.data[1]
        return None

    @property
    def extra_state_attributes(self):
        if (playback := self._playback) is None:
            return {}
        return {
            key: value
            for key, value in {
                "sample_rate_hz": playback.sample_rate_hz,
                "bit_depth": playback.bit_depth,
                "audio_format": playback.audio_format,
                "bit_rate_bps": playback.bit_rate_bps,
            }.items()
            if value is not None
        }
