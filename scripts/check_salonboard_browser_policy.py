"""Fail if Salonboard browser automation bypasses the session policy module."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ALLOWED_FILES = {
    Path("app/services/salonboard_browser_session.py"),
    Path("scripts/check_salonboard_browser_policy.py"),
    Path("tests/test_salonboard_browser_policy.py"),
}
FORBIDDEN = [
    "https://salonboard.com/login/",
    "launch_persistent_context(",
]


def tracked_python_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def main() -> int:
    violations: list[str] = []
    for path in tracked_python_files():
        if path in ALLOWED_FILES:
            continue
        text = (REPO_ROOT / path).read_text(encoding="utf-8")
        if "salonboard" not in text.lower():
            continue
        for needle in FORBIDDEN:
            if needle in text:
                violations.append(f"{path}: direct use of {needle!r}")

    if violations:
        print("Salonboard browser session policy violation:")
        for violation in violations:
            print(f"  - {violation}")
        print("\nUse app.services.salonboard_browser_session instead.")
        return 1

    print("OK: Salonboard browser session policy is centralized")
    return 0


if __name__ == "__main__":
    sys.exit(main())
