"""Firmware line on the device page, as in the Prisma app."""

import ast
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).parents[1] / "custom_components/primare/playback.py"


def _load():
    tree = ast.parse(SOURCE.read_text())
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "format_firmware")
    namespace = {}
    exec(compile(ast.Module([func], []), str(SOURCE), "exec"), namespace)
    return namespace["format_firmware"]


format_firmware = _load()


class FormatFirmwareTest(unittest.TestCase):
    def test_full(self):
        self.assertEqual(format_firmware("315", "15644", "1.52.272222"), "3.15 (Streaming 15644 · Cast 1.52)")

    def test_without_cast(self):
        self.assertEqual(format_firmware("170", "15645"), "1.70 (Streaming 15645)")

    def test_only_streaming(self):
        self.assertEqual(format_firmware(None, "15644"), "Streaming 15644")

    def test_nothing(self):
        self.assertIsNone(format_firmware(None, None, None))


if __name__ == "__main__":
    unittest.main()
