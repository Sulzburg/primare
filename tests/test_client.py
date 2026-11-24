"""Exercise the control client (port 50006) against a simulated Primare device.

Runs without Home Assistant: python -m unittest discover tests
"""

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

_PATH = Path(__file__).resolve().parents[1] / "custom_components/primare/client.py"
_SPEC = importlib.util.spec_from_file_location("primare_test_client", _PATH)
client = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = client
_SPEC.loader.exec_module(client)


class FakePrimare:
    """Answers like a Primare device: echoes set values, answers queries."""

    def __init__(self):
        self.state = {"pow": "1", "mut": "0", "vol": "20", "inp": "04", "sur": "1"}
        self.received = []
        self.split = False
        self.silent = False
        self.writers = []

    async def handle(self, reader, writer):
        self.writers.append(writer)
        try:
            while True:
                cmd = (await reader.readuntil(b"\r\n")).decode().strip()
                self.received.append(cmd)
                if self.silent:
                    continue
                key, val = cmd[2:5], cmd[6:]
                if val == "u":
                    self.state["vol"] = str(min(99, int(self.state["vol"]) + 1))
                elif val == "d":
                    self.state["vol"] = str(max(0, int(self.state["vol"]) - 1))
                elif val != "?":
                    self.state[key] = val
                out = f"!1{key}.{self.state[key]}\r\n".encode()
                if self.split:
                    writer.write(out[:4])
                    await writer.drain()
                    await asyncio.sleep(0.02)
                    writer.write(out[4:])
                else:
                    writer.write(out)
                await writer.drain()
        except Exception:  # noqa: BLE001 – connection closed by the test
            pass

    def drop_all(self):
        for writer in self.writers:
            writer.close()
        self.writers = []


class ClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name, value in {
            "RECONNECT_DELAYS": (0.1, 0.2),
            "KEEPALIVE_INTERVAL": 0.5,
            "REQUERY_DELAY_AFTER_POWER_ON": 0.1,
        }.items():
            self.enterContext(patch.object(client, name, value))
        self.dev = FakePrimare()
        self.server = await asyncio.start_server(self.dev.handle, "127.0.0.1", 0)
        self.port = self.server.sockets[0].getsockname()[1]
        self.clients = []

    async def asyncTearDown(self):
        for cl in self.clients:
            await cl.stop()
        self.server.close()
        self.dev.drop_all()

    async def connect(self, **kwargs):
        cl = client.PrimareClient("127.0.0.1", self.port, name="Test", **kwargs)
        self.clients.append(cl)
        await cl.start(wait=2)
        return cl

    async def until(self, condition, timeout=4):
        async with asyncio.timeout(timeout):
            while not condition():
                await asyncio.sleep(0.02)

    async def test_initial_state_and_split_replies(self):
        cl = await self.connect()
        await self.until(lambda: (cl.power, cl.volume, cl.input, cl.dsp, cl.mute) == (True, 20, 4, 1, False))
        self.dev.split = True
        await cl.set_volume(33)
        await self.until(lambda: cl.volume == 33)

    async def test_two_messages_in_one_packet(self):
        cl = await self.connect()
        cl._feed("!1vol.10!1mut.1\r\n")
        self.assertEqual((cl.volume, cl.mute), (10, True))

    async def test_volume_is_limited_to_99(self):
        cl = await self.connect()
        await cl.set_volume(150)
        await self.until(lambda: cl.volume == 99)
        self.assertNotIn("!1vol.150", self.dev.received)

    async def test_reconnects_after_drop_and_after_silence(self):
        cl = await self.connect()
        self.dev.drop_all()
        await self.until(lambda: not cl.connected)
        await self.until(lambda: cl.connected)
        self.dev.silent = True
        await self.until(lambda: not cl.connected)
        self.dev.silent = False
        await self.until(lambda: cl.connected)

    async def test_command_without_connection_raises(self):
        cl = await self.connect()
        self.server.close()
        self.dev.drop_all()
        await asyncio.wait_for(self.server.wait_closed(), 2)
        await self.until(lambda: not cl.connected)
        with self.assertRaises(client.PrimareNotConnected):
            await cl.set_volume(10)
        self.server = await asyncio.start_server(self.dev.handle, "127.0.0.1", self.port)
        await self.until(lambda: cl.connected)

    async def test_requery_after_power_on(self):
        cl = await self.connect()
        await cl.set_power(False)
        await self.until(lambda: cl.power is False)
        self.dev.received.clear()
        await cl.set_power(True)
        await self.until(lambda: "!1vol.?" in self.dev.received)

    async def test_fades_cancel_each_other(self):
        cl = await self.connect()
        await cl.set_volume(40)
        await self.until(lambda: cl.volume == 40)
        first = asyncio.create_task(cl.fade(0, 1.0, steps=10))
        await asyncio.sleep(0.25)
        second = asyncio.create_task(cl.fade(30, 0.3, steps=3))
        await asyncio.gather(first, second)
        self.assertIsNone(first.exception())
        await self.until(lambda: cl.volume == 30)

    async def test_set_volume_cancels_fade(self):
        cl = await self.connect()
        fade = asyncio.create_task(cl.fade(0, 1.0, steps=10))
        await asyncio.sleep(0.15)
        await cl.set_volume(25)
        await fade
        await asyncio.sleep(0.3)
        self.assertEqual(cl.volume, 25)

    async def test_volume_steps(self):
        cl = await self.connect()
        await cl.step_volume(-3, 0.01)
        await self.until(lambda: cl.volume == 17)

    async def test_max_volume(self):
        self.dev.state["vol"] = "40"
        cl = await self.connect(max_volume=45)
        await self.until(lambda: cl.volume == 40)
        await cl.set_volume(80)
        await self.until(lambda: cl.volume == 45)
        self.dev.received.clear()
        await cl.volume_up()
        await asyncio.sleep(0.2)
        self.assertNotIn("!1vol.u", self.dev.received)
        await cl.set_volume(42)
        await self.until(lambda: cl.volume == 42)
        await cl.step_volume(10, 0.01)
        await self.until(lambda: cl.volume == 45)
        await asyncio.sleep(0.3)
        self.assertEqual(cl.volume, 45)
        await cl.fade(99, 0.3, steps=5)
        await asyncio.sleep(0.2)
        self.assertEqual(cl.volume, 45)
        await cl.step_volume(-5, 0.01)
        await self.until(lambda: cl.volume == 40)


if __name__ == "__main__":
    unittest.main()
