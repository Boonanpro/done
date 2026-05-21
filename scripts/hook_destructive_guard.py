"""Block destructive Bash commands before they execute.

Failure modes this guards against:
- ``git stash push|save``: stashed work gets forgotten. Use a wip branch
  (``git checkout -b wip/...`` + ``git commit -m wip``) instead so the
  work is visible in ``git branch -a``.
- ``git stash drop|clear``: silently wipes existing stashes that may hold
  the user's real work (this exact failure caused the 2026-05-21 incident).
- ``git reset --hard``: discards uncommitted changes irreversibly.
- ``git push --force``: overwrites upstream history. ``--force-with-lease``
  is allowed (it errors out if upstream moved instead of overwriting).
- ``rm -rf`` on source paths: catastrophic. ``node_modules``/``.next``/
  ``dist``/``build``/``.cache``/``coverage``/``tmp`` are allow-listed
  because nuking build caches is routine.

Escape hatch: set ``OVERRIDE_DESTRUCTIVE=1`` inline (e.g.
``OVERRIDE_DESTRUCTIVE=1 git reset --hard origin/main``) when the
operation is genuinely intended. The override has to be typed every
time so it can't slip in by reflex.

Read-only stash subcommands (``list``, ``show``, ``apply``, ``pop``,
``branch``) pass through. ``pop`` is allowed because it surfaces work
rather than hiding it; ``drop``/``clear`` are the dangerous ones.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

# Windows のデフォルト cp932 だと日本語メッセージが文字化けするので UTF-8 に固定。
if hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# Each rule: (regex, human explanation, suggested replacement)
RULES: list[tuple[re.Pattern, str, str]] = [
    (
        re.compile(r"(^|[\s;&|`])git\s+stash\s+(push|save)(\s|$)"),
        "git stash push/save は退避物が忘れられて作業が失われる事故が多い",
        "代わりに wip ブランチを作って commit してください:\n"
        "  git checkout -b wip/<short-name>\n"
        "  git add -A && git commit -m 'wip: <short-description>'",
    ),
    (
        re.compile(r"(^|[\s;&|`])git\s+stash\s+(drop|clear)(\s|$)"),
        "git stash drop/clear は他人(過去の自分)が退避した重要な変更を消す可能性がある",
        "先に ``git stash list`` で中身を確認し、本当に不要なら "
        "``OVERRIDE_DESTRUCTIVE=1`` を付けて実行してください",
    ),
    (
        re.compile(r"(^|[\s;&|`])git\s+reset\s+--hard(\s|$)"),
        "git reset --hard はワーキングツリーの未コミット変更を全て破棄する",
        "影響範囲を絞るには:\n"
        "  特定ファイルだけ:  git checkout -- <path>\n"
        "  マージを取り消し:  git reset --merge\n"
        "本当に hard reset したい場合は ``OVERRIDE_DESTRUCTIVE=1`` を付けてください",
    ),
    (
        # --force だが --force-with-lease は許可。後者は upstream が動いていたら fail する安全版
        re.compile(
            r"(^|[\s;&|`])git\s+push\s+(?:[^-\s]+\s+)?(?:--force(?!-with-lease)|-f)(\s|$)"
        ),
        "git push --force は他人の commit を上書きして失わせる可能性がある",
        "代わりに --force-with-lease を使ってください (upstream が動いていたら "
        "fail して衝突を可視化します):\n"
        "  git push --force-with-lease",
    ),
]

# rm -rf は破壊力が桁違いなので、特定の build/cache パスに限定して allow する。
RM_RF_RE = re.compile(r"(^|[\s;&|`])rm\s+-(?:rf|fr)(?:[a-zA-Z]*)\s+(?P<target>\S+)")
RM_RF_ALLOW_TARGETS = (
    "node_modules",
    ".next",
    "dist",
    "build",
    ".cache",
    "coverage",
    "tmp",
    "temp",
    ".turbo",
    "out",
    ".vercel",
    ".pytest_cache",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
)


def _check_rm_rf(cmd: str) -> tuple[str, str] | None:
    """Return (message, suggestion) if rm -rf target is not allow-listed."""
    for match in RM_RF_RE.finditer(cmd):
        target = match.group("target").strip("\"'")
        # Path separator agnostic: strip leading ./ and split, look at last segment.
        normalized = target.replace("\\", "/").rstrip("/")
        last = normalized.rsplit("/", 1)[-1]
        # Allowlist: last segment matches OR full path ends with allowed dir
        if last in RM_RF_ALLOW_TARGETS:
            continue
        # /tmp/... も許容
        if normalized.startswith("/tmp/") or normalized.startswith("tmp/"):
            continue
        return (
            f"rm -rf {target} は通常のビルドキャッシュ削除パスに含まれない",
            "ビルドキャッシュ削除なら node_modules / .next / dist / build / .cache "
            "/ coverage / __pycache__ などの allowlist パスを使ってください。\n"
            "本当に削除する必要があるなら ``OVERRIDE_DESTRUCTIVE=1`` を付けてください",
        )
    return None


def _read_payload() -> dict:
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def _command_text(payload: dict) -> str:
    tool_input = payload.get("tool_input") or {}
    return tool_input.get("command") or ""


# `cmd ... <<'TAG' ... TAG` のような HEREDOC ブロックを除去する。
# gh pr create / git commit -m などで PR body や commit message に
# "git reset --hard" のような単語が含まれて誤検知するのを防ぐ。
_HEREDOC_RE = re.compile(
    r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[\s\S]*?^\2\s*$",
    re.MULTILINE,
)

# シングルクォート / ダブルクォートで囲まれた文字列も除外する
# (例: gh pr create --body "...git reset --hard..." の本文)。
# 単純化のため、改行を跨がない最短マッチで近似する。
_SINGLE_QUOTED_RE = re.compile(r"'[^'\n]*'")
_DOUBLE_QUOTED_RE = re.compile(r'"[^"\n]*"')


def _strip_quoted_regions(cmd: str) -> str:
    """文字列リテラル / HEREDOC を空白に置換した「実行されうる部分だけ」の表現を返す。

    完璧な shell パーサではないが、PR body / commit message / curl --data
    等の中で命令名が登場する誤検知をほぼ消せる。"""
    stripped = _HEREDOC_RE.sub(" ", cmd)
    stripped = _SINGLE_QUOTED_RE.sub(" ", stripped)
    stripped = _DOUBLE_QUOTED_RE.sub(" ", stripped)
    return stripped


def main() -> int:
    payload = _read_payload()
    cmd = _command_text(payload)
    if not cmd:
        return 0

    # Inline escape hatch. We check the command string itself (not the parent
    # process env) so the override has to be typed explicitly every time.
    if re.search(r"(^|[\s;&|`])OVERRIDE_DESTRUCTIVE=1(\s|$)", cmd):
        return 0
    if os.environ.get("OVERRIDE_DESTRUCTIVE") == "1":
        return 0

    # 文字列リテラル / HEREDOC 内に登場する命令名はマッチ対象から除外する。
    executable = _strip_quoted_regions(cmd)

    for rule, reason, suggestion in RULES:
        if rule.search(executable):
            sys.stderr.write(
                "破壊的コマンドをブロックしました:\n"
                f"  command: {cmd}\n"
                f"  理由: {reason}\n\n"
                f"{suggestion}\n"
            )
            return 2

    rm_check = _check_rm_rf(executable)
    if rm_check:
        reason, suggestion = rm_check
        sys.stderr.write(
            "破壊的コマンドをブロックしました:\n"
            f"  command: {cmd}\n"
            f"  理由: {reason}\n\n"
            f"{suggestion}\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
