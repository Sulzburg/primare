"""Regression tests for the local controls against a simulated Primare device."""

import asyncio
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from homeassistant import loader
from homeassistant.bootstrap import async_load_base_functionality
from homeassistant.config_entries import ConfigEntries, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component

from custom_components.primare import coordinator as controls


class PrimareControlsTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory(prefix="primare-controls-"))
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "custom_components" / "primare",
            Path(directory) / "custom_components" / "primare",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        self.hass = HomeAssistant(directory)
        loader.async_setup(self.hass)
        self.hass.config_entries = ConfigEntries(self.hass, {})
        self.assertTrue(await async_load_base_functionality(self.hass))
        self.assertTrue(await async_setup_component(self.hass, "primare", {}))
        await self.hass.async_start()
        self.addAsyncCleanup(self.hass.async_stop)
        self.writers = set()
        self.requests = []
        self.ignored = set()
        self.responses = {b"pow": b"1", b"mut": b"0", b"inp": b"13", b"vol": b"31"}
        self.server = await asyncio.start_server(self.peer, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.enterContext(patch.object(controls, "DEFAULT_PORT", self.port))
        self.enterContext(patch.object(controls, "RECONNECT_DELAY", 0.1))
        self.addAsyncCleanup(self.close_server)

    async def close_server(self):
        self.server.close()
        for writer in tuple(self.writers):
            writer.close()
        await self.server.wait_closed()

    async def peer(self, reader, writer):
        self.writers.add(writer)
        try:
            while raw := await reader.readline():
                request = raw.strip()
                self.requests.append(request)
                if request in self.ignored:
                    continue
                key, suffix = request.removeprefix(b"!1").split(b".")
                value = self.responses.get(key) if suffix == b"?" else suffix
                if value is not None:
                    writer.write(b"!1" + key + b"." + value + b"\r\n")
                    await writer.drain()
        except OSError:
            pass
        finally:
            self.writers.discard(writer)
            writer.close()

    async def add(self, name="Audit", host="127.0.0.1"):
        form = await self.hass.config_entries.flow.async_init("primare", context={"source": "user"})
        return await self.hass.config_entries.flow.async_configure(
            form["flow_id"],
            {"ip_address": host, "device_name": name, "device_type": "Stereo"},
        )

    async def until(self, condition):
        async with asyncio.timeout(5):
            while not (result := condition()):
                await asyncio.sleep(0.01)
            return result

    def state(self, entity_id):
        value = self.hass.states.get(entity_id)
        return value.state if value is not None else None

    async def test_offline_boot_and_reconnect_publish_real_states(self):
        await self.close_server()
        result = await self.add()
        self.assertIs(result["result"].state, ConfigEntryState.LOADED)
        await self.until(lambda: self.state("switch.audit_power") == "unavailable")
        self.assertEqual(self.state("number.audit_volume"), "unavailable")
        self.server = await asyncio.start_server(self.peer, "127.0.0.1", self.port)
        await self.until(lambda: self.state("switch.audit_power") == "on")
        self.assertEqual(self.state("select.audit_input"), "Prisma")
        self.assertEqual(self.state("number.audit_volume"), "31")
        self.assertNotIn(b"!1sur.?", self.requests)

        self.responses[b"pow"] = b"0"
        next(iter(self.writers)).close()
        await self.until(lambda: self.state("switch.audit_power") == "unavailable")
        await self.until(lambda: self.state("switch.audit_power") == "off")
        self.assertEqual(self.requests.count(b"!1pow.?"), 2)

    async def test_a_silent_socket_is_replaced(self):
        with patch.object(controls, "HEARTBEAT_INTERVAL", 0.05):
            await self.add()
            await self.until(lambda: self.state("switch.audit_power") == "on")
            writer = next(iter(self.writers))
            self.ignored.add(b"!1pow.?")
            await self.until(lambda: self.state("switch.audit_power") == "unavailable")
            self.ignored.remove(b"!1pow.?")
            await self.until(lambda: self.state("switch.audit_power") == "on")
            self.assertNotIn(writer, self.writers)

    async def test_split_replies_and_unconfirmed_command(self):
        await self.add()
        await self.until(lambda: self.state("number.audit_volume") == "31")
        writer = next(iter(self.writers))
        writer.write(b"!1vol.4")
        await writer.drain()
        await asyncio.sleep(0.06)
        self.assertEqual(self.state("number.audit_volume"), "31")
        writer.write(b"2\r\n!1inp.12\r\n")
        await writer.drain()
        await self.until(lambda: self.state("number.audit_volume") == "42")
        self.assertEqual(self.state("select.audit_input"), "PC/MAC")

        with self.assertRaises(HomeAssistantError):
            await self.hass.services.async_call(
                "number", "set_value", {"entity_id": "number.audit_volume", "value": 100},
                blocking=True,
            )
        self.assertNotIn(b"!1vol.100", self.requests)
        self.ignored.add(b"!1pow.0")
        with self.assertRaisesRegex(HomeAssistantError, "did not confirm"):
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": "switch.audit_power"}, blocking=True
            )
        self.assertEqual(self.requests.count(b"!1pow.0"), 1)
        self.assertEqual(self.state("switch.audit_power"), "on")

    async def test_reload_retains_legacy_entity_and_same_names_are_distinct(self):
        first = (await self.add())["result"]
        await self.until(lambda: self.state("switch.audit_power") == "on")
        registry = er.async_get(self.hass)
        original_writer = next(iter(self.writers))

        self.assertTrue(await self.hass.config_entries.async_unload(first.entry_id))
        await self.until(lambda: original_writer not in self.writers)
        registry.async_update_entity(
            "switch.audit_power",
            new_entity_id="switch.legacy_power",
            new_unique_id="primare_audit_power_switch",
        )
        self.assertTrue(await self.hass.config_entries.async_setup(first.entry_id))
        await self.until(lambda: self.state("switch.legacy_power") == "on")
        self.assertTrue(await self.hass.config_entries.async_reload(first.entry_id))
        await self.until(lambda: self.state("switch.legacy_power") == "on")

        second = (await self.add(host="localhost"))["result"]
        await self.until(lambda: len(er.async_entries_for_config_entry(registry, second.entry_id)) == 4)
        self.assertEqual(len(er.async_entries_for_config_entry(registry, first.entry_id)), 4)
        self.assertNotEqual(first.entry_id, second.entry_id)
        result = await self.add("Different", "LOCALHOST.")
        self.assertEqual(result["reason"], "already_configured")
