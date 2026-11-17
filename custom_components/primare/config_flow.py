"""Einrichtung, Neukonfiguration (IP/Port) und Optionen (Gerätetyp, Eingänge)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .client import DEFAULT_PORT, VOLUME_MAX, async_probe
from .const import (
    CONF_DEVICE_TYPE,
    CONF_HOST,
    CONF_INPUTS,
    CONF_MAX_VOLUME,
    CONF_NAME,
    CONF_PORT,
    DEFAULT_INPUTS,
    DOMAIN,
    TYPE_MULTICHANNEL,
    TYPE_STEREO,
    TYPE_STREAMER,
    format_inputs,
    parse_inputs,
)

TYPE_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[
            SelectOptionDict(value=TYPE_MULTICHANNEL, label="SP25 / SPA25 (Presets + DSP)"),
            SelectOptionDict(value=TYPE_STEREO, label="Vor-/Vollverstärker (Eingänge)"),
            SelectOptionDict(value=TYPE_STREAMER, label="Netzwerkplayer (nur Power + Lautstärke)"),
        ],
        mode=SelectSelectorMode.LIST,
    )
)
PORT_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
)


async def _test(host: str, port: int) -> str | None:
    try:
        await async_probe(host, port)
    except (OSError, TimeoutError):
        return "cannot_connect"
    return None


class PrimareConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PrimareOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_PORT] = int(user_input[CONF_PORT])
            self._async_abort_entries_match({CONF_HOST: user_input[CONF_HOST]})
            if not (error := await _test(user_input[CONF_HOST], user_input[CONF_PORT])):
                return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): PORT_SELECTOR,
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_DEVICE_TYPE, default=TYPE_MULTICHANNEL): TYPE_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input or {}),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            host, port = user_input[CONF_HOST], int(user_input[CONF_PORT])
            if not (error := await _test(host, port)):
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_HOST: host, CONF_PORT: port}
                )
            errors["base"] = error

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                vol.Required(
                    CONF_PORT, default=entry.data.get(CONF_PORT, DEFAULT_PORT)
                ): PORT_SELECTOR,
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)


class PrimareOptionsFlow(OptionsFlow):
    """Gerätetyp und Eingangsnamen in der Oberfläche statt in const.py."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        entry = self.config_entry
        current_type = entry.options.get(
            CONF_DEVICE_TYPE, entry.data.get(CONF_DEVICE_TYPE, TYPE_MULTICHANNEL)
        )
        errors: dict[str, str] = {}

        if user_input is not None:
            new_type = user_input[CONF_DEVICE_TYPE]
            text = user_input.get(CONF_INPUTS, "")
            if new_type != current_type and text.strip() == format_inputs(
                DEFAULT_INPUTS.get(current_type, {})
            ):
                # Typ gewechselt, Liste nicht angefasst → Vorgabe des neuen Typs
                text = format_inputs(DEFAULT_INPUTS.get(new_type, {}))
            try:
                inputs = parse_inputs(text)
            except ValueError:
                errors[CONF_INPUTS] = "invalid_inputs"
            else:
                return self.async_create_entry(
                    data={
                        CONF_DEVICE_TYPE: new_type,
                        CONF_INPUTS: format_inputs(inputs),
                        CONF_MAX_VOLUME: int(user_input[CONF_MAX_VOLUME]),
                    }
                )

        if CONF_INPUTS in entry.options:
            current_inputs = entry.options[CONF_INPUTS]
        else:
            current_inputs = format_inputs(DEFAULT_INPUTS.get(current_type, {}))

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_TYPE, default=current_type): TYPE_SELECTOR,
                vol.Required(
                    CONF_MAX_VOLUME,
                    default=int(entry.options.get(CONF_MAX_VOLUME, VOLUME_MAX)),
                ): NumberSelector(
                    NumberSelectorConfig(
                        min=1, max=VOLUME_MAX, step=1, mode=NumberSelectorMode.SLIDER
                    )
                ),
                vol.Optional(CONF_INPUTS, default=current_inputs): TextSelector(
                    TextSelectorConfig(multiline=True)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
