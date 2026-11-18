"""Primare-Integration (SP25 / SPA25, Pre35 & Co., NP5) über TCP/IP."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.typing import ConfigType

from .client import DEFAULT_PORT, VOLUME_MAX, PrimareClient
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
    DeviceProfile,
    parse_inputs,
)
from .identity import async_read_identity
from .services import async_setup_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [
    Platform.MEDIA_PLAYER,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.BUTTON,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class PrimareRuntime:
    client: PrimareClient
    profile: DeviceProfile
    model: str | None = None  # as the device reported it (UPnP), remembered
    location: str | None = None  # address of the device's UPnP description


type PrimareConfigEntry = ConfigEntry[PrimareRuntime]


def build_profile(entry: ConfigEntry) -> DeviceProfile:
    device_type = entry.options.get(
        CONF_DEVICE_TYPE, entry.data.get(CONF_DEVICE_TYPE, TYPE_MULTICHANNEL)
    )
    inputs = DEFAULT_INPUTS.get(device_type, {})
    if CONF_INPUTS in entry.options:
        try:
            inputs = parse_inputs(entry.options[CONF_INPUTS])
        except ValueError:
            _LOGGER.warning("%s: Eingangsliste in den Optionen ungültig – nutze Vorgabe", entry.title)
    return DeviceProfile(device_type, inputs)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_setup_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PrimareConfigEntry) -> bool:
    profile = build_profile(entry)
    client = PrimareClient(
        entry.data[CONF_HOST],
        entry.data.get(CONF_PORT, DEFAULT_PORT),
        queries=profile.queries,
        name=entry.title,
        max_volume=int(entry.options.get(CONF_MAX_VOLUME, VOLUME_MAX)),
    )
    # Kurz auf die erste Verbindung warten, damit Entitäten gleich Werte haben.
    # Klappt das nicht, laufen die Versuche im Hintergrund weiter und die
    # Entitäten stehen so lange auf "nicht verfügbar".
    await client.start(wait=3)
    store = _identity_store(hass, entry)
    known = await store.async_load() or {}
    entry.runtime_data = PrimareRuntime(
        client, profile, model=known.get("model"), location=known.get("location")
    )
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_create_background_task(
        hass, _async_update_identity(hass, entry, store, known), "primare_identity"
    )
    return True


def _identity_store(hass: HomeAssistant, entry: ConfigEntry) -> Store:
    return Store(hass, 1, f"{DOMAIN}.identity.{entry.entry_id}")


async def _async_update_identity(
    hass: HomeAssistant, entry: PrimareConfigEntry, store: Store, known: dict
) -> None:
    """Model as the device reports it (UPnP), onto the device page – and remember it.

    A model read once stays, even if the device does not answer on a later start.
    """
    info = await async_read_identity(entry.data[CONF_HOST], known.get("location"))
    manufacturer = info.get("manufacturer", "")
    if manufacturer and "primare" not in manufacturer.lower():
        return
    if info.get("location"):
        entry.runtime_data.location = info["location"]
    if info.get("model") and (
        info["model"] != known.get("model") or info.get("location") != known.get("location")
    ):
        await store.async_save({"model": info["model"], "location": info.get("location")})
    registry = dr.async_get(hass)
    for device in dr.async_entries_for_config_entry(registry, entry.entry_id):
        if (DOMAIN, entry.entry_id) not in device.identifiers:
            continue
        changes = {}
        model = info.get("model") or known.get("model")
        if model and device.model != model:
            changes["model"] = model
        if device.serial_number:
            # Neither UPnP nor LUCI deliver the real Primare serial – remove what the
            # 2.3.0 test versions wrote. The integration owns this device.
            changes["serial_number"] = None
        if changes:
            registry.async_update_device(device.id, **changes)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Forget the remembered model when the device is removed."""
    await _identity_store(hass, entry).async_remove()


async def async_unload_entry(hass: HomeAssistant, entry: PrimareConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.client.stop()
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: PrimareConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """1.1 → 1.2: unique_id vom Gerätenamen auf die Eintrags-ID umstellen.

    Die Entity-IDs bleiben dabei unverändert; Automationen merken nichts.
    """
    if entry.version > 1:
        return False

    if entry.minor_version < 2:
        slug = str(entry.data.get(CONF_NAME, entry.title)).lower().replace(" ", "_")
        old_prefix = f"primare_{slug}_"

        @callback
        def _migrate(reg_entry: er.RegistryEntry) -> dict[str, str] | None:
            if reg_entry.unique_id.startswith(old_prefix):
                suffix = reg_entry.unique_id[len(old_prefix):]
                return {"new_unique_id": f"{entry.entry_id}_{suffix}"}
            return None

        await er.async_migrate_entries(hass, entry.entry_id, _migrate)
        hass.config_entries.async_update_entry(entry, minor_version=2)
        _LOGGER.info("%s: unique_ids migriert (Version 1.2)", entry.title)

    return True
