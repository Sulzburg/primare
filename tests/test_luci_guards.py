"""Guards added in 2.2.2: unknown skip flags and stale position counters."""

import asyncio
import importlib.util
import sys
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "custom_components/primare/luci.py"
_SPEC = importlib.util.spec_from_file_location("primare_test_luci_guards", _PATH)
luci = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = luci
_SPEC.loader.exec_module(luci)


class FlagTest(unittest.TestCase):
    def test_missing_flags_are_unknown(self):
        playback = luci._playback(b'{"Window CONTENTS":{"TrackName":"A"}}', 0)
        self.assertEqual((playback.can_next, playback.can_previous, playback.can_seek), (None, None, None))

    def test_explicit_flags_are_kept(self):
        playback = luci._playback(
            b'{"Window CONTENTS":{"TrackName":"A","Next":false,"Prev":true,"Seek":true}}', 0
        )
        self.assertEqual((playback.can_next, playback.can_previous, playback.can_seek), (False, True, True))

    def test_non_boolean_flags_are_unknown(self):
        playback = luci._playback(b'{"Window CONTENTS":{"TrackName":"A","Next":"true"}}', 0)
        self.assertIsNone(playback.can_next)


def _view(cover, title="Dreadlock Holiday", artist="10cc"):
    import json
    return json.dumps({"Window CONTENTS": {
        "TrackName": title, "Artist": artist, "Album": "Greatest Hits", "CoverArtUrl": cover,
    }}).encode()


class CoverTest(unittest.TestCase):
    """Pre35 with Roon, 18.11.2026: CoverArtUrl is just "coverart.jpg"."""

    def test_file_name_becomes_device_address(self):
        url = luci._playback(_view("coverart.jpg"), 0, "192.168.0.30").cover_art_url
        self.assertTrue(url.startswith("http://192.168.0.30/coverart.jpg?track="), url)

    def test_new_track_gets_new_address(self):
        first = luci._playback(_view("coverart.jpg"), 0, "192.168.0.30").cover_art_url
        same = luci._playback(_view("coverart.jpg"), 0, "192.168.0.30").cover_art_url
        other = luci._playback(_view("coverart.jpg", title="Oxygène, Pt. 4"), 0, "192.168.0.30").cover_art_url
        self.assertEqual(first, same)
        self.assertNotEqual(first, other)

    def test_placeholder_is_no_cover(self):
        self.assertIsNone(luci._playback(_view("defaultArt.jpg"), 0, "192.168.0.30").cover_art_url)

    def test_unsafe_names_are_dropped(self):
        for name in ("../etc/passwd", "a/b.jpg", "x.jpg?y=1", "cover.exe", "c over.jpg", "//evil/x.jpg",
                     "javascript:x.jpg", "ftp://h/x.jpg"):
            self.assertIsNone(luci._playback(_view(name), 0, "192.168.0.30").cover_art_url, name)

    def test_full_addresses_stay_as_they_are(self):
        url = "http://192.168.0.28:9790/minimserver/x.jpg"
        self.assertEqual(luci._playback(_view(url), 0, "192.168.0.30").cover_art_url, url)

    def test_without_host_a_file_name_is_dropped(self):
        self.assertIsNone(luci._playback(_view("coverart.jpg"), 0).cover_art_url)


class StalePositionTest(unittest.IsolatedAsyncioTestCase):
    async def test_position_beyond_track_length_is_ignored(self):
        client = luci.LuciPlaybackClient("127.0.0.1")
        self.addAsyncCleanup(client.async_shutdown)
        client._apply_frame(
            luci.PLAY_VIEW,
            b'{"Window CONTENTS":{"TrackName":"Saturday Morning","TotalTime":194000}}',
            pushed=True,
        )
        client._state = 0
        seen = []
        for real, stale in ((172000, 39820000), (173000, 39821000)):
            client._apply_frame(luci.POSITION, str(real).encode(), pushed=True)
            seen.append(client._current_position(asyncio.get_running_loop().time()))
            client._apply_frame(luci.POSITION, str(stale).encode(), pushed=True)
            seen.append(client._current_position(asyncio.get_running_loop().time()))
        self.assertEqual(seen, [172.0, 172.0, 173.0, 173.0])


def device_frame(box, payload=b"", status=1, kind=2):
    import struct
    return struct.pack(">HBHBHH", 0, kind, box, status, 0, len(payload)) + payload


class DeviceInfoTest(unittest.IsolatedAsyncioTestCase):
    """Firmware and source as the other LUCI projects document them."""

    async def asyncSetUp(self):
        import struct

        self.requests = []
        self.answers = {
            luci.FIRMWARE: b"15644",
            luci.HOST_FIRMWARE: b"315",
            luci.SOURCE: b"27",
            luci.CAST_VERSION: b"1.52.272222",
        }
        self.refuse = set()
        self.writers = []

        async def peer(reader, writer):
            self.writers.append(writer)
            try:
                while True:
                    header = await reader.readexactly(10)
                    _, kind, box, _, _, length = struct.unpack("<HBHBHH", header)
                    payload = await reader.readexactly(length)
                    self.requests.append((kind, box, payload))
                    if box == luci.REGISTER:
                        writer.write(device_frame(box))
                    elif box in self.refuse:
                        writer.write(device_frame(box, status=2))
                    elif box in self.answers:
                        writer.write(device_frame(box, self.answers[box]))
                    await writer.drain()
            except (asyncio.IncompleteReadError, OSError):
                pass

        self.server = await asyncio.start_server(peer, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.client = luci.LuciPlaybackClient("127.0.0.1", port)
        self.addAsyncCleanup(self.cleanup)

    async def cleanup(self):
        await self.client.async_shutdown()
        self.server.close()
        for writer in self.writers:
            writer.close()

    async def test_reads_firmware_and_source(self):
        info = await self.client.async_read_device_info()
        self.assertEqual(
            info,
            {"firmware": "15644", "host_firmware": "315", "cast": "1.52.272222", "source_id": 27},
        )
        self.assertTrue(all(kind == 1 for kind, box, _ in self.requests if box != luci.REGISTER))

    async def test_refused_or_silent_boxes_are_skipped(self):
        self.refuse.add(luci.SOURCE)
        del self.answers[luci.HOST_FIRMWARE]
        del self.answers[luci.CAST_VERSION]
        info = await self.client.async_read_device_info()
        self.assertEqual(info, {"firmware": "15644"})

    async def test_source_push_reaches_the_snapshot(self):
        seen = []
        self.client.subscribe(seen.append)
        await self.client.async_read_device_info()
        self.writers[0].write(device_frame(luci.PLAY_STATE, b"0", status=0))
        self.writers[0].write(device_frame(luci.SOURCE, b"22", status=0))
        await self.writers[0].drain()
        async with asyncio.timeout(3):
            while not any(getattr(s, "source_id", None) == 22 for s in seen):
                await asyncio.sleep(0.05)
        self.assertEqual(luci.SOURCES[22], "Tidal")


if __name__ == "__main__":
    unittest.main()
