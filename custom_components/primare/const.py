"""Konstanten und Geräteprofile der Primare-Integration."""

from __future__ import annotations

from dataclasses import dataclass, field

DOMAIN = "primare"

# Schlüssel in entry.data (Namen aus Version 1 beibehalten)
CONF_HOST = "ip_address"
CONF_NAME = "device_name"
CONF_DEVICE_TYPE = "device_type"
CONF_PORT = "port"
# Schlüssel in entry.options
CONF_INPUTS = "inputs"
CONF_MAX_VOLUME = "max_volume"
CONF_PLAYBACK = "playback_status"  # gleicher Schlüssel wie in PR #3 von yvos

TYPE_MULTICHANNEL = "Multichannel"  # SP25 / SPA25: Presets + DSP
TYPE_STEREO = "Stereo"              # Vor-/Vollverstärker: Eingänge
TYPE_STREAMER = "Streamer"          # z. B. NP5: nur Power + Lautstärke
DEVICE_TYPES = [TYPE_MULTICHANNEL, TYPE_STEREO, TYPE_STREAMER]

# Vorgabe-Eingangsnamen, solange in den Optionen nichts eingetragen ist
DEFAULT_INPUTS: dict[str, dict[int, str]] = {
    TYPE_MULTICHANNEL: {
        1: "BD LG",
        2: "BD PAN",
        3: "FireTV",
        4: "HDMI ARC",
        5: "TV Opto",
        17: "Prisma",
    },
    TYPE_STEREO: {
        1: "R35",
        3: "SP25",
        6: "TV",
        10: "NP5",
        12: "PC/MAC",
        13: "Prisma",
    },
    TYPE_STREAMER: {},
}

DSP_MAP: dict[int, str] = {
    1: "Auto",
    2: "Bypass",
    3: "Stereo",
    4: "Party",
    5: "Dolby Digital: Movie",
    6: "Dolby Digital: Music",
    7: "Dolby Digital: Night",
    8: "DTS Neural: X",
    9: "Native",
}
DSP_MAP_INV: dict[str, int] = {v: k for k, v in DSP_MAP.items()}


@dataclass(frozen=True)
class DeviceProfile:
    """Was ein Gerätetyp kann."""

    device_type: str
    inputs: dict[int, str] = field(default_factory=dict)

    @property
    def has_mute(self) -> bool:
        return self.device_type != TYPE_STREAMER

    @property
    def has_input(self) -> bool:
        return self.device_type != TYPE_STREAMER and bool(self.inputs)

    @property
    def has_dsp(self) -> bool:
        return self.device_type == TYPE_MULTICHANNEL

    @property
    def queries(self) -> tuple[str, ...]:
        keys = ["pow", "vol"]
        if self.has_mute:
            keys.append("mut")
        if self.has_input:
            keys.append("inp")
        if self.has_dsp:
            keys.append("sur")
        return tuple(keys)

    @property
    def model(self) -> str:
        return {
            TYPE_MULTICHANNEL: "SP25 / SPA25",
            TYPE_STEREO: "Stereo-Vorverstärker",
            TYPE_STREAMER: "Netzwerkplayer",
        }.get(self.device_type, self.device_type)

    @property
    def inputs_inv(self) -> dict[str, int]:
        return {v: k for k, v in self.inputs.items()}


def parse_inputs(text: str) -> dict[int, str]:
    """``"1 = BD LG\\n4 = HDMI ARC"`` → ``{1: "BD LG", 4: "HDMI ARC"}``.

    Wirft ValueError bei ungültigen Zeilen.
    """
    result: dict[int, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        num, sep, name = line.partition("=")
        if not sep:
            raise ValueError(line)
        number = int(num.strip())
        name = name.strip()
        if not 1 <= number <= 17 or not name or name in result.values():
            raise ValueError(line)
        result[number] = name
    return dict(sorted(result.items()))


def format_inputs(inputs: dict[int, str]) -> str:
    return "\n".join(f"{k} = {v}" for k, v in sorted(inputs.items()))
