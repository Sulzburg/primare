"""Configure one Primare device per address."""

from ipaddress import ip_address
import re

from homeassistant import config_entries
import voluptuous as vol

from .const import DOMAIN

DEVICE_TYPE_OPTIONS = ("Multichannel", "Stereo")


def _normalize_host(value: str) -> str:
    host = value.strip()
    try:
        return str(ip_address(host))
    except ValueError:
        return host.rstrip(".").casefold()


class PrimareConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = _normalize_host(user_input["ip_address"])
            try:
                ip_address(host)
                valid_host = True
            except ValueError:
                valid_host = bool(re.fullmatch(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*", host))
            name = user_input["device_name"].strip()
            if not valid_host:
                errors["ip_address"] = "invalid_host"
            if not name:
                errors["device_name"] = "missing_name"
            if not errors:
                await self.async_set_unique_id(host)
                self._abort_if_unique_id_configured()
                if any(
                    _normalize_host(entry.data["ip_address"]) == host
                    for entry in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_create_entry(
                    title=name,
                    data={**user_input, "ip_address": host, "device_name": name},
                )

        schema = vol.Schema({
            vol.Required("ip_address"): str,
            vol.Required("device_name"): str,
            vol.Required("device_type", default="Multichannel"): vol.In(DEVICE_TYPE_OPTIONS),
        })
        return self.async_show_form(
            step_id="user", data_schema=self.add_suggested_values_to_schema(schema, user_input), errors=errors
        )
