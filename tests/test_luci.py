"""Exercise the LUCI client against a TCP peer without importing Home Assistant."""

import asyncio
import importlib.util
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

_PATH = Path(__file__).resolve().parents[1] / "custom_components/primare/luci.py"
_SPEC = importlib.util.spec_from_file_location("primare_test_luci", _PATH)
luci = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = luci
_SPEC.loader.exec_module(luci)


def frame(box, payload=b"", status=1):
    return struct.pack(">HBHBHH", 0, 2, box, status, 0, len(payload)) + payload


class LuciTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.state = b"0\0"
        self.push = None
        self.position_reply = frame(luci.POSITION, b"1000")
        self.state_status = 1
        self.command_reply = frame(luci.TRANSPORT)
        self.requests = []
        self.connections = 0
        self.disconnected = asyncio.Event()
        self.server = await asyncio.start_server(self.device, "127.0.0.1", 0)
        self.client = luci.LuciPlaybackClient(
            "127.0.0.1", self.server.sockets[0].getsockname()[1]
        )

    async def asyncTearDown(self):
        await self.client.async_shutdown()
        self.server.close()
        await self.server.wait_closed()

    async def device(self, reader, writer):
        self.connections += 1
        try:
            while True:
                _, kind, box, _, _, length = struct.unpack(
                    "<HBHBHH", await reader.readexactly(10)
                )
                payload = await reader.readexactly(length)
                self.requests.append((kind, box, payload))
                if box == luci.REGISTER:
                    response = frame(box)
                elif box == luci.PLAY_STATE:
                    response = frame(box, self.state, self.state_status)
                    if self.push is not None:
                        response = frame(luci.POSITION, self.push, status=0) + response
                elif box == luci.PLAY_VIEW:
                    response = frame(box, b'{"Window CONTENTS":{"TrackName":"Track"}}')
                elif box == luci.POSITION:
                    response = self.position_reply
                elif box == luci.TRANSPORT:
                    response = self.command_reply
                    if response == b"close":
                        return
                    if response == b"split":
                        # Consume the header during the ACK wait, but complete its
                        # payload only after the client has timed out.
                        push = frame(luci.POSITION, b"42000", status=0)
                        writer.write(push[:10])
                        await writer.drain()
                        await asyncio.sleep(1.1)
                        response = push[10:]
                else:
                    self.fail(f"Unexpected LUCI box {box:#04x}")
                writer.write(response)
                await writer.drain()
        except (OSError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            self.disconnected.set()

    async def test_registration_padding_and_unknown_states(self):
        self.assertEqual((await self.client.async_read()).state, 0)
        self.assertEqual(self.requests[0], (2, luci.REGISTER, b"127.0.0.1"))
        self.assertEqual(self.requests[1], (1, luci.PLAY_STATE, b""))
        for raw, expected in [(b" 2\n", 2), (b" 5 ", 5), (b"3", 3), (b"4", 4), (b"7", 7)]:
            self.state = raw
            self.assertEqual((await self.client.async_read()).state, expected)
        self.assertEqual(self.connections, 1)
        self.state = b" \0"
        with self.assertRaisesRegex(ValueError, "Empty LUCI"):
            await self.client.async_read()

    async def test_position_push_precedes_query_and_sentinel_means_absent(self):
        self.push = b"12401\0"
        self.assertEqual((await self.client.async_read()).position, 12.401)
        self.push = b"-1000\n"
        self.assertIsNone((await self.client.async_read()).position)
        self.assertFalse(any(box == luci.POSITION for _, box, _ in self.requests))

    async def test_refused_position_is_not_queried_again_on_this_session(self):
        self.position_reply = frame(luci.POSITION, status=2)
        self.assertIsNone((await self.client.async_read()).position)
        self.assertIsNone((await self.client.async_read()).position)
        self.assertEqual(self.connections, 1)
        self.assertEqual(sum(box == luci.POSITION for _, box, _ in self.requests), 1)

    async def test_transport_refusal_surfaces_and_command_is_not_repeated(self):
        self.command_reply = frame(luci.TRANSPORT, status=2)
        with self.assertRaisesRegex(ValueError, "transport command refused"):
            await self.client.async_transport("NEXT")
        self.assertEqual(self.requests.count((2, luci.TRANSPORT, b"NEXT")), 1)

    async def test_transport_eof_surfaces_and_command_is_not_repeated(self):
        self.command_reply = b"close"
        with self.assertRaises(EOFError):
            await self.client.async_transport("NEXT")
        self.assertEqual(self.requests.count((2, luci.TRANSPORT, b"NEXT")), 1)

    async def test_transport_without_ack_does_not_lose_partial_frame(self):
        self.command_reply = b"split"
        await self.client.async_transport("RESUME")
        self.assertEqual((await self.client.async_read()).position, 42)
        self.assertEqual(self.connections, 1)
        self.assertEqual(self.requests.count((2, luci.TRANSPORT, b"RESUME")), 1)

    async def test_unexpected_reply_status_and_oversized_frame(self):
        self.state_status = 4
        with self.assertRaisesRegex(ValueError, r"status 4 for box 0x33"):
            await asyncio.wait_for(self.client.async_read(), 1)
        self.state_status = 1
        self.state = b"x" * (luci.MAX_PAYLOAD + 1)
        with self.assertRaisesRegex(ValueError, "Oversized LUCI frame"):
            await self.client.async_read()
        await asyncio.wait_for(self.disconnected.wait(), 1)

    async def test_idle_client_closes_and_can_reconnect(self):
        with patch.object(luci, "IDLE_TIMEOUT", 0.03):
            await self.client.async_read()
            await asyncio.wait_for(self.disconnected.wait(), 1)
            self.assertEqual((await self.client.async_read()).state, 0)
            self.assertEqual(self.connections, 2)

    async def test_shutdown_closes_and_prevents_reconnection(self):
        await self.client.async_read()
        await self.client.async_shutdown()
        await asyncio.wait_for(self.disconnected.wait(), 1)
        with self.assertRaisesRegex(ConnectionError, "shutting down"):
            await self.client.async_read()
        self.assertEqual(self.connections, 1)
