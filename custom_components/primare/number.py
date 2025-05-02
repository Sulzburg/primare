import logging
from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities):
    entry_data = hass.data["primare"].get(config_entry.entry_id)
    if not entry_data:
        raise RuntimeError(f"Kein Eintrag für {config_entry.entry_id} gefunden")

    coordinator = entry_data["coordinator"]
    device_name = entry_data["device_name"]

    async_add_entities([PrimareVolumeControl(coordinator, device_name)])

class PrimareVolumeControl(NumberEntity):
    def __init__(self, coordinator, device_name: str):
        """Initialisiert den Volume-Slider und speichert den Coordinator."""
        self._coordinator = coordinator
        self._device_name = device_name
        self._unique_id = f"primare_{device_name.lower().replace(' ', '_')}_volume_control"
        self._remove_listener = None

    async def async_added_to_hass(self) -> None:
        """Registriert den Listener, damit die Entität aktualisiert wird, sobald der Coordinator neue Daten hat."""
        self._remove_listener = self._coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Entfernt den Listener beim Entfernen der Entität."""
        if self._remove_listener:
            self._remove_listener()

    @property
    def name(self) -> str:
        return f"{self._device_name} Volume"

    @property
    def unique_id(self) -> str:
        return self._unique_id

    @property
    def native_min_value(self) -> float:
        return 0

    @property
    def native_max_value(self) -> float:
        return 100

    @property
    def native_step(self) -> float:
        return 1

    @property
    def mode(self) -> str:
        return "slider"

    @property
    def native_value(self) -> float:
        # Wenn noch kein Wert vorhanden ist, wird 0 zurückgegeben.
        value = self._coordinator.data.get("volume")
        return value if value is not None else 0

    @property
    def icon(self) -> str:
        return "mdi:volume-high"

    async def async_set_value(self, value: float) -> None:
        command = f"!1vol.{int(value)}"
        await self._coordinator.async_send_command(command)
