"""Wiedergabe des eingebauten Prisma-Streamers (LUCI, Port 7777).

Die Logik stammt aus Pull Request #3 von yvos (https://github.com/yvos) und
wurde nur an die Struktur von Version 2 angepasst:
- Gerät, Name und unique_id wie die übrigen Entitäten (Name "Wiedergabe"),
- Standby kommt aus dem PrimareClient (Port 50006) statt aus dem alten Coordinator.
"""

from __future__ import annotations

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
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util import dt as dt_util

from . import PrimareConfigEntry
from .client import PrimareClient
from .const import CONF_HOST, CONF_PLAYBACK, DOMAIN
from .luci import LuciPlaybackClient, Playback

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


def playback_unique_id(entry: PrimareConfigEntry) -> str:
    return f"{entry.entry_id}_playback"


def async_create_playback(
    hass: HomeAssistant, entry: PrimareConfigEntry
) -> PrimarePlayback | None:
    """Wiedergabe-Entität bauen, wenn sie in den Optionen eingeschaltet ist.

    Ist sie ausgeschaltet, wird ein alter Registereintrag entfernt.
    """
    if not entry.options.get(CONF_PLAYBACK, False):
        registry = er.async_get(hass)
        if entity_id := registry.async_get_entity_id(
            "media_player", DOMAIN, playback_unique_id(entry)
        ):
            registry.async_remove(entity_id)
        return None

    luci = LuciPlaybackClient(entry.data[CONF_HOST])
    entry.async_on_unload(luci.async_shutdown)

    async def async_read_playback() -> Playback:
        try:
            return await luci.async_read()
        except (OSError, EOFError, ValueError) as err:
            raise UpdateFailed(f"Wiedergabe nicht lesbar: {err}") from err

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name=f"Primare {entry.title} Wiedergabe",
        update_method=async_read_playback,
    )

    async def async_stop(_event) -> None:
        await coordinator.async_shutdown()
        await luci.async_shutdown()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, async_stop))
    return PrimarePlayback(coordinator, entry, luci)


class PrimarePlayback(CoordinatorEntity, MediaPlayerEntity):
    """Was der Streamer gerade spielt – unabhängig von Spotify-Konto oder Sender."""

    _attr_has_entity_name = True
    _attr_name = "Wiedergabe"
    _attr_device_class = MediaPlayerDeviceClass.SPEAKER

    def __init__(
        self,
        coordinator: DataUpdateCoordinator,
        entry: PrimareConfigEntry,
        luci: LuciPlaybackClient,
    ) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._luci = luci
        self._controls: PrimareClient = entry.runtime_data.client
        self._initial_sync = None
        self._track = None
        self._cancel_sync = None
        self._listening = False
        self._attr_unique_id = playback_unique_id(entry)
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._attr_supported_features = MediaPlayerEntityFeature(0)

    # -------------------------------------------------------------- Lebenszyklus
    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._listening = True
        self.async_on_remove(self._controls.add_listener(self._handle_power_update))
        self.async_on_remove(self._luci.subscribe(self._handle_luci_event))
        # Fester Takt, auch wenn laufend Positionsmeldungen kommen
        self.async_on_remove(
            async_track_time_interval(self.hass, self._async_resync, RESYNC_INTERVAL)
        )
        self._initial_sync = self._entry.async_create_background_task(
            self.hass, self._async_resync(), "primare_playback_initial_sync"
        )

    async def async_will_remove_from_hass(self) -> None:
        self._listening = False
        self._cancel_scheduled_sync()
        if self._initial_sync is not None:
            self._initial_sync.cancel()
            self._initial_sync = None
        await self._luci.async_disconnect()
        await super().async_will_remove_from_hass()

    # ------------------------------------------------------------- Aktualisierung
    def _power_off(self) -> bool:
        return self._controls.power is False

    @callback
    def _handle_luci_event(self, update: Playback | Exception) -> None:
        if not self._listening or self.hass.is_stopping:
            return
        if isinstance(update, Exception):
            self.coordinator.async_set_update_error(UpdateFailed(str(update)))
            self._schedule_sync(RECONNECT_DELAY)
        else:
            self._cancel_scheduled_sync()
            self.coordinator.async_set_updated_data(update)

    @callback
    def _cancel_scheduled_sync(self) -> None:
        if self._cancel_sync is not None:
            self._cancel_sync()
            self._cancel_sync = None

    @callback
    def _schedule_sync(self, delay: float) -> None:
        if not self._listening or self.hass.is_stopping:
            return
        self._cancel_scheduled_sync()
        self._cancel_sync = async_call_later(self.hass, delay, self._async_scheduled_sync)

    async def _async_scheduled_sync(self, _now) -> None:
        self._cancel_sync = None
        await self._async_resync()

    async def _async_resync(self, _now=None) -> None:
        if not self._listening or self.hass.is_stopping:
            return
        await self.coordinator.async_refresh()
        if not self.coordinator.last_update_success:
            self._schedule_sync(RECONNECT_DELAY)

    async def async_update(self) -> None:
        await self._async_resync()

    @callback
    def _handle_power_update(self) -> None:
        # Standby kommt über Port 50006. Welcher Eingang zur LUCI-Sitzung gehört,
        # wird bewusst nicht geraten.
        if self._power_off():
            if self._attr_state != MediaPlayerState.OFF:
                self._handle_coordinator_update()
        elif self._attr_state == MediaPlayerState.OFF:
            # Auf die nächste LUCI-Abfrage warten statt alten Titel wiederherzustellen
            self._attr_state = None
            self.async_write_ha_state()
            self._schedule_sync(1)

    @callback
    def _handle_coordinator_update(self) -> None:
        self._apply_snapshot()
        super()._handle_coordinator_update()

    @callback
    def _apply_snapshot(self) -> None:
        now = dt_util.utcnow()
        playback = self.coordinator.data if self.coordinator.last_update_success else None
        self._attr_state = (
            MediaPlayerState.OFF
            if self._power_off()
            else (_STATES.get(playback.state) if playback is not None else None)
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
            if playback
            else {}
        )
        self._attr_supported_features = self._features(playback)
        self._update_position(playback, now)

    def _update_position(self, playback: Playback | None, now) -> None:
        track = playback.track if playback else None
        position = playback.position if playback else None
        duration = playback.duration if playback else None
        if position is not None and duration and position > duration + 2:
            # Gerät zählt falsch (z. B. nach Tidal↔Qobuz-Wechsel) – lieber keine Position
            position = None
        # Beim Spielen braucht auch ein Zurückspulen auf dieselbe Zahl einen neuen Zeitstempel
        if track == self._track and self._attr_state != MediaPlayerState.PLAYING and (
            position == self._attr_media_position
            or (position is None and self._attr_state == MediaPlayerState.PAUSED)
        ):
            return
        self._track = track
        self._attr_media_position = position
        self._attr_media_position_updated_at = now if position is not None else None

    @staticmethod
    def _features(playback: Playback | None) -> MediaPlayerEntityFeature:
        if playback is None or playback.state not in (0, 2):
            return MediaPlayerEntityFeature(0)
        features = (
            MediaPlayerEntityFeature.PLAY
            | MediaPlayerEntityFeature.PAUSE
            | MediaPlayerEntityFeature.STOP
        )
        # Many devices (e.g. Pre35) do not report Next/Prev at all, yet the
        # commands work – offer them unless the device explicitly refuses.
        if playback.can_next is not False:
            features |= MediaPlayerEntityFeature.NEXT_TRACK
        if playback.can_previous is not False:
            features |= MediaPlayerEntityFeature.PREVIOUS_TRACK
        if playback.can_seek is True:
            features |= MediaPlayerEntityFeature.SEEK
        return features

    @property
    def available(self) -> bool:
        return self._power_off() or super().available

    # ------------------------------------------------------------------ Befehle
    async def _async_transport(self, command: str, position: float | None = None) -> None:
        try:
            await self._luci.async_transport(command, position)
        except (OSError, EOFError, ValueError) as err:
            if not self._luci.connected:
                self._handle_luci_event(err)
            raise HomeAssistantError(f"Wiedergabe nicht steuerbar: {err}") from err
        self._schedule_sync(1)

    async def async_media_play(self) -> None:
        await self._async_transport(
            "RESUME" if self.state == MediaPlayerState.PAUSED else "PLAY"
        )

    async def async_media_pause(self) -> None:
        await self._async_transport("PAUSE")

    async def async_media_stop(self) -> None:
        await self._async_transport("STOP")

    async def async_media_next_track(self) -> None:
        await self._async_transport("NEXT")

    async def async_media_previous_track(self) -> None:
        await self._async_transport("PREV")

    async def async_media_seek(self, position: float) -> None:
        await self._async_transport("SEEK", position)
