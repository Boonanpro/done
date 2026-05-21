"""Test inspector_writeback scope hardening.

Verifies that the writeback module refuses to write outside
frontend/src/app/artifacts/<slug>/ even when called with a path that
points elsewhere. This is the defense against a future bug or refactor
that loses the slug-level filter.

Run with:
    python scripts/test_inspector_writeback_scope.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.inspector_writeback_core import (
    ARTIFACTS_ROOT,
    WritebackScopeError,
    _ensure_under_artifact,
    _artifact_root,
    apply_override_to_file,
    remove_element_from_file,
)


def expect_raises(name: str, fn) -> bool:
    try:
        fn()
    except WritebackScopeError as e:
        print(f"  OK:   {name} -> blocked ({e})")
        return True
    except Exception as e:
        print(f"  FAIL: {name} -> wrong exception type: {type(e).__name__}: {e}")
        return False
    print(f"  FAIL: {name} -> NOT blocked (security bug)")
    return False


def expect_ok(name: str, fn) -> bool:
    try:
        fn()
    except Exception as e:
        print(f"  FAIL: {name} -> raised {type(e).__name__}: {e}")
        return False
    print(f"  OK:   {name} -> passed")
    return True


def main() -> int:
    failed = 0

    print("=== _artifact_root rejects invalid slugs ===")
    for bad in ["", "..", "../etc", "foo/bar", "foo\\bar", ".."]:
        if not expect_raises(f"slug={bad!r}", lambda b=bad: _artifact_root(b)):
            failed += 1

    print("\n=== _ensure_under_artifact accepts paths inside artifact dir ===")
    # Use a real artifact dir if it exists, otherwise simulate.
    kittoku_root = _artifact_root("kittoku")
    if kittoku_root.exists():
        sample = next(kittoku_root.rglob("*.tsx"), None)
        if sample:
            if not expect_ok(
                f"inside kittoku: {sample.relative_to(ROOT)}",
                lambda s=sample: _ensure_under_artifact(s, "kittoku"),
            ):
                failed += 1

    print("\n=== _ensure_under_artifact rejects paths outside artifact dir ===")
    cases = [
        ("app/api/chat_routes.py belongs to Dan infra", ROOT / "app/api/chat_routes.py"),
        ("frontend/src/middleware.ts belongs to Dan infra", ROOT / "frontend/src/middleware.ts"),
        ("scripts/auto_deploy.py", ROOT / "scripts/auto_deploy.py"),
        # Different artifact's file should be rejected when slug doesn't match.
        (
            "salonboard file under kittoku slug",
            ROOT / "frontend/src/app/artifacts/salonboard-styleup/page.tsx",
        ),
        # Path traversal attempts
        (
            "traversal: ../../../etc/passwd",
            ARTIFACTS_ROOT / "kittoku" / ".." / ".." / ".." / "etc" / "passwd",
        ),
        (
            "traversal: ../salonboard/page.tsx",
            ARTIFACTS_ROOT / "kittoku" / ".." / "salonboard-styleup" / "page.tsx",
        ),
    ]
    for name, p in cases:
        if not expect_raises(name, lambda path=p: _ensure_under_artifact(path, "kittoku")):
            failed += 1

    print("\n=== apply_override_to_file refuses out-of-scope target ===")
    out_of_scope = ROOT / "app" / "api" / "chat_routes.py"
    if not expect_raises(
        "apply_override_to_file to chat_routes.py",
        lambda: apply_override_to_file(out_of_scope, "fake-edit-id", {}, slug="kittoku"),
    ):
        failed += 1

    print("\n=== remove_element_from_file refuses out-of-scope target ===")
    if not expect_raises(
        "remove_element_from_file from chat_routes.py",
        lambda: remove_element_from_file(out_of_scope, "fake-edit-id", slug="kittoku"),
    ):
        failed += 1

    print(f"\n{failed} failure(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
