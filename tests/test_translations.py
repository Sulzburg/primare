"""Every entity name exists in German and English, and nothing is left hard-coded."""

import json
import re
import unittest
from pathlib import Path

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

    def test_exception_keys_in_both_languages(self):
        # Every translation_key raised in the code must have a German and English message.
        tkey = re.compile(r'(?<!_attr_)translation_key="([a-z_]+)"')
        keys = set()
        for path in _DIR.glob("*.py"):
            keys |= set(tkey.findall(path.read_text(encoding="utf-8")))
        self.assertGreaterEqual(len(keys), 8)
        for lang in ("de", "en"):
            exc = json.loads((_DIR / f"translations/{lang}.json").read_text(encoding="utf-8")).get("exceptions", {})
            for key in keys:
                self.assertIn(key, exc, f"{lang}: exceptions.{key}")
                self.assertTrue(exc[key]["message"], f"{lang}: exceptions.{key}")

    def test_no_hard_coded_error_messages(self):
        # Service/validation errors must go through translation_key, not a literal string.
        literal = re.compile(r'raise (?:ServiceValidationError|HomeAssistantError)\(\s*f?"')
        for path in _DIR.glob("*.py"):
            self.assertNotRegex(path.read_text(encoding="utf-8"), literal, path.name)

    def test_services_in_both_languages(self):
        de = json.loads((_DIR / "translations/de.json").read_text(encoding="utf-8")).get("services", {})
        en = json.loads((_DIR / "translations/en.json").read_text(encoding="utf-8")).get("services", {})
        self.assertEqual(set(de), set(en))
        self.assertGreaterEqual(len(de), 4)
        for name, svc in de.items():
            self.assertTrue(svc.get("name") and svc.get("description"), f"de: {name}")
            self.assertEqual(set(svc.get("fields", {})), set(en[name].get("fields", {})), name)
            for fn, f in svc.get("fields", {}).items():
                self.assertTrue(f.get("name") and f.get("description"), f"de: {name}.{fn}")


if __name__ == "__main__":
    unittest.main()
