"""The combined media player (3.0): amplifier and streamer in one entity."""

import asyncio
from datetime import UTC, datetime, timedelta
import unittest
from unittest import mock

from ha_stub import install

install()

from custom_components.primare.const import (  # noqa: E402
    DEFAULT_INPUTS,
    TYPE_MULTICHANNEL,
    TYPE_STEREO,
    TYPE_STREAMER,
    DeviceProfile,
)
from custom_components.primare import media_player as mp  # noqa: E402
from custom_components.primare.luci import Playback  # noqa: E402
from custom_components.primare.media_player import PrimareMediaPlayer  # noqa: E402
from custom_components.primare.playback import format_firmware  # noqa: E402
from ha_stub import MediaPlayerEntityFeature as F, MediaPlayerState as S  # noqa: E402

PRE35_INPUTS = {1: "R35", 3: "SP25", 6: "TV", 10: "NP5", 12: "PC/MAC", 13: "Prisma"}


class FakeClient:
    def __init__(self, power=True, input=13, volume=20, mute=False, dsp=None):
        self.power, self.input, self.volume, self.mute, self.dsp = power, input, volume, mute, dsp
        self.connected = True
        self.sent = []

    def add_listener(self, listener):
        return lambda: None

    async def set_power(self, on):
        self.sent.append(("power", on))


class FakeStreamer:
    def __init__(self, playback=None):
        self.playback = playback
        self.invalidated = 0
        self.commands = []

    def add_listener(self, listener):
        return lambda: None

    def async_invalidate(self):
        self.invalidated += 1

    async def async_transport(self, command, position=None):
        self.commands.append(command)


class FakeRuntime:
    def __init__(self, client, profile):
        self.client, self.profile, self.model = client, profile, None


class FakeEntry:
    entry_id = "abc"
    title = "Pre35"

    def __init__(self, client, profile):
        self.runtime_data = FakeRuntime(client, profile)


def player(device_type=TYPE_STEREO, inputs=PRE35_INPUTS, playback=None, **client):
    c = FakeClient(**client)
    s = FakeStreamer(playback)
    p = PrimareMediaPlayer(FakeEntry(c, DeviceProfile(device_type, inputs)), s)
    p._refresh()
    return p, c, s


PLAYING = Playback(state=0, title="China Blue", artist="Yello", album="Time Lab",
                   duration=218, position=110, sample_rate_hz=48000, bit_depth=24, source_id=27)


class StateTest(unittest.TestCase):
    def test_off(self):
        p, _, _ = player(power=False, playback=PLAYING)
        self.assertEqual(p.state, S.OFF)
        self.assertIsNone(p.media_title if hasattr(p, "media_title") else p._attr_media_title)

    def test_unknown_until_first_answer(self):
        p, _, _ = player(power=None)
        self.assertIsNone(p.state)

    def test_other_input_shows_input_name(self):
        p, _, _ = player(input=1, playback=PLAYING)
        self.assertEqual(p.state, S.ON)
        self.assertEqual(p._attr_media_title, "R35")
        self.assertIsNone(p._attr_media_artist)
        self.assertEqual(p._attr_extra_state_attributes, {})

    def test_streamer_playing(self):
        p, _, _ = player(input=13, playback=PLAYING)
        self.assertEqual(p.state, S.PLAYING)
        self.assertEqual((p._attr_media_title, p._attr_media_artist), ("China Blue", "Yello"))
        self.assertEqual(p._attr_app_name, "Roon")
        self.assertEqual(p._attr_extra_state_attributes["sample_rate_hz"], 48000)
        self.assertEqual(p._attr_media_position, 110)

    def test_streamer_idle_shows_input_name(self):
        p, _, _ = player(input=13, playback=Playback(state=1))
        self.assertEqual(p.state, S.IDLE)
        self.assertEqual(p._attr_media_title, "Prisma")

    def test_streamer_unreadable_stays_on(self):
        p, _, _ = player(input=13, playback=None)
        self.assertEqual(p.state, S.ON)

    def test_paused(self):
        p, _, _ = player(input=13, playback=Playback(state=2, title="X"))
        self.assertEqual(p.state, S.PAUSED)

    def test_sp25_streamer_is_17(self):
        p, _, _ = player(TYPE_MULTICHANNEL, DEFAULT_INPUTS[TYPE_MULTICHANNEL], input=17, playback=PLAYING, dsp=1)
        self.assertEqual(p.state, S.PLAYING)
        p, _, _ = player(TYPE_MULTICHANNEL, DEFAULT_INPUTS[TYPE_MULTICHANNEL], input=13, playback=PLAYING, dsp=1)
        self.assertEqual(p.state, S.ON)
        self.assertEqual(p._attr_media_title, "Preset 13")

    def test_np5_always_streams(self):
        p, _, _ = player(TYPE_STREAMER, {}, input=None, playback=PLAYING)
        self.assertEqual(p.state, S.PLAYING)
        self.assertEqual(p._attr_media_title, "China Blue")

    def test_stale_position_hidden(self):
        p, _, _ = player(playback=Playback(state=0, title="X", duration=200, position=39821))
        self.assertIsNone(p._attr_media_position)


class FeatureTest(unittest.TestCase):
    def test_play_offered_on_every_input(self):
        p, _, _ = player(input=1)
        for feature in (F.PLAY, F.PAUSE, F.STOP, F.NEXT_TRACK, F.PREVIOUS_TRACK):
            self.assertTrue(p._attr_supported_features & feature, feature)
        self.assertFalse(p._attr_supported_features & F.SEEK)

    def test_amplifier_features(self):
        p, _, _ = player()
        for feature in (F.TURN_ON, F.TURN_OFF, F.VOLUME_SET, F.VOLUME_MUTE, F.SELECT_SOURCE):
            self.assertTrue(p._attr_supported_features & feature, feature)
        self.assertFalse(p._attr_supported_features & F.SELECT_SOUND_MODE)

    def test_np5_has_no_mute_or_input(self):
        p, _, _ = player(TYPE_STREAMER, {}, input=None)
        self.assertFalse(p._attr_supported_features & F.VOLUME_MUTE)
        self.assertFalse(p._attr_supported_features & F.SELECT_SOURCE)

    def test_device_refusing_next_and_allowing_seek(self):
        p, _, _ = player(playback=Playback(state=0, title="X", duration=200, can_next=False, can_seek=True))
        self.assertFalse(p._attr_supported_features & F.NEXT_TRACK)
        self.assertTrue(p._attr_supported_features & F.PREVIOUS_TRACK)
        self.assertTrue(p._attr_supported_features & F.SEEK)


class TransitionTest(unittest.TestCase):
    def test_switching_to_streamer_forgets_old_track(self):
        p, c, s = player(input=1, playback=PLAYING)
        p._handle_update()  # remembers: not streaming
        c.input = 13
        p._handle_update()
        self.assertEqual(s.invalidated, 1)

    def test_waking_up_forgets_old_track(self):
        p, c, s = player(power=False, playback=PLAYING)
        p._handle_update()
        c.power = True
        p._handle_update()
        self.assertEqual(s.invalidated, 1)

    def test_volume_change_does_not_invalidate(self):
        p, c, s = player(input=13, playback=PLAYING)
        p._handle_update()
        c.volume = 30
        p._handle_update()
        self.assertEqual(s.invalidated, 0)


class CommandTest(unittest.TestCase):
    def test_play_goes_to_streamer_even_on_other_input(self):
        p, _, s = player(input=1)
        asyncio.run(p.async_media_play())
        self.assertEqual(s.commands, ["PLAY"])

    def test_play_when_paused_resumes(self):
        p, _, s = player(playback=Playback(state=2, title="X"))
        asyncio.run(p.async_media_play())
        self.assertEqual(s.commands, ["RESUME"])


class PositionTest(unittest.TestCase):
    """An amplifier change must not throw the shown position back (found by yvos)."""

    def test_volume_change_keeps_position(self):
        t0 = datetime(2026, 11, 18, 10, 0, tzinfo=UTC)
        now = [t0]
        with mock.patch.object(mp.dt_util, "utcnow", lambda: now[0], create=True):
            p, c, _ = player(input=13, playback=PLAYING)

            def shown():
                return p._attr_media_position + (now[0] - p._attr_media_position_updated_at).total_seconds()

            now[0] = t0 + timedelta(seconds=40)
            for change in ("volume", "mute", "dsp"):
                setattr(c, change, 30 if change == "volume" else True)
                p._handle_update()
                self.assertEqual(shown(), 150, change)

    def test_new_streamer_data_updates_position(self):
        p, _, s = player(input=13, playback=PLAYING)
        s.playback = Playback(state=0, title="China Blue", duration=218, position=170)
        p._handle_streamer_update()
        self.assertEqual(p._attr_media_position, 170)


class SeekTest(unittest.TestCase):
    def test_seek_offered_when_device_says_nothing(self):
        p, _, _ = player(playback=Playback(state=0, title="X", duration=200))
        self.assertTrue(p._attr_supported_features & F.SEEK)

    def test_no_seek_without_track_length(self):
        p, _, _ = player(playback=Playback(state=0, title="X"))
        self.assertFalse(p._attr_supported_features & F.SEEK)

    def test_no_seek_when_device_refuses(self):
        p, _, _ = player(playback=Playback(state=0, title="X", duration=200, can_seek=False))
        self.assertFalse(p._attr_supported_features & F.SEEK)

    def test_seek_sends_position(self):
        p, _, s = player(playback=Playback(state=0, title="X", duration=200))
        asyncio.run(p.async_media_seek(42))
        self.assertEqual(s.commands, ["SEEK"])


class NamingTest(unittest.TestCase):
    def test_player_is_named_like_the_device(self):
        self.assertIsNone(PrimareMediaPlayer._attr_name)

    def test_firmware_line(self):
        self.assertEqual(format_firmware("315", "15644", "1.52.272222"), "3.15 (Streaming 15644 · Cast 1.52)")


if __name__ == "__main__":
    unittest.main()
