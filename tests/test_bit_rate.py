"""UPnP reports bytes per second for PCM/FLAC; the attribute is bits per second."""

import importlib.util
import sys
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "custom_components/primare/luci.py"
_spec = importlib.util.spec_from_file_location("primare_luci_bitrate", _PATH)
luci = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = luci
_spec.loader.exec_module(luci)


class BitRateTest(unittest.TestCase):
    def test_upnp_bytes_become_bits(self):
        view = {"BitRate": 176400, "SampleRate": 44100, "BitDepth": 16}
        self.assertEqual(luci._bit_rate(view), 1411200)

    def test_real_bit_rate_unchanged(self):
        self.assertEqual(luci._bit_rate({"BitRate": 320000, "SampleRate": 44100, "BitDepth": 16}), 320000)

    def test_without_format_unchanged(self):
        self.assertEqual(luci._bit_rate({"BitRate": 176400}), 176400)

    def test_missing(self):
        self.assertIsNone(luci._bit_rate({}))


if __name__ == "__main__":
    unittest.main()
