import voluptuous as vol
from homeassistant import config_entries

DOMAIN = "primare"

class PrimareConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            return self.async_create_entry(title="Primare", data=user_input)
        data_schema = vol.Schema({
            vol.Required("ip_address"): str,
            vol.Required("device_name"): str,
        })
        return self.async_show_form(step_id="user", data_schema=data_schema, errors=errors)
