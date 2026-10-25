"""2.9.100: release discipline and code health, checked on every push (Linux and Windows)."""
import re
import unittest
from pathlib import Path

import release_check

from tests import ROOT  # 2.9.117: the repository folder


def ALL_FILES():
    """The program and its tests (2.9.117: they are in nanza/... and tests/)."""
    return [*__import__("nanza_paths").program_files(), *sorted((ROOT / "tests").glob("*.py"))]


# Code-health ratchet: these numbers may only go DOWN. Lower them when screens are tidied.
MAX_LINES_OVER_200 = 106  # 2.9.102: 505 -> 106
STAR_IMPORT_FILES = set()  # 2.9.102: none left (there were 26)
MAX_BROAD_EXCEPTS = 679  # 2.9.119: 733 -> 679 (money paths catch the specific errors) - may only go down


class ReleaseCheckTest(unittest.TestCase):
    def test_repository_is_ready_to_release(self):
        self.assertEqual(release_check.problems(), [])

    def test_long_lines_do_not_grow(self):
        count = sum(1 for f in ALL_FILES() for line in f.read_text(encoding="utf-8").splitlines() if len(line) > 200)
        self.assertLessEqual(count, MAX_LINES_OVER_200, "new lines longer than 200 characters - split them")

    def test_no_new_star_imports(self):
        found = {f.name for f in ALL_FILES() if re.search(r"^from \S+ import \*", f.read_text(encoding="utf-8"), re.M)}
        self.assertEqual(found - STAR_IMPORT_FILES, set(), "new 'from x import *' - import the names you use")


class ErrorHandlingTest(unittest.TestCase):
    """2.9.105: errors are not hidden."""

    def program_files(self):
        return [f for f in __import__("nanza_paths").program_files() if not f.name.startswith("test_")]

    def test_no_silent_except_pass(self):
        silent = [f"{f.name}:{n}" for f in self.program_files() for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
                  if re.search(r"except( Exception)?:\s*pass\s*$", line)]
        self.assertEqual(silent, [], "log the error instead of 'except: pass'")

    def test_broad_excepts_do_not_grow(self):
        count = sum(len(re.findall(r"except Exception( as \w+)?:", f.read_text(encoding="utf-8"))) for f in self.program_files())
        self.assertLessEqual(count, MAX_BROAD_EXCEPTS, "catch the specific error (ValueError, OSError...) instead of Exception")

    def test_unexpected_server_errors_are_logged(self):
        import server
        with self.assertLogs("saber.server", "ERROR") as logged:
            try: raise TypeError("a bug")
            except TypeError: server._log_unexpected("/api/x", 400)
        self.assertIn("Unexpected error", logged.output[0])
        try: raise ValueError("Enter a valid date")  # a refusal the user caused: answered, not logged as an error
        except ValueError:
            import logging
            with self.assertRaises(AssertionError):
                with self.assertLogs("saber.server", logging.ERROR): server._log_unexpected("/api/x", 400)


if __name__ == "__main__":
    unittest.main()


class DocumentedAssetsLinkTest(unittest.TestCase):
    """2.9.136 (F3): AI_RULES.md tells Linux users to make the link `assets -> Assets`; a copy without git must not fail on
    that one link, while any other link (or the same name pointing elsewhere) and cache files still fail."""

    def _copy(self, folder):
        import os
        root = Path(folder)
        (root / "Assets").mkdir(); (root / "Assets" / "logo.txt").write_text("x", encoding="utf-8")
        (root / "main.py").write_text("x = 1\n", encoding="utf-8")
        return root, os

    def test_documented_link_allowed_others_rejected(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder, patch.object(release_check.subprocess, "run", side_effect=OSError("no git")):
            root, os = self._copy(folder)
            try: os.symlink(root / "Assets", root / "assets", target_is_directory=True)
            except (OSError, NotImplementedError): self.skipTest("symbolic links are not available here")
            paths = {path for path, _mode in release_check.tracked_files(root)}
            self.assertNotIn("assets", paths); self.assertIn("Assets/logo.txt", paths)
            os.symlink(root / "main.py", root / "other_link.py")
            modes = dict(release_check.tracked_files(root))
            self.assertEqual(modes.get("other_link.py"), "120000")
            (root / "__pycache__").mkdir(); (root / "__pycache__" / "m.pyc").write_bytes(b"x")
            self.assertIn("__pycache__/m.pyc", dict(release_check.tracked_files(root)))

    def test_same_name_pointing_elsewhere_is_rejected(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder, patch.object(release_check.subprocess, "run", side_effect=OSError("no git")):
            root, os = self._copy(folder)
            (root / "elsewhere").mkdir()
            try: os.symlink(root / "elsewhere", root / "assets", target_is_directory=True)
            except (OSError, NotImplementedError): self.skipTest("symbolic links are not available here")
            self.assertEqual(dict(release_check.tracked_files(root)).get("assets"), "120000")
