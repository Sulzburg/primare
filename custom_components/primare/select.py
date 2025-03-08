import socket
import logging
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from datetime import timedelta

_LOGGER = logging.getLogger(__name__)

SP25_IP = "XXX.XXX.XXX.XXX"
SP25_PORT = 50006
END_CHARACTER = "\r\n"

# Inputs mit sprechenden Namen
INPUT_PRESETS = {
    "BD LG": "!1inp.1",
    "BD PAN": "!1inp.2",
    "FireTV": "!1inp.3",
    "HDMI ARC": "!1inp.4",
    "TV Opto": "!1inp.5",
#    "Game Console": "!1inp.6",
#    "SAT/Receiver": "!1inp.7",
    "PC/Mac": "!1inp.8",
#    "Radio": "!1inp.9",
#    "PC": "!1inp.10",
#    "Spotify": "!1inp.11",
#    "Tidal": "!1inp.12",
#    "Deezer": "!1inp.13",
#    "USB": "!1inp.14",
#    "Kabel TV": "!1inp.15",
#    "Test Input 1": "!1inp.16",
    "Prisma": "!1inp.17"
}

# DSP-Modi mit sprechenden Namen
DSP_MODES = {
    "Auto": "!1sur.1",
    "Bypass": "!1sur.2",
    "Stereo": "!1sur.3",
    "Party": "!1sur.4",
    "Dolby Digital: Movie": "!1sur.5",
    "Dolby Digital: Music": "!1sur.6",
    "Dolby Digital: Night": "!1sur.7",
    "DTS Neural: X": "!1sur.8",
    "Native": "!1sur.9"
}

def send_command(command):
    """Sendet einen Befehl an den SP25 und gibt die Antwort zurück."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((SP25_IP, SP25_PORT))
            s.sendall((command + END_CHARACTER).encode("ascii"))
            response = s.recv(1024).decode("ascii").strip()
            return response
    except Exception as e:
        _LOGGER.error(f"Fehler beim Senden des Befehls: {e}")
        return None

def get_current_input():
    """Fragt den aktuellen Eingang ab."""
    response = send_command("!1inp.?")
    for name, cmd in INPUT_PRESETS.items():
        if response == cmd:
            return name
    return None

def get_current_dsp():
    """Fragt den aktuellen DSP-Modus ab."""
    response = send_command("!1sur.?")
    for name, cmd in DSP_MODES.items():
        if response == cmd:
            return name
    return None

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Setzt die Select-Entitäten in Home Assistant auf."""
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="sp25_status",
        update_method=async_update_data,
        update_interval=timedelta(seconds=5),
    )
    add_entities([SP25InputSelect(coordinator), SP25DSPSelect(coordinator)])
    coordinator.async_config_entry_first_refresh()

async def async_update_data():
    """Abrufen der aktuellen Daten."""
    return {
        "input": get_current_input(),
        "dsp": get_current_dsp()
    }

class SP25InputSelect(CoordinatorEntity, SelectEntity):
    """Preset-Auswahl für den SP25 (Eingangsquelle)."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_options = list(INPUT_PRESETS.keys())
        self._attr_unique_id = "sp25_preset_select"       
        self._attr_icon = "mdi:audio-input-rca"
    
    @property
    def name(self):
        return "SP25 Input Source"
    
    @property
    def current_option(self):
        return self.coordinator.data.get("input")

    def select_option(self, option):
        if option in INPUT_PRESETS:
            send_command(INPUT_PRESETS[option])
            self.coordinator.async_request_refresh()

class SP25DSPSelect(CoordinatorEntity, SelectEntity):
    """DSP-Modus-Auswahl für den SP25."""

    def __init__(self, coordinator):
        super().__init__(coordinator)
        self._attr_options = list(DSP_MODES.keys())
        self._attr_unique_id = "sp25_dsp_select"        
        self._attr_icon = "mdi:surround-sound"
    
    @property
    def name(self):
        return "SP25 DSP Mode"
    
    @property
    def current_option(self):
        return self.coordinator.data.get("dsp")

    def select_option(self, option):
        if option in DSP_MODES:
            send_command(DSP_MODES[option])
            self.coordinator.async_request_refresh()
