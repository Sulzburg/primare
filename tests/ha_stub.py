"""A minimal stand-in for Home Assistant, only for the media player tests.

Home Assistant itself is not installed where these tests run. Everything not
defined here resolves to an inert placeholder; the parts the media player logic
really depends on (states, features, entity base) are real enough to test it.
"""

from __future__ import annotations

from enum import IntFlag, StrEnum
import importlib.abc
import importlib.machinery
from pathlib import Path
import sys
import types


class _AnyMeta(type):
    def __getattr__(cls, name):
        return _Any

    def __getitem__(cls, item):
        return cls

    def __or__(cls, other):
        return cls

    __ror__ = __or__


class _Any(metaclass=_AnyMeta):
    """Subclassable, callable, subscriptable – stands in for anything not needed."""

    def __init__(self, *args, **kwargs):
        pass

    def __call__(self, *args, **kwargs):
        return _Any()

    def __getattr__(self, name):
        return _Any()


def callback(func):
    return func


class MediaPlayerState(StrEnum):
    OFF = "off"
    ON = "on"
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"


class MediaPlayerEntityFeature(IntFlag):
    PAUSE = 1
    SEEK = 2
    VOLUME_SET = 4
    VOLUME_MUTE = 8
    PREVIOUS_TRACK = 16
    NEXT_TRACK = 32
    TURN_ON = 128
    TURN_OFF = 256
    VOLUME_STEP = 1024
    SELECT_SOURCE = 2048
    STOP = 4096
    PLAY = 16384
    SELECT_SOUND_MODE = 65536


class MediaType(StrEnum):
    MUSIC = "music"


class MediaPlayerDeviceClass(StrEnum):
    RECEIVER = "receiver"
    SPEAKER = "speaker"


class Entity:
    _attr_media_position = None
    hass = None

    def async_on_remove(self, func):
        pass

    def async_write_ha_state(self):
        self.writes = getattr(self, "writes", 0) + 1

    async def async_added_to_hass(self):
        pass


class MediaPlayerEntity(Entity):
    pass


class HomeAssistantError(Exception):
    pass


class ServiceValidationError(HomeAssistantError):
    pass


_SPECIAL = {
    "homeassistant.core": {"callback": callback},
    "homeassistant.components.media_player": {
        "MediaPlayerState": MediaPlayerState,
        "MediaPlayerEntityFeature": MediaPlayerEntityFeature,
        "MediaType": MediaType,
        "MediaPlayerDeviceClass": MediaPlayerDeviceClass,
        "MediaPlayerEntity": MediaPlayerEntity,
    },
    "homeassistant.helpers.entity": {"Entity": Entity},
    "homeassistant.exceptions": {
        "HomeAssistantError": HomeAssistantError,
        "ServiceValidationError": ServiceValidationError,
    },
}


class _StubModule(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        return _Any


class _Finder(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    ROOTS = ("homeassistant", "voluptuous")

    def find_spec(self, fullname, path, target=None):
        if fullname.split(".")[0] in self.ROOTS:
            return importlib.machinery.ModuleSpec(fullname, self, is_package=True)
        return None

    def create_module(self, spec):
        module = _StubModule(spec.name)
        module.__path__ = []
        for key, value in _SPECIAL.get(spec.name, {}).items():
            setattr(module, key, value)
        return module

    def exec_module(self, module):
        pass


def install():
    """Make 'custom_components.primare' importable on top of the stand-in."""
    if not any(isinstance(f, _Finder) for f in sys.meta_path):
        sys.meta_path.insert(0, _Finder())
    root = str(Path(__file__).resolve().parents[1])
    if root not in sys.path:
        sys.path.insert(0, root)
