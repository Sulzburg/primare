"""Every entity name exists in German and English, and nothing is left hard-coded."""

import json
from pathlib import Path
import re
import unittest

_DIR = Path(__file__).resolve().parents[1] / "custom_components/primare"
_KEY = re.compile(r'_attr_translation_key = "([a-z_]+)"')


def _keys_in_code():
    keys = {}
    for path in _DIR.glob("*.py"):
        for key in _KEY.findall(path.read_text(encoding="utf-8")):
            keys[key] = path.stem
    return keys


class TranslationTest(unittest.TestCase):
    def test_every_key_in_both_languages(self):
        keys = _keys_in_code()
        self.assertGreaterEqual(len(keys), 10)
        for lang in ("de", "en"):
            entity = json.loads((_DIR / f"translations/{lang}.json").read_text(encoding="utf-8"))["entity"]
            for key, platform in keys.items():
                self.assertIn(key, entity.get(platform, {}), f"{lang}: {platform}.{key}")
                self.assertTrue(entity[platform][key]["name"])

    def test_device_types_in_both_languages(self):
        const = (_DIR / "const.py").read_text(encoding="utf-8")
        types = re.findall(r'^TYPE_[A-Z]+ = "([^"]+)"', const, re.MULTILINE)
        self.assertEqual(len(types), 3)
        for lang in ("de", "en"):
            selector = json.loads((_DIR / f"translations/{lang}.json").read_text(encoding="utf-8"))["selector"]
            options = selector["device_type"]["options"]
            self.assertEqual(set(options), {t.lower() for t in types}, lang)
            self.assertTrue(all(options.values()), lang)

    def test_no_hard_coded_names(self):
        for path in _DIR.glob("*.py"):
            for match in re.finditer(r'_attr_name = (.+)', path.read_text(encoding="utf-8")):
                self.assertEqual(match.group(1).strip(), "None", f"{path.name}: {match.group(0)}")

    def test_german_names(self):
        de = json.loads((_DIR / "translations/de.json").read_text(encoding="utf-8"))["entity"]
        self.assertEqual(de["switch"]["power"]["name"], "Ein/Aus")
        self.assertEqual(de["button"]["volume_up"]["name"], "Lauter")


if __name__ == "__main__":
    unittest.main()
