"""Shared availability and registry identity for Primare controls."""

from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN


class PrimareControlEntity:
    """Listen to the shared control session."""

    def __init__(self, hass, entry, coordinator, platform, field, suffix, label):
        super().__init__()
        device_name = entry.data["device_name"]
        self._coordinator = coordinator
        self._field = field
        self._attr_name = f"{device_name} {label}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, manufacturer="Primare", name=device_name
        )

        registry = er.async_get(hass)
        legacy_id = f"primare_{device_name.lower().replace(' ', '_')}_{suffix}"
        entity_id = registry.async_get_entity_id(platform, DOMAIN, legacy_id)
        # Reuse legacy registry rows only for their original config entry.
        if entity_id and registry.async_get(entity_id).config_entry_id == entry.entry_id:
            self._attr_unique_id = legacy_id
        else:
            self._attr_unique_id = f"{entry.entry_id}_{suffix}"

    @property
    def available(self):
        return self._coordinator.available(self._field)

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        self.async_on_remove(self._coordinator.async_add_listener(self.async_write_ha_state))
