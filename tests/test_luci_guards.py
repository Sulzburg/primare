"""Guards added in 2.2.2: unknown skip flags and stale position counters."""

import asyncio
import importlib.util
from pathlib import Path
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
