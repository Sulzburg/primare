"""What the built-in Prisma streamer is playing (LUCI, port 7777).

The playback logic comes from pull request #3 by yvos (https://github.com/yvos).
Since 3.0 it no longer is an entity of its own ("Wiedergabe"): the media player
of the device ("Steuerung") reads it from here.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
import logging

from homeassistant.components.media_player import MediaPlayerState
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import PrimareConfigEntry
from .const import CONF_HOST, DOMAIN
from .luci import LuciPlaybackClient, Playback

_LOGGER = logging.getLogger(__name__)
RESYNC_INTERVAL = timedelta(seconds=60)
RECONNECT_DELAY = 5
TITLE_RETRY = 3  # no title while playing: read it again
STATES = {
    0: MediaPlayerState.PLAYING,
    1: MediaPlayerState.IDLE,
    2: MediaPlayerState.PAUSED,
    3: MediaPlayerState.BUFFERING,
    4: MediaPlayerState.BUFFERING,
    5: MediaPlayerState.BUFFERING,
}


def async_remove_old_playback_entity(hass: HomeAssistant, entry: PrimareConfigEntry) -> None:
    """Up to 2.x the streamer had its own entity "Wiedergabe" – remove it."""
    registry = er.async_get(hass)
    if entity_id := registry.async_get_entity_id("media_player", DOMAIN, f"{entry.entry_id}_playback"):
        registry.async_remove(entity_id)


class StreamerPlayback:
    """Keeps the streamer's playback current and tells the media player."""

    def __init__(self, hass: HomeAssistant, entry: PrimareConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._luci = LuciPlaybackClient(entry.data[CONF_HOST])
        self._coordinator = DataUpdateCoordinator(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"Primare {entry.title} streamer",
            update_method=self._async_read,
        )
        self._listeners: list[Callable[[], None]] = []
        self._cancel_sync: Callable[[], None] | None = None
        self._initial_sync = None
        self._running = False
        self._stale = False

    # ---------------------------------------------------------------- lifecycle
    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_start(self) -> None:
        self._running = True
        entry = self._entry
        entry.async_on_unload(self._coordinator.async_add_listener(self._notify))
        entry.async_on_unload(self._luci.subscribe(self._handle_luci_event))
        # Fixed rhythm, even while position pushes keep coming
        entry.async_on_unload(
            async_track_time_interval(self._hass, self._async_resync, RESYNC_INTERVAL)
        )
        entry.async_on_unload(
            self._hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, self._async_stop_event)
        )
        entry.async_on_unload(self.async_stop)
        self._initial_sync = entry.async_create_background_task(
            self._hass, self._async_resync(), "primare_playback_initial_sync"
        )
        entry.async_create_background_task(
            self._hass, self._async_read_device_info(), "primare_device_info"
        )

    async def _async_stop_event(self, _event) -> None:
        await self.async_stop()

    async def async_stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._cancel_scheduled_sync()
        if self._initial_sync is not None:
            self._initial_sync.cancel()
            self._initial_sync = None
        await self._coordinator.async_shutdown()
        await self._luci.async_shutdown()

    # ------------------------------------------------------------------ state
    @property
    def playback(self) -> Playback | None:
        """Latest playback, or None while unknown (no answer yet, error, just woke up)."""
        if self._stale or not self._coordinator.last_update_success:
            return None
        return self._coordinator.data

    @callback
    def async_invalidate(self) -> None:
        """Device woke up or changed input: forget the old track, ask again shortly."""
        self._stale = True
        self._notify()
        self._schedule_sync(1)

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    # ------------------------------------------------------------------ reading
    async def _async_read(self) -> Playback:
        try:
            playback = await self._luci.async_read()
        except (OSError, EOFError, ValueError) as err:
            raise UpdateFailed(f"Streamer not readable: {err}") from err
        self._stale = False
        return playback

    @callback
    def _handle_luci_event(self, update: Playback | Exception) -> None:
        if not self._running or self._hass.is_stopping:
            return
        if isinstance(update, Exception):
            self._coordinator.async_set_update_error(UpdateFailed(str(update)))
            self._schedule_sync(RECONNECT_DELAY)
        else:
            self._cancel_scheduled_sync()
            self._stale = False
            self._coordinator.async_set_updated_data(update)
            if update.state in (0, 2) and update.title is None:
                # Title dropped on a source change, or not sent yet: ask for it shortly.
                self._schedule_sync(TITLE_RETRY)

    @callback
    def _cancel_scheduled_sync(self) -> None:
        if self._cancel_sync is not None:
            self._cancel_sync()
            self._cancel_sync = None

    @callback
    def _schedule_sync(self, delay: float) -> None:
        if not self._running or self._hass.is_stopping:
            return
        self._cancel_scheduled_sync()
        self._cancel_sync = async_call_later(self._hass, delay, self._async_scheduled_sync)

    async def _async_scheduled_sync(self, _now) -> None:
        self._cancel_sync = None
        await self._async_resync()

    async def _async_resync(self, _now=None) -> None:
        if not self._running or self._hass.is_stopping:
            return
        await self._coordinator.async_refresh()
        if not self._coordinator.last_update_success:
            self._schedule_sync(RECONNECT_DELAY)

    async def _async_read_device_info(self) -> None:
        """Main, streaming and Cast firmware once onto the device page (as the Prisma app shows them)."""
        if self._initial_sync is not None:
            with suppress(Exception):
                await self._initial_sync
        try:
            info = await self._luci.async_read_device_info()
        except (OSError, EOFError, ValueError) as err:
            _LOGGER.debug("%s: device info not read: %s", self._entry.title, err)
            return
        _LOGGER.debug("%s: device info %s", self._entry.title, info)
        registry = dr.async_get(self._hass)
        for device in dr.async_entries_for_config_entry(registry, self._entry.entry_id):
            if (DOMAIN, self._entry.entry_id) not in device.identifiers:
                continue
            version = format_firmware(info.get("host_firmware"), info.get("firmware"), info.get("cast"))
            if version and device.sw_version != version:
                registry.async_update_device(device.id, sw_version=version)

    # ---------------------------------------------------------------- commands
    async def async_transport(self, command: str, position: float | None = None) -> None:
        try:
            await self._luci.async_transport(command, position)
        except (OSError, EOFError, ValueError) as err:
            if not self._luci.connected:
                self._handle_luci_event(err)
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="streamer_not_controllable",
                translation_placeholders={"error": str(err)},
            ) from err
        self._schedule_sync(1)


def format_firmware(main: object, streaming: object, cast: object = None) -> str | None:
    """'315', '15644', '1.52.272222' -> '3.15 (Streaming 15644 · Cast 1.52)'."""
    main = str(main) if main else ""
    if main.isdigit() and len(main) >= 3:
        main = f"{int(main[:-2])}.{main[-2:]}"
    details = []
    if streaming:
        details.append(f"Streaming {streaming}")
    if cast:
        details.append("Cast " + ".".join(str(cast).split(".")[:2]))
    if main and details:
        return f"{main} ({' · '.join(details)})"
    return main or (" · ".join(details) or None)
