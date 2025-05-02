import voluptuous as vol
from homeassistant import config_entries

DOMAIN = "primare"

DEVICE_TYPE_OPTIONS = {
    "SP25": "Multichannel",
    "Pre35": "Stereo"
}

class PrimareConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title=user_input["device_name"], data=user_input)
        data_schema = vol.Schema({
            vol.Required("ip_address"): str,
            vol.Required("device_name"): str,
            vol.Required("device_type", default="SP25"): vol.In(DEVICE_TYPE_OPTIONS),
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)
