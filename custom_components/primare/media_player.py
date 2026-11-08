"""Expose the Primare's local playback state and stream metadata."""

from datetime import timedelta
import logging

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from .const import CONF_PLAYBACK_STATUS, DOMAIN
from .luci import (
    POSITION_TOLERANCE,
    STALE_RECONNECT_DELAY,
    LuciPlaybackClient,
    LuciSessionStale,
    Playback,
)

_LOGGER = logging.getLogger(__name__)
RESYNC_INTERVAL = timedelta(seconds=60)
RECONNECT_DELAY = 5
_STATES = {
    0: MediaPlayerState.PLAYING,
    1: MediaPlayerState.IDLE,
    2: MediaPlayerState.PAUSED,
    3: MediaPlayerState.BUFFERING,
    4: MediaPlayerState.BUFFERING,
    5: MediaPlayerState.BUFFERING,
}


async def async_setup_entry(hass, entry, async_add_entities):
    if not entry.options.get(CONF_PLAYBACK_STATUS, False):
        registry = er.async_get(hass)
        if entity_id := registry.async_get_entity_id("media_player", DOMAIN, entry.entry_id):
            registry.async_remove(entity_id)
        return

    client = LuciPlaybackClient(entry.data["ip_address"])
    entry.async_on_unload(client.async_shutdown)

    async def async_read_playback():
        try:
            return await client.async_read()
        except LuciSessionStale:
            # A refresh queued before the watchdog fired keeps the last snapshot.
            return coordinator.data
        except (OSError, EOFError, ValueError) as err:
            raise UpdateFailed(f"Could not read Primare playback: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name="Primare playback",
        update_method=async_read_playback,
    )

    async def async_stop(_event):
        await coordinator.async_shutdown()
        await client.async_shutdown()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop))
    controls = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([PrimarePlayback(coordinator, entry, client, controls)])


class PrimarePlayback(CoordinatorEntity, MediaPlayerEntity):
    """A local player, independent of the Spotify account or sender."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER

    def __init__(self, coordinator, entry, client, controls):
        super().__init__(coordinator)
        self._entry = entry
        self._initial_sync = None
        self._client = client
        self._controls = controls
        self._track = None
        self._cancel_refresh = None
        self._cancel_retry = None
        self._waiting_for_push_retry = False
        self._listening = False
        device_name = entry.data["device_name"].strip()
        self._playback_name = f"{device_name} Playback"
        self._attr_name = (
            self._playback_name
            if self._playback_name.casefold().startswith("primare ")
            else f"Primare {self._playback_name}"
        )
        self._attr_unique_id = entry.entry_id
        self._attr_supported_features = MediaPlayerEntityFeature(0)

    @property
    def suggested_object_id(self) -> str:
        # Keep the entity ID convention when adding the brand to the name.
        return self._playback_name

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self._listening = True
        self.async_on_remove(self._controls.async_add_listener(self._handle_power_update))
        self.async_on_remove(self._client.subscribe(self._handle_luci_event))
        # A fixed timer still runs when position notifications keep coming in.
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_resync, RESYNC_INTERVAL)
        )
        self._initial_sync = self._entry.async_create_background_task(
            self.hass, self._async_resync(), "primare_playback_initial_sync"
        )

    async def async_will_remove_from_hass(self):
        self._listening = False
        if self._cancel_refresh is not None:
            self._cancel_refresh()
            self._cancel_refresh = None
        self._clear_retry()
        if self._initial_sync is not None:
            # Entity removal precedes config-entry task cancellation.
            self._initial_sync.cancel()
            self._initial_sync = None
        await self._client.async_disconnect()
        await super().async_will_remove_from_hass()

    @callback
    def _handle_luci_event(self, update: Playback | Exception):
        if not self._listening or self.hass.is_stopping:
            return
        if isinstance(update, LuciSessionStale):
            # Rapid re-registration can leave a LUCI session without notifications.
            self._clear_retry()
            self._waiting_for_push_retry = True
            self._schedule_retry(STALE_RECONNECT_DELAY)
        elif isinstance(update, Exception):
            self.coordinator.async_set_update_error(UpdateFailed(str(update)))
            self._schedule_retry()
        else:
            self._clear_retry()
            self.coordinator.async_set_updated_data(update)

    @callback
    def _clear_retry(self):
        if self._cancel_retry is not None:
            self._cancel_retry()
            self._cancel_retry = None

    @callback
    def _schedule_retry(self, delay=RECONNECT_DELAY):
        if self._listening and self._cancel_retry is None and not self.hass.is_stopping:
            self._cancel_retry = async_call_later(
                self.hass, delay, self._async_retry
            )

    async def _async_retry(self, _now):
        self._cancel_retry = None
        self._waiting_for_push_retry = False
        await self._async_resync()

    async def _async_resync(self, _now=None):
        if not self._listening or self._waiting_for_push_retry or self.hass.is_stopping:
            return
        await self.coordinator.async_refresh()
        if self._waiting_for_push_retry:
            return
        if self.coordinator.last_update_success:
            self._clear_retry()
        else:
            self._schedule_retry()

    async def async_update(self):
        await self._async_resync()

    @callback
    def _handle_power_update(self):
        # The NP5 exposes standby on port 50006, but did not answer the input
        # query. Do not guess which physical source a LUCI session represents.
        if self._controls.data.get("power") == 0:
            if self._attr_state != MediaPlayerState.OFF:
                self._handle_coordinator_update()
        elif self._attr_state == MediaPlayerState.OFF:
            # Wait for the next LUCI read rather than restoring a cached track.
            self._attr_state = None
            self.async_write_ha_state()
            self._schedule_resync()

    @callback
    def _handle_coordinator_update(self):
        self._apply_snapshot()
        super()._handle_coordinator_update()

    @callback
    def _apply_snapshot(self):
        now = dt_util.utcnow()
        previous_state = self._attr_state
        power_off = self._controls.data.get("power") == 0
        playback = self.coordinator.data if self.coordinator.last_update_success else None
        self._attr_state = MediaPlayerState.OFF if power_off else (
            _STATES.get(playback.state) if playback is not None else None
        )
        if self._attr_state in (None, MediaPlayerState.IDLE, MediaPlayerState.OFF):
            playback = None

        self._attr_media_title = playback.title if playback else None
        self._attr_media_artist = playback.artist if playback else None
        self._attr_media_album_name = playback.album if playback else None
        self._attr_media_image_url = playback.cover_art_url if playback else None
        self._attr_media_content_type = MediaType.MUSIC if self._attr_media_title else None
        self._attr_media_duration = playback.duration if playback else None
        self._attr_app_name = playback.source_app if playback else None
        self._attr_extra_state_attributes = (
            {
                key: value
                for key, value in {
                    "sample_rate_hz": playback.sample_rate_hz,
                    "bit_depth": playback.bit_depth,
                    "audio_format": playback.audio_format,
                    "bit_rate_bps": playback.bit_rate_bps,
                }.items()
                if value is not None
            }
            if playback else {}
        )
        self._attr_supported_features = self._features(playback)
        self._update_position(playback, previous_state, now)

    def _update_position(self, playback, previous_state, now):
        track = (
            (playback.title, playback.artist, playback.album, playback.duration)
            if playback else None
        )
        position = playback.position if playback else None
        unchanged_track_and_state = track == self._track and self._attr_state == previous_state
        if unchanged_track_and_state:
            if position is None and self._attr_state == MediaPlayerState.PAUSED:
                # A paused streamer need not push a position on every poll.
                return
            if position is not None and self._attr_media_position is not None:
                expected = self._attr_media_position
                if self._attr_state == MediaPlayerState.PLAYING:
                    expected += (now - self._attr_media_position_updated_at).total_seconds()
                    if abs(position - expected) <= POSITION_TOLERANCE:
                        return
                elif position == expected:
                    return
        self._track = track
        self._attr_media_position = position
        self._attr_media_position_updated_at = now if position is not None else None

    @staticmethod
    def _features(playback):
        if playback is None or playback.state not in (0, 2):
            return MediaPlayerEntityFeature(0)
        features = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
        )
        if playback.can_next:
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if playback.can_previous:
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        if playback.can_seek:
            features |= MediaPlayerEntityFeature.SEEK
        return features

    @property
    def available(self):
        return self._controls.data.get("power") == 0 or super().available

    async def _async_transport(self, command, position=None):
        if self._waiting_for_push_retry:
            raise HomeAssistantError("Primare playback is reconnecting")
        try:
            await self._client.async_transport(command, position)
        except LuciSessionStale as err:
            raise HomeAssistantError("Primare playback is reconnecting") from err
        except (OSError, EOFError, ValueError) as err:
            if not self._client.connected:
                self._handle_luci_event(err)
            raise HomeAssistantError(f"Could not control Primare playback: {err}") from err
        self._schedule_resync()

    @callback
    def _schedule_resync(self):
        if self._cancel_refresh is not None:
            self._cancel_refresh()
        self._cancel_refresh = async_call_later(self.hass, 1, self._async_delayed_refresh)

    async def _async_delayed_refresh(self, _now):
        self._cancel_refresh = None
        await self._async_resync()

    async def async_media_play(self):
        await self._async_transport(
            "RESUME" if self.state == MediaPlayerState.PAUSED else "PLAY"
        )

    async def async_media_pause(self):
        await self._async_transport("PAUSE")

    async def async_media_stop(self):
        await self._async_transport("STOP")

    async def async_media_next_track(self):
        await self._async_transport("NEXT")

    async def async_media_previous_track(self):
        await self._async_transport("PREV")

    async def async_media_seek(self, position):
        await self._async_transport("SEEK", position)
