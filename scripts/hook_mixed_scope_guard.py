"""Pre-commit guard: block commits that mix Dan infra with artifact code.

Run from a git pre-commit hook (or any other layer that wants the same
check; the CI workflow imports detect_mix() directly).

Behavior:
    - Reads ``git diff --cached --name-only --diff-filter=ACMRT`` to get
      the set of files staged for the commit.
    - Classifies each path via ``scope_classifier.classify``.
    - Calls ``scope_classifier.detect_mix`` to decide.
    - On block: prints a structured message to stderr explaining which
      files belong to which scope and why the commit is rejected, then
      exits with status 1 (which aborts the commit).
    - On pass: exits 0 silently.

Bypass:
    - ``OVERRIDE_MIXED_SCOPE=1 git commit ...`` skips the check. Use only
      when a single logical change genuinely has to touch both layers
      (rare). The override has to be typed each time so it can not slip
      in by reflex.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

# Windows のデフォルト cp932 だと日本語メッセージが mojibake になるので UTF-8 に固定。
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _staged_paths() -> list[str]:
    try:
        out = subprocess.check_output(
            [
                "git",
                "diff",
                "--cached",
                "--name-only",
                "--diff-filter=ACMRT",
            ],
            text=True,
            encoding="utf-8",
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    if os.environ.get("OVERRIDE_MIXED_SCOPE") == "1":
        return 0

    here = Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    from scope_classifier import classify, detect_mix  # noqa: E402

    paths = _staged_paths()
    if not paths:
        return 0

    verdict = detect_mix(paths)
    if verdict.ok:
        return 0

    sys.stderr.write("\n")
    sys.stderr.write("=" * 70 + "\n")
    sys.stderr.write("混在 commit を pre-commit hook がブロックしました\n")
    sys.stderr.write("=" * 70 + "\n")
    sys.stderr.write(f"\n理由: {verdict.reason}\n\n")

    sys.stderr.write("staged files (scope ごと):\n")
    if verdict.infra_files:
        sys.stderr.write("  [infra]\n")
        for p in sorted(verdict.infra_files):
            sys.stderr.write(f"    {p}\n")
    for slug in sorted(verdict.artifact_groups):
        sys.stderr.write(f"  [artifact:{slug}]\n")
        for p in sorted(verdict.artifact_groups[slug]):
            sys.stderr.write(f"    {p}\n")
    if verdict.ambiguous_files:
        sys.stderr.write("  [ambiguous - scope_classifier にルール追加が必要]\n")
        for p in sorted(verdict.ambiguous_files):
            sys.stderr.write(f"    {p}\n")

    sys.stderr.write("\n対処:\n")
    sys.stderr.write(
        "  1. 一方を unstage して別 commit に分ける:\n"
        "       git reset HEAD <path>\n"
        "       git commit -m 'feat(<scope>): ...'\n"
        "       git add <other path>\n"
        "       git commit -m 'feat(<other scope>): ...'\n"
        "  2. 本当に同じ commit が必要な特例の時のみ:\n"
        "       OVERRIDE_MIXED_SCOPE=1 git commit ...\n"
    )

    if verdict.ambiguous_files:
        sys.stderr.write(
            "\nambiguous なファイルは scripts/scope_classifier.py の "
            "ルール表 (_PUBLIC_DIR_TO_OWNER / _PUBLIC_FILE_TO_OWNER / "
            "_INFRA_PATTERNS) に追記してから再 commit してください。\n"
        )

    sys.stderr.write("=" * 70 + "\n\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
