import asyncio
import logging

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_SELECT_SOURCE,
    SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
DEFAULT_PORT = 50006

# Hier nutzen wir wieder das gleiche Mapping für die Input-Quellen
INPUT_MAP = {
    1: "BD LG",
    2: "BD PAN",
    3: "FireTV",
    4: "HDMI ARC",
    5: "TV Opto",
    6: "Game Console",
    7: "SAT/Receiver",
    8: "PC/Mac",
    9: "Radio",
    10: "PC",
    11: "Spotify",
    12: "Tidal",
    13: "Deezer",
    14: "USB",
    15: "Kabel TV",
    16: "Test Input 1",
    17: "Prisma"
}


async def async_send_command(ip_address: str, command: str):
    """Öffnet eine separate TCP-Verbindung, sendet einen Befehl und schließt die Verbindung wieder."""
    try:
        reader, writer = await asyncio.open_connection(ip_address, DEFAULT_PORT)
        writer.write(command.encode() + b"\n")
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        _LOGGER.debug("Befehl '%s' an %s gesendet.", command, ip_address)
    except Exception as err:
        _LOGGER.error("Fehler beim Senden des Befehls '%s' an %s: %s", command, ip_address, err)


class PrimareMediaPlayer(MediaPlayerEntity):
    """Mediaplayer-Entität für den Primare SPA25.

    Diese Entität nutzt den gemeinsamen Coordinator (wie auch die Sensoren) für Status-Updates.
    """

    _attr_supported_features = (
        SUPPORT_VOLUME_SET | SUPPORT_VOLUME_MUTE | SUPPORT_SELECT_SOURCE | SUPPORT_TURN_ON | SUPPORT_TURN_OFF
    )

    def __init__(self, coordinator, device_name: str, ip_address: str):
        """Initialisiert den Mediaplayer."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._ip_address = ip_address
        self._attr_name = f"{device_name} Media Player"
        self._attr_unique_id = f"primare_{device_name.lower().replace(' ', '_')}_media_player"
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Registriert einen Listener, damit Status-Updates erfolgen."""
        self._remove_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entfernt den Listener beim Löschen der Entität."""
        if self._remove_listener:
            self._remove_listener()

    @property
    def state(self):
        # Wir nutzen den Wert des Power-Sensors: 1 = "on", 0 = "off"
        power = self._coordinator.data.get("power")
        return "on" if power == 1 else "off"

    @property
    def volume_level(self):
        # Wir gehen davon aus, dass das Volume als Wert zwischen 0 und 100 vorliegt
        vol = self._coordinator.data.get("volume")
        if vol is not None:
            return vol / 100.0  # Normalisierung auf 0...1
        return None

    @property
    def is_volume_muted(self):
        mute = self._coordinator.data.get("mute")
        if mute is not None:
            return bool(mute)
        return None

    @property
    def source(self):
        # Aktueller Eingang als Text (z. B. "FireTV")
        return self._coordinator.data.get("input")

    @property
    def source_list(self):
        # Liste aller möglichen Eingänge (basierend auf INPUT_MAP)
        return list(INPUT_MAP.values())

    async def async_turn_on(self):
        command = "!1pow.1"
        await async_send_command(self._ip_address, command)

    async def async_turn_off(self):
        command = "!1pow.0"
        await async_send_command(self._ip_address, command)

    async def async_set_volume_level(self, volume):
        # volume ist zwischen 0 und 1, wir skalieren auf 0 bis 100
        vol_value = int(volume * 100)
        command = f"!1vol.{vol_value}"
        await async_send_command(self._ip_address, command)

    async def async_mute_volume(self, mute):
        command = "!1mut.1" if mute else "!1mut.0"
        await async_send_command(self._ip_address, command)

    async def async_select_source(self, source):
        # Ermittle anhand des Source-Namens den numerischen Wert
        inv_map = {v: k for k, v in INPUT_MAP.items()}
        src_number = inv_map.get(source)
        if src_number is None:
            _LOGGER.error("Ungültige Quelle: %s", source)
            return
        command = f"!1inp.{src_number}"
        await async_send_command(self._ip_address, command)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    """Richtet die Mediaplayer-Entität ein."""
    device_name = config_entry.data["device_name"]
    ip_address = config_entry.data["ip_address"]
    coordinator = hass.data["primare"]["coordinator"]
    async_add_entities([PrimareMediaPlayer(coordinator, device_name, ip_address)])
