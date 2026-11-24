"""Device profiles per type – capabilities and fixed-volume source."""

import importlib.util
import pathlib
import sys
import unittest

_PATH = pathlib.Path(__file__).parents[1] / "custom_components/primare/const.py"
_spec = importlib.util.spec_from_file_location("primare_const", _PATH)
const = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = const  # dataclasses look the module up
_spec.loader.exec_module(const)


def _profile(device_type, inputs=None):
    return const.DeviceProfile(device_type, inputs or {})


class ProfileTest(unittest.TestCase):
    def test_multichannel(self):
        p = _profile(const.TYPE_MULTICHANNEL, {1: "A"})
        self.assertTrue(p.has_mute)
        self.assertTrue(p.has_input)
        self.assertTrue(p.has_dsp)
        self.assertIsNone(p.fixed_source)
        self.assertEqual(p.stream_input, 17)

    def test_stereo(self):
        p = _profile(const.TYPE_STEREO, {1: "A"})
        self.assertTrue(p.has_mute)
        self.assertTrue(p.has_input)
        self.assertFalse(p.has_dsp)
        self.assertEqual(p.fixed_source, "input")
        self.assertEqual(p.stream_input, 13)

    def test_streamer(self):
        p = _profile(const.TYPE_STREAMER)
        self.assertFalse(p.has_mute)
        self.assertFalse(p.has_input)
        self.assertFalse(p.has_dsp)
        self.assertEqual(p.fixed_source, "output")
        self.assertIsNone(p.stream_input)

    def test_cd_behaves_like_streamer(self):
        # CD15 / CD35 (untested): assumed to behave like the network player.
        p = _profile(const.TYPE_CD, {1: "A"})  # even given inputs: none exposed
        self.assertFalse(p.has_mute)
        self.assertFalse(p.has_input)
        self.assertFalse(p.has_dsp)
        self.assertEqual(p.fixed_source, "output")
        self.assertIsNone(p.stream_input)
        self.assertEqual(p.model, "CD player")

    def test_cd_is_a_device_type(self):
        self.assertIn(const.TYPE_CD, const.DEVICE_TYPES)


if __name__ == "__main__":
    unittest.main()
