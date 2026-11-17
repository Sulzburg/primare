"""Default input names: the device's factory names, valid for the options form."""

import importlib.util
import pathlib
import sys
import unittest

_PATH = pathlib.Path(__file__).parents[1] / "custom_components/primare/const.py"
_spec = importlib.util.spec_from_file_location("primare_const", _PATH)
const = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = const  # dataclasses look the module up
_spec.loader.exec_module(const)


class DefaultInputsTest(unittest.TestCase):
    def test_multichannel_is_sp25_factory_list(self):
        inputs = const.DEFAULT_INPUTS[const.TYPE_MULTICHANNEL]
        self.assertEqual(inputs[1], "Preset 1")
        self.assertEqual(inputs[15], "Preset 15")
        self.assertEqual(inputs[16], "PC/MAC")
        self.assertEqual(inputs[17], "Stream")
        self.assertEqual(len(inputs), 17)

    def test_stereo_is_pre35_factory_list(self):
        inputs = const.DEFAULT_INPUTS[const.TYPE_STEREO]
        self.assertEqual(
            [inputs[n] for n in range(1, 14)],
            ["A1", "A2", "A3", "A4", "A5", "D6", "D7", "D8", "D9", "D10", "D11", "PC/MAC", "Stream"],
        )

    def test_defaults_survive_the_options_form(self):
        for inputs in const.DEFAULT_INPUTS.values():
            self.assertEqual(const.parse_inputs(const.format_inputs(inputs)), inputs)


if __name__ == "__main__":
    unittest.main()
