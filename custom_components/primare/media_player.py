import logging
import socket
import voluptuous as vol

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    SUPPORT_TURN_ON,
    SUPPORT_TURN_OFF,
    SUPPORT_VOLUME_SET,
    SUPPORT_VOLUME_MUTE,
    SUPPORT_SELECT_SOURCE,
)
from homeassistant.const import CONF_HOST, CONF_PORT, STATE_OFF, STATE_ON
import homeassistant.helpers.config_validation as cv

_LOGGER = logging.getLogger(__name__)

DOMAIN = "primare"
DEFAULT_PORT = 50006

SUPPORT_PRIMARE = (
    SUPPORT_TURN_ON
    | SUPPORT_TURN_OFF
    | SUPPORT_VOLUME_SET
    | SUPPORT_VOLUME_MUTE
    | SUPPORT_SELECT_SOURCE
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_HOST): cv.string,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): cv.port,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

def setup_platform(hass, config, add_entities, discovery_info=None):
    host = config[DOMAIN][CONF_HOST]
    port = config[DOMAIN][CONF_PORT]
    add_entities([PrimareSPA25(host, port)])

class PrimareSPA25(MediaPlayerEntity):
    def __init__(self, host, port):
        self._host = host
        self._port = port
        self._state = STATE_OFF
        self._volume = 0
        self._mute = False
        self._source = None
        self._available_sources = {"HDMI1": "HDMI1", "HDMI2": "HDMI2", "Optical": "OPT"}
    
    def _send_command(self, command):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(2)
                s.connect((self._host, self._port))
                full_command = f"!1{command}\r\n"
                s.sendall(full_command.encode("utf-8"))
                response = s.recv(1024).decode("utf-8").strip()
                return response
        except Exception as e:
            _LOGGER.error("Error sending command to Primare SPA25: %s", e)
            return None
    
    def update(self):
        status = self._send_command("?PWR")
        if status == "!1PWR01":
            self._state = STATE_ON
        else:
            self._state = STATE_OFF
    
    def turn_on(self):
        self._send_command("PWR01")
        self._state = STATE_ON
    
    def turn_off(self):
        self._send_command("PWR00")
        self._state = STATE_OFF
    
    def set_volume_level(self, volume):
        volume_level = int(volume * 50)  # Annahme: Bereich 0-50
        self._send_command(f"VOL{volume_level:02d}")
    
    def mute_volume(self, mute):
        self._send_command("AMT01" if mute else "AMT00")
        self._mute = mute
    
    def select_source(self, source):
        if source in self._available_sources:
            self._send_command(f"INP{self._available_sources[source]}")
            self._source = source
    
    @property
    def name(self):
        return "Primare SPA25"
    
    @property
    def state(self):
        return self._state
    
    @property
    def volume_level(self):
        return self._volume / 50.0  # Annahme: Bereich 0-50
    
    @property
    def is_volume_muted(self):
        return self._mute
    
    @property
    def source(self):
        return self._source
    
    @property
    def source_list(self):
        return list(self._available_sources.keys())
    
    @property
    def supported_features(self):
        return SUPPORT_PRIMARE