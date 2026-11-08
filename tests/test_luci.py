"""Exercise the LUCI client against a TCP peer without importing Home Assistant."""

import asyncio
import importlib.util
import json
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
        self.play_view = {"TrackName": "Track"}
        self.position_reply = frame(luci.POSITION, b"1000")
        self.state_status = 1
        self.register_status = 1
        self.command_reply = frame(luci.TRANSPORT)
        self.requests = []
        self.request_times = []
        self.connections = 0
        self.writer = None
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
        self.writer = writer
        try:
            while True:
                _, kind, box, _, _, length = struct.unpack(
                    "<HBHBHH", await reader.readexactly(10)
                )
                payload = await reader.readexactly(length)
                self.requests.append((kind, box, payload))
                self.request_times.append(asyncio.get_running_loop().time())
                if box == luci.REGISTER:
                    response = frame(box, status=self.register_status)
                elif box == luci.PLAY_STATE:
                    response = frame(box, self.state, self.state_status)
                    if self.push is not None:
                        response = frame(luci.POSITION, self.push, status=0) + response
                elif box == luci.PLAY_VIEW:
                    response = frame(box, json.dumps({"Window CONTENTS": self.play_view}).encode())
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

    async def test_paused_read_retains_position_push_over_stale_play_view(self):
        self.state = b"2"
        self.push = b"30000"
        self.assertEqual((await self.client.async_read()).position, 30)
        self.push = None
        self.play_view["Current_time"] = 0
        self.assertEqual((await self.client.async_read()).position, 30)
        self.assertFalse(any(box == luci.POSITION for _, box, _ in self.requests))

    async def test_playing_read_uses_play_view_over_old_position_push(self):
        self.push = b"30000"
        self.assertEqual((await self.client.async_read()).position, 30)
        self.push = None
        self.play_view["Current_time"] = 31000
        self.assertEqual((await self.client.async_read()).position, 31)

    async def test_track_notification_invalidates_paused_position(self):
        self.state = b"2"
        self.push = b"30000"
        self.assertEqual((await self.client.async_read()).position, 30)
        self.push = None
        self.play_view["Current_time"] = 0
        self.position_reply = frame(luci.POSITION, b"0")
        # A repeated track can have the same title and still start over.
        view = json.dumps({"Window CONTENTS": self.play_view}).encode()
        self.writer.write(frame(luci.PLAY_VIEW, view, 0))
        await self.writer.drain()
        self.assertEqual((await self.client.async_read()).position, 0)

    async def test_mirrored_play_view_does_not_discard_new_position(self):
        self.state = b"2"
        await self.client.async_read()
        view = b'{"Window CONTENTS":{"TrackName":"Track","Current_time":0}}'
        self.writer.write(
            frame(luci.PLAY_VIEW, view, 0)
            + frame(luci.POSITION, b"2000", 0)
            + frame(luci.PLAY_VIEW_PUSH, view, 0)
        )
        await self.writer.drain()
        self.assertEqual((await self.client.async_read()).position, 2)

    async def test_refused_position_is_not_queried_again_on_this_session(self):
        self.position_reply = frame(luci.POSITION, status=2)
        self.assertIsNone((await self.client.async_read()).position)
        self.assertIsNone((await self.client.async_read()).position)
        self.assertEqual(self.connections, 1)
        self.assertEqual(sum(box == luci.POSITION for _, box, _ in self.requests), 1)

    async def test_refused_registration_closes_socket_and_next_read_reconnects(self):
        self.register_status = 2
        with self.assertRaisesRegex(luci.LuciRefused, "box 0x03"):
            await self.client.async_transport("NEXT")
        self.assertFalse(self.client.connected)
        self.assertEqual([box for _, box, _ in self.requests], [luci.REGISTER])
        self.register_status = 1
        self.assertEqual((await self.client.async_read()).state, 0)
        self.assertEqual(self.connections, 2)

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

    async def test_transport_without_ack_reuses_push_session(self):
        self.command_reply = b""
        with patch.object(luci, "ACK_TIMEOUT", 0.03):
            await self.client.async_transport("NEXT")
            await self.client.async_read()
            await self.client.async_transport("NEXT")
        self.assertEqual(self.connections, 1)
        self.assertEqual(
            [payload for _, box, payload in self.requests if box == luci.TRANSPORT],
            [b"NEXT", b"NEXT"],
        )

    async def test_first_command_waits_after_registration(self):
        await self.client.async_transport("PLAY")
        self.assertEqual([box for _, box, _ in self.requests], [luci.REGISTER, luci.TRANSPORT])
        self.assertGreaterEqual(self.request_times[1] - self.request_times[0], 0.09)

    async def test_unexpected_reply_status_and_oversized_frame(self):
        self.state_status = 4
        with self.assertRaisesRegex(ValueError, r"status 4 for box 0x33"):
            await asyncio.wait_for(self.client.async_read(), 1)
        self.state_status = 1
        self.state = b"x" * (luci.MAX_PAYLOAD + 1)
        with self.assertRaisesRegex(ValueError, "Oversized LUCI frame"):
            await self.client.async_read()
        await asyncio.wait_for(self.disconnected.wait(), 1)

    async def test_pushes_update_paused_state_without_another_poll(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        self.assertEqual((await self.client.async_read()).state, 0)
        request_count = len(self.requests)
        self.writer.write(
            frame(luci.PLAY_STATE, b"2", 0)
            + frame(luci.PLAY_VIEW_PUSH, b'{"Window CONTENTS":{"TrackName":"Track"}}', 0)
            + frame(luci.POSITION, b"1250", 0)
        )
        await self.writer.drain()
        snapshot = await asyncio.wait_for(updates.get(), 1)
        self.assertEqual((snapshot.state, snapshot.title, snapshot.position), (2, "Track", 1.25))
        self.assertEqual(len(self.requests), request_count)

    async def test_status_one_playback_frame_without_query_is_a_push(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        self.writer.write(frame(luci.PLAY_STATE, b"2", status=1))
        await self.writer.drain()
        snapshot = await asyncio.wait_for(updates.get(), 1)
        self.assertEqual(snapshot.state, 2)

    async def test_track_gap_does_not_publish_an_idle_or_buffering_state(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        self.writer.write(frame(luci.PLAY_STATE, b"1", 0))
        await self.writer.drain()
        await asyncio.sleep(luci.PUSH_SETTLE * 2)
        self.assertTrue(updates.empty())
        self.writer.write(
            frame(luci.PLAY_STATE, b"5", 0)
            + frame(luci.PLAY_VIEW, b'{"Window CONTENTS":{"TrackName":"Next"}}', 0)
            + frame(luci.PLAY_STATE, b"0", 0)
            + frame(luci.POSITION, b"1200", 0)
        )
        await self.writer.drain()
        snapshot = await asyncio.wait_for(updates.get(), 1)
        self.assertEqual((snapshot.state, snapshot.title, snapshot.position), (0, "Next", 1.2))
        self.assertTrue(updates.empty())

    async def test_short_connecting_and_receiving_blips_keep_the_playing_snapshot(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        for raw in (b"3", b"4"):
            self.writer.write(frame(luci.PLAY_STATE, raw, 0))
            await self.writer.drain()
            await asyncio.sleep(luci.PUSH_SETTLE * 2)
            self.assertTrue(updates.empty())
            self.writer.write(frame(luci.PLAY_STATE, b"0", 0))
            await self.writer.drain()
            await asyncio.sleep(luci.PUSH_SETTLE * 2)
            self.assertTrue(updates.empty())

    async def test_sustained_connecting_keeps_known_track_details(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        with patch.object(luci, "TRACK_GAP", 0.05):
            self.writer.write(frame(luci.PLAY_STATE, b"3", 0))
            await self.writer.drain()
            snapshot = await asyncio.wait_for(updates.get(), 1)
        self.assertEqual((snapshot.state, snapshot.title), (3, "Track"))

    async def test_connecting_and_receiving_skip_play_view_and_tolerate_idle_blip(self):
        self.state = b"3"
        self.assertEqual(await self.client.async_read(), luci.Playback(3))
        self.state = b"4"
        self.assertEqual(await self.client.async_read(), luci.Playback(4))
        self.state = b"1"
        self.assertEqual(await self.client.async_read(), luci.Playback(4))
        self.assertEqual(self.connections, 1)
        self.assertEqual(
            [box for _, box, _ in self.requests],
            [luci.REGISTER, luci.PLAY_STATE, luci.PLAY_STATE, luci.PLAY_STATE],
        )

    async def test_resync_during_track_gap_does_not_request_idle_metadata(self):
        await self.client.async_read()
        start = len(self.requests)
        self.state = b"1"
        snapshot = await self.client.async_read()
        self.assertEqual((snapshot.state, snapshot.title), (0, "Track"))
        self.assertEqual(self.requests[start:], [(1, luci.PLAY_STATE, b"")])

    async def test_stopped_state_clears_metadata_with_speaker_confirmation(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        self.writer.write(
            frame(luci.PLAY_STATE, b"1", 0)
            + frame(luci.SPEAKER, b"SPEAKER_INACTIVE,4", 0)
        )
        await self.writer.drain()
        snapshot = await asyncio.wait_for(updates.get(), 1)
        self.assertEqual(snapshot, luci.Playback(1))

    async def test_stopped_state_without_confirmation_is_still_published(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        self.writer.write(frame(luci.PLAY_STATE, b"1", 0))
        await self.writer.drain()
        self.assertEqual(await asyncio.wait_for(updates.get(), 3), luci.Playback(1))

    async def test_unexpected_reader_failure_disconnects_and_notifies(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        with self.assertLogs(luci.__name__, "WARNING"), patch.object(
            luci, "_playback", side_effect=RuntimeError("boom")
        ):
            self.writer.write(frame(luci.PLAY_VIEW, b"{}", 0))
            await self.writer.drain()
            error = await asyncio.wait_for(updates.get(), 1)
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(str(error), "boom")
        self.assertFalse(self.client.connected)
        self.assertEqual((await self.client.async_read()).state, 0)
        self.assertEqual(self.connections, 2)

    async def test_disconnect_notifies_and_next_read_opens_new_session(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        self.writer.close()
        self.assertIsInstance(await asyncio.wait_for(updates.get(), 1), EOFError)
        self.assertEqual((await self.client.async_read()).state, 0)
        self.assertEqual(self.connections, 2)

    async def test_short_disconnect_retains_track_gap_filter(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        self.play_view["TrackName"] = "A"
        await self.client.async_read()
        self.writer.close()
        self.assertIsInstance(await asyncio.wait_for(updates.get(), 1), EOFError)

        self.state = b"1"
        snapshot = await self.client.async_read()
        self.assertEqual((snapshot.state, snapshot.title), (0, "A"))
        self.writer.write(frame(luci.PLAY_STATE, b"1", 0) + frame(luci.PLAY_STATE, b"5", 0))
        await self.writer.drain()
        await asyncio.sleep(luci.PUSH_SETTLE * 2)
        self.assertTrue(updates.empty())

        self.writer.write(
            frame(luci.PLAY_VIEW, b'{"Window CONTENTS":{"TrackName":"B"}}', 0)
            + frame(luci.PLAY_STATE, b"0", 0)
        )
        await self.writer.drain()
        snapshot = await asyncio.wait_for(updates.get(), 1)
        self.assertEqual((snapshot.state, snapshot.title), (0, "B"))
        self.assertTrue(updates.empty())

    async def test_long_disconnect_discards_previous_track(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        self.writer.close()
        self.assertIsInstance(await asyncio.wait_for(updates.get(), 1), EOFError)
        self.state = b"1"
        with patch.object(luci, "STATE_KEEP_SECONDS", 0.05):
            await asyncio.sleep(0.07)
            self.assertEqual(await self.client.async_read(), luci.Playback(1))
        self.assertEqual(self.connections, 2)

    async def test_refused_registration_does_not_extend_cached_playback(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        await self.client.async_read()
        self.writer.close()
        self.assertIsInstance(await asyncio.wait_for(updates.get(), 1), EOFError)
        with patch.object(luci, "STATE_KEEP_SECONDS", 0.3):
            await asyncio.sleep(0.17)
            self.register_status = 2
            with self.assertRaises(luci.LuciRefused):
                await self.client.async_read()
            await asyncio.sleep(0.17)
            self.register_status = 1
            self.state = b"1"
            self.assertEqual(await self.client.async_read(), luci.Playback(1))
        self.assertEqual(self.connections, 3)

    async def test_watchdog_detects_silent_playing_session(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        self.push = b"1000"
        with patch.object(luci, "PUSH_SILENCE_LIMIT", 0.1):
            self.assertEqual((await self.client.async_read()).state, 0)
            self.assertIsInstance(await asyncio.wait_for(updates.get(), 1), luci.LuciSessionStale)
        await asyncio.wait_for(self.disconnected.wait(), 1)
        self.assertFalse(self.client.connected)
        with self.assertRaises(luci.LuciSessionStale):
            await self.client.async_read()
        self.assertEqual(self.connections, 1)

    async def test_watchdog_only_checks_playing_after_a_position_push(self):
        updates = asyncio.Queue()
        self.client.subscribe(updates.put_nowait)
        with patch.object(luci, "PUSH_SILENCE_LIMIT", 0.1):
            self.assertEqual((await self.client.async_read()).state, 0)
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(updates.get(), 0.15)

            self.state = b"2"
            self.push = b"1000"
            self.assertEqual((await self.client.async_read()).state, 2)
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(updates.get(), 0.15)

            self.writer.close()
            self.assertIsInstance(await asyncio.wait_for(updates.get(), 1), EOFError)
            self.state = b"0"
            self.push = None
            self.assertEqual((await self.client.async_read()).state, 0)
            self.assertIsInstance(await asyncio.wait_for(updates.get(), 1), luci.LuciSessionStale)
        self.assertEqual(self.connections, 2)

    async def test_shutdown_closes_and_prevents_reconnection(self):
        await self.client.async_read()
        await self.client.async_shutdown()
        await asyncio.wait_for(self.disconnected.wait(), 1)
        with self.assertRaisesRegex(ConnectionError, "shutting down"):
            await self.client.async_read()
        self.assertEqual(self.connections, 1)
