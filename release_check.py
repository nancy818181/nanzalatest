"""2.9.100: the checks made before every release (run by the tests on every push, on Linux and Windows).

Two stray files reached GitHub in 2.9.97-2.9.98 (files named "<_io.BytesIO ...>" and a link Assets/Assets) and stopped the
Windows installer build. These checks fail the tests when anything like that is in the repository again:
- no symbolic link and no file Windows cannot have (< > : " | ? * in the name, a trailing dot or space, reserved names);
- no cache / test-setup folder (__pycache__, the lowercase 'assets' link);
- the version is the same in installer.iss, app_runtime.py and the first "## Version" of README.md;
- every program module compiles.
Usage: python release_check.py   (prints the problems, exit code 1 when there are any)."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WINDOWS_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')
RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


def tracked_files(root=ROOT):
    """(path, mode) of the files in the repository index - or of the folder when git is not there."""
    try:
        output = subprocess.run(["git", "ls-files", "-s", "-z"], cwd=root, capture_output=True, check=True).stdout.decode("utf-8", "replace")
        entries = []
        for item in output.split("\0"):
            if not item: continue
            meta, path = item.split("\t", 1)
            entries.append((path, meta.split()[0]))
        return entries
    except (OSError, subprocess.CalledProcessError):
        return [(str(p.relative_to(root)).replace("\\", "/"), "120000" if p.is_symlink() else "100644")
                for p in root.rglob("*") if p.is_file() or p.is_symlink()]


def versions(root=ROOT):
    installer = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', (root / "installer.iss").read_text(encoding="utf-8"))
    runtime = re.search(r'^APP_VERSION\s*=\s*"([^"]+)"', (root / "app_runtime.py").read_text(encoding="utf-8"), re.M)
    readme = re.search(r"^## Version\s+(\S+)", (root / "README.md").read_text(encoding="utf-8"), re.M)
    return {"installer.iss": installer and installer.group(1), "app_runtime.py": runtime and runtime.group(1), "README.md": readme and readme.group(1)}


def problems(root=ROOT):
    found = []
    for path, mode in tracked_files(root):
        name = path.rsplit("/", 1)[-1]
        if mode == "120000": found.append(f"symbolic link in the repository: {path}")
        if WINDOWS_BAD.search(path) or name.endswith((".", " ")) or name.split(".")[0].lower() in RESERVED:
            found.append(f"file name Windows cannot have: {path!r}")
        if "__pycache__/" in path or path.endswith(".pyc"): found.append(f"cache file in the repository: {path}")
        if path == "assets" or path.startswith("assets/"): found.append(f"test-setup link 'assets' in the repository: {path}")
    v = versions(root)
    if len(set(v.values())) != 1 or None in v.values():
        found.append("versions differ: " + ", ".join(f"{k} {val}" for k, val in v.items()))
    for module in sorted(root.glob("*.py")):
        try: compile(module.read_text(encoding="utf-8"), str(module), "exec")  # checks the syntax without writing a .pyc
        except (SyntaxError, ValueError, UnicodeDecodeError) as exc: found.append(f"does not compile: {module.name}: {exc}")
    return found


if __name__ == "__main__":
    issues = problems()
    for issue in issues: print("RELEASE CHECK:", issue)
    print("release check: " + ("OK" if not issues else f"{len(issues)} problem(s)"))
    sys.exit(1 if issues else 0)
