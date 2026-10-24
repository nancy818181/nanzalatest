"""2.9.117: the tests, in their own folder. Run them from the repository folder:

    python -m unittest discover -s tests -t . -p "test_*.py"

This file runs first: it puts the program's folders (nanza/...) and this folder on the import path, so the tests import
the program and tests_setup by name, as before."""
import sys
from pathlib import Path

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
for _path in (ROOT, TESTS):
    if str(_path) not in sys.path: sys.path.insert(0, str(_path))
import nanza_paths  # noqa: E402,F401
import os  # noqa: E402
os.environ.setdefault("NANZA_SCRYPT_LOG_N", "10")  # 2.9.134: the tests hash passwords at a low cost (the program uses 2^17); one test checks the real setting


class _Repository(type(ROOT)):
    """`REPO / "server.py"` finds a module in its folder (nanza/...), `REPO / "tests_data"` is the tests' data, anything
    else is in the repository folder (installer.iss, Assets, .github ...). Lets the tests keep `HERE / name`."""

    def __truediv__(self, name):
        name = str(name)
        if name.endswith(".py") and "/" not in name:
            try: return nanza_paths.source(name)
            except FileNotFoundError: return ROOT / name
        if name == "tests_data": return TESTS / name
        return ROOT / name


REPO = _Repository(ROOT)
