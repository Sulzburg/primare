"""Gemeinsame Basis aller Primare-Entitäten."""

from __future__ import annotations

from collections.abc import Awaitable

from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import PrimareConfigEntry
from .client import PrimareNotConnected
from .const import DOMAIN


class PrimareEntity(Entity):
    """Gerät, unique_id, Verfügbarkeit und Push-Updates an einer Stelle."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: PrimareConfigEntry, key: str) -> None:
        runtime = entry.runtime_data
        self._client = runtime.client
        self._profile = runtime.profile
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Primare",
            model=runtime.model or runtime.profile.model,
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._client.add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        return self._client.connected

    async def _send(self, coro: Awaitable[None]) -> None:
        """Befehl ausführen; fehlende Verbindung als verständlichen Fehler melden."""
        try:
            await coro
        except PrimareNotConnected as err:
            raise HomeAssistantError(str(err)) from err
