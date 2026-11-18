"""Aktionen primare.volume_up/down/relative/fade.

Felder aus Version 1 (entry_id, device_name) funktionieren weiter;
neu ist die Geräteauswahl (device_id).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import voluptuous as vol

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .client import PrimareNotConnected
from .const import DOMAIN

if TYPE_CHECKING:
    from .client import PrimareClient

_TARGET = {
    vol.Optional("device_id"): vol.Any(cv.string, [cv.string]),
    vol.Optional("entry_id"): cv.string,
    vol.Optional("device_name"): cv.string,
}

UPDOWN_SCHEMA = vol.Schema(
    {**_TARGET, vol.Optional("times", default=1): vol.All(vol.Coerce(int), vol.Range(1, 10))}
)
REL_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Required("delta"): vol.Coerce(int),
        vol.Optional("mode", default="steps"): vol.In(["steps", "absolute"]),
        vol.Optional("step_delay_ms", default=40): vol.All(vol.Coerce(int), vol.Range(0, 500)),
    }
)
FADE_SCHEMA = vol.Schema(
    {
        **_TARGET,
        vol.Optional("target", default=0): vol.All(vol.Coerce(int), vol.Range(0, 100)),
        vol.Optional("duration_ms", default=1200): vol.All(vol.Coerce(int), vol.Range(1, 60000)),
        vol.Optional("easing", default="linear"): vol.In(
            ["linear", "ease_in", "ease_out", "ease_in_out"]
        ),
        vol.Optional("mode", default="absolute"): vol.In(["absolute", "steps"]),
        vol.Optional("steps", default=10): vol.All(vol.Coerce(int), vol.Range(1, 100)),
        vol.Optional("step_delay_ms", default=40): vol.All(vol.Coerce(int), vol.Range(0, 500)),
    }
)


def _resolve(hass: HomeAssistant, call: ServiceCall) -> PrimareClient:
    entries = [
        e for e in hass.config_entries.async_entries(DOMAIN)
        if e.state is ConfigEntryState.LOADED
    ]
    if not entries:
        raise ServiceValidationError("No Primare device loaded.")

    data = call.data
    if device_id := data.get("device_id"):
        if isinstance(device_id, list):
            if len(device_id) != 1:
                raise ServiceValidationError("Please select exactly one device.")
            device_id = device_id[0]
        device = dr.async_get(hass).async_get(device_id)
        for entry in entries:
            if device and entry.entry_id in device.config_entries:
                return entry.runtime_data.client
        raise ServiceValidationError(f"Device not found: {device_id}")

    if entry_id := data.get("entry_id"):
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry.runtime_data.client
        raise ServiceValidationError(f"entry_id not found: {entry_id}")

    if name := data.get("device_name"):
        wanted = name.casefold()
        matches = [
            e for e in entries
            if wanted in (e.title.casefold(), str(e.data.get("device_name", "")).casefold())
        ]
        if len(matches) == 1:
            return matches[0].runtime_data.client
        known = ", ".join(e.title for e in entries)
        raise ServiceValidationError(f"device_name not found or ambiguous: {name} (known: {known})")

    if len(entries) == 1:
        return entries[0].runtime_data.client
    raise ServiceValidationError("Several Primare devices – please specify one.")


async def _run(coro) -> None:
    try:
        await coro
    except PrimareNotConnected as err:
        raise HomeAssistantError(str(err)) from err


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    async def volume_up(call: ServiceCall) -> None:
        await _run(_resolve(hass, call).step_volume(call.data["times"], 0.04))

    async def volume_down(call: ServiceCall) -> None:
        await _run(_resolve(hass, call).step_volume(-call.data["times"], 0.04))

    async def volume_relative(call: ServiceCall) -> None:
        client = _resolve(hass, call)
        delta = call.data["delta"]
        if delta == 0:
            return
        if call.data["mode"] == "steps":
            await _run(client.step_volume(delta, call.data["step_delay_ms"] / 1000))
            return
        if client.volume is None:
            raise HomeAssistantError("Current volume unknown.")
        await _run(client.set_volume(client.volume + delta))

    async def volume_fade(call: ServiceCall) -> None:
        client = _resolve(hass, call)
        await _run(
            client.fade(
                call.data["target"],
                call.data["duration_ms"] / 1000,
                easing=call.data["easing"],
                steps=call.data["steps"],
                mode=call.data["mode"],
                step_delay=call.data["step_delay_ms"] / 1000,
            )
        )

    hass.services.async_register(DOMAIN, "volume_up", volume_up, schema=UPDOWN_SCHEMA)
    hass.services.async_register(DOMAIN, "volume_down", volume_down, schema=UPDOWN_SCHEMA)
    hass.services.async_register(DOMAIN, "volume_relative", volume_relative, schema=REL_SCHEMA)
    hass.services.async_register(DOMAIN, "volume_fade", volume_fade, schema=FADE_SCHEMA)
