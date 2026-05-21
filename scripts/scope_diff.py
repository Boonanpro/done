"""Show the scope (infra / artifact / demo / ignored / ambiguous) of files.

Usage:
    python scripts/scope_diff.py                # currently staged
    python scripts/scope_diff.py --working      # staged + unstaged + untracked
    python scripts/scope_diff.py --branch main  # diff vs <ref>
    python scripts/scope_diff.py <path> ...     # arbitrary paths

Output is grouped by scope. Exit status is 1 if detect_mix() would block
the set, 0 otherwise - so this command can also be used as a quick
"would this commit fly?" probe.
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Windows のデフォルト cp932 だと日本語メッセージが mojibake になるので UTF-8 に固定。
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from scope_classifier import classify, detect_mix  # noqa: E402


def _git(args: list[str]) -> list[str]:
    out = subprocess.check_output(["git"] + args, cwd=ROOT, text=True, encoding="utf-8")
    return [line for line in out.splitlines() if line.strip()]


def _paths_for_mode(mode: str, ref: str | None) -> list[str]:
    if mode == "staged":
        return _git(["diff", "--cached", "--name-only", "--diff-filter=ACMRT"])
    if mode == "working":
        # staged + unstaged + untracked, deduplicated
        staged = set(_git(["diff", "--cached", "--name-only", "--diff-filter=ACMRT"]))
        unstaged = set(_git(["diff", "--name-only", "--diff-filter=ACMRT"]))
        untracked = set(_git(["ls-files", "--others", "--exclude-standard"]))
        return sorted(staged | unstaged | untracked)
    if mode == "branch":
        return _git(["diff", f"{ref}...HEAD", "--name-only", "--diff-filter=ACMRT"])
    raise ValueError(f"unknown mode: {mode}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--working", action="store_true",
                        help="include unstaged + untracked, not just staged")
    parser.add_argument("--branch", metavar="REF",
                        help="diff against this ref (e.g. main, origin/main)")
    parser.add_argument("paths", nargs="*",
                        help="explicit paths to classify (skips git lookup)")
    args = parser.parse_args()

    if args.paths:
        paths = args.paths
        source = "<args>"
    elif args.branch:
        paths = _paths_for_mode("branch", args.branch)
        source = f"git diff {args.branch}...HEAD"
    elif args.working:
        paths = _paths_for_mode("working", None)
        source = "git working tree (staged + unstaged + untracked)"
    else:
        paths = _paths_for_mode("staged", None)
        source = "git diff --cached"

    if not paths:
        print(f"({source}: no changed files)")
        return 0

    print(f"# scope of {len(paths)} file(s) ({source})")
    print()

    groups: dict[str, list[str]] = {}
    for p in paths:
        s = str(classify(p))
        groups.setdefault(s, []).append(p)

    for scope in sorted(groups.keys()):
        files = sorted(groups[scope])
        print(f"[{scope}]  ({len(files)} files)")
        for f in files:
            print(f"  {f}")
        print()

    v = detect_mix(paths)
    if v.ok:
        print("verdict: OK - this set can be committed as one logical scope")
        return 0
    print(f"verdict: BLOCK - {v.reason}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
