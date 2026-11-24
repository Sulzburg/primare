"""Static checks on the Home Assistant modules (which cannot be imported here).

Catches e.g. a helper function accidentally placed inside a class, which cuts
the class in two: the methods after it silently stop belonging to the class.
"""

import ast
import unittest
from pathlib import Path

_DIR = Path(__file__).resolve().parents[1] / "custom_components/primare"
# Private helpers that Home Assistant's own base classes provide
_HA_BASE_METHODS = {"_async_abort_entries_match", "_get_reconfigure_entry", "_async_handle_step"}


def _private_calls_missing(cls: ast.ClassDef) -> set[str]:
    defined = {
        node.name for node in cls.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assigned, used = set(), set()
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
            and node.attr.startswith("_")
            and not node.attr.startswith("__")
        ):
            if isinstance(node.ctx, ast.Store):
                assigned.add(node.attr)
            else:
                used.add(node.attr)
    # private names read but neither assigned nor defined, and not HA's _attr_* fields
    return {
        name
        for name in used - assigned - defined - _HA_BASE_METHODS
        if not name.startswith("_attr_") and name.startswith(("_handle", "_async", "_apply", "_schedule", "_cancel", "_update", "_features", "_power", "_send"))
    }


class StructureTest(unittest.TestCase):
    def test_classes_define_the_private_methods_they_call(self):
        problems = {}
        for path in sorted(_DIR.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    # methods may live in a base class of the same package
                    bases = [b.id for b in node.bases if isinstance(b, ast.Name)]
                    missing = _private_calls_missing(node)
                    for base in bases:
                        for other in tree.body:
                            if isinstance(other, ast.ClassDef) and other.name == base:
                                missing -= {
                                    n.name for n in other.body
                                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                                }
                    if "PrimareEntity" in bases:
                        missing -= {"_send", "_handle_update"}
                    if missing:
                        problems[f"{path.name}:{node.name}"] = sorted(missing)
        self.assertEqual(problems, {})

    def test_no_module_level_function_between_methods(self):
        for path in sorted(_DIR.glob("*.py")):
            lines = path.read_text(encoding="utf-8").splitlines()
            # parsing is the real check: methods after a stray def would be nested
            tree = ast.parse("\n".join(lines))
            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    nested = [
                        n.name for n in node.body
                        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and n.args.args and n.args.args[0].arg == "self"
                    ]
                    self.assertEqual(nested, [], f"{path.name}: methods nested in {node.name}()")


if __name__ == "__main__":
    unittest.main()
