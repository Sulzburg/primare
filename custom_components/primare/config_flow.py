import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import CONF_PLAYBACK_STATUS, DOMAIN

DEVICE_TYPE_OPTIONS = {
    "Multichannel": "Multichannel",
    "Stereo": "Stereo"
}

class PrimareConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return PrimareOptionsFlow()

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title=user_input["device_name"], data=user_input)
        data_schema = vol.Schema({
            vol.Required("ip_address"): str,
            vol.Required("device_name"): str,
            vol.Required("device_type", default="Multichannel"): vol.In(DEVICE_TYPE_OPTIONS),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)


class PrimareOptionsFlow(config_entries.OptionsFlow):
    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_PLAYBACK_STATUS,
                    default=self.config_entry.options.get(CONF_PLAYBACK_STATUS, False),
                ): bool,
            }),
        )
