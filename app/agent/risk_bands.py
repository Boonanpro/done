"""
Shared Green/Yellow/Red risk-band policy.

This file is the single source of truth for risk-band wording and
keyword-based red-action detection used by project execution flows.
"""

from __future__ import annotations

from typing import Iterable

# Human-readable policy lines used in prompts/docs.
GREEN_POLICY_LINE = (
    "- **Green（即実行）**: 検索、閲覧、ツール作成、bashコマンド、"
    "ファイル操作、パッケージインストール"
)
YELLOW_POLICY_LINE = (
    "- **Yellow（実行→報告）**: フォーム入力（非個人情報）、"
    "カート追加、設定変更"
)
RED_POLICY_LINE = (
    "- **Red（確認→実行）**: 個人情報入力、購入確定、取消不可操作"
    " → 必ずユーザーに内容を示して確認を待つ"
)

# Runtime red-action detection.
DEFAULT_RED_KEYWORDS = (
    "購入",
    "確定",
    "送金",
    "振込",
    "削除",
    "解約",
    "個人情報",
    "【要人間】",
)

DEFAULT_YELLOW_KEYWORDS = (
    "フォーム",
    "入力",
    "カート",
    "設定",
    "更新",
)


def render_zone_policy_for_prompt() -> str:
    """Return the standard G/Y/R policy block for prompt injection."""
    return "\n".join((GREEN_POLICY_LINE, YELLOW_POLICY_LINE, RED_POLICY_LINE))


def is_red_action(text: str, extra_keywords: Iterable[str] | None = None) -> bool:
    """Return True when text contains red-action keywords."""
    if not text:
        return False
    keywords = list(DEFAULT_RED_KEYWORDS)
    if extra_keywords:
        keywords.extend(list(extra_keywords))
    return any(keyword in text for keyword in keywords)


def classify_risk_band(text: str) -> str:
    """
    Classify text into green / yellow / red.

    Note:
    - Red uses strict keyword detection.
    - Yellow is a soft heuristic and used mainly for reporting guidance.
    """
    if is_red_action(text):
        return "red"
    if any(keyword in (text or "") for keyword in DEFAULT_YELLOW_KEYWORDS):
        return "yellow"
    return "green"

