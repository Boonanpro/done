"""
Proposal step extraction helpers.

This module is shared by planning flows so step parsing is decoupled from
legacy proposal generators.
"""

from __future__ import annotations

import json
import logging
import re
from typing import List

logger = logging.getLogger(__name__)


def extract_steps(proposal_text: str) -> List[dict]:
    """
    Extract execution steps from proposal markdown.

    Order:
    1. Regex-based parsing (3 patterns)
    2. LLM fallback when regex extraction fails
    """
    steps = _extract_steps_regex(proposal_text)
    if steps:
        return steps
    logger.warning("[ProposalSteps] Regex extraction failed, trying LLM fallback")
    return _extract_steps_llm(proposal_text)


def _extract_steps_regex(proposal_text: str) -> List[dict]:
    """Regex-based extraction with three fallback patterns."""
    steps: List[dict] = []
    step_num = 0

    # Pattern 1: numbered list under 実行計画
    plan_match = re.search(
        r"#+\s*実行計画\s*\n(.*?)(?=\n#+\s|\Z)",
        proposal_text,
        re.DOTALL,
    )
    if plan_match:
        plan_section = plan_match.group(1)
        for match in re.finditer(r"(\d+)\.\s+(.+)", plan_section):
            step_num += 1
            steps.append(
                {
                    "step_number": step_num,
                    "description": match.group(2).strip(),
                    "status": "pending",
                }
            )
        if steps:
            return steps

    # Pattern 2: phase heading + table rows
    phase_matches = re.finditer(
        r"#+\s*フェーズ\s*\d+[：:]\s*(.+?)(?:\s*[（(].+?[）)])?\s*\n(.*?)(?=\n#+\s*フェーズ|\n#+\s*[^#]|\Z)",
        proposal_text,
        re.DOTALL,
    )
    for phase_match in phase_matches:
        phase_name = phase_match.group(1).strip()
        phase_body = phase_match.group(2)
        for row in re.finditer(r"\|\s*[\d\-]+\s*\|\s*(.+?)\s*\|", phase_body):
            desc = row.group(1).strip()
            if desc.startswith("-") or desc in ("内容", "ステップ", "説明"):
                continue
            step_num += 1
            steps.append(
                {
                    "step_number": step_num,
                    "description": f"{phase_name}: {desc}",
                    "status": "pending",
                }
            )
    if steps:
        return steps

    # Pattern 3: generic numbered list
    for match in re.finditer(r"^(\d+)\.\s+(.+)", proposal_text, re.MULTILINE):
        step_num += 1
        steps.append(
            {
                "step_number": step_num,
                "description": match.group(2).strip(),
                "status": "pending",
            }
        )

    return steps


def _extract_steps_llm(proposal_text: str) -> List[dict]:
    """LLM fallback extraction."""
    try:
        import anthropic
        from app.config import settings

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": f"""以下の提案書から実行ステップを抽出してJSON配列で返してください。

提案書:
{proposal_text[:4000]}

出力形式（これだけを返すこと。説明は不要）:
[
  {{"step_number": 1, "description": "ステップの内容"}},
  {{"step_number": 2, "description": "ステップの内容"}}
]""",
                }
            ],
        )

        raw = response.content[0].text.strip()
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            logger.warning("[ProposalSteps] LLM extraction: no JSON array found")
            return []

        parsed = json.loads(json_match.group())
        steps: List[dict] = []
        for i, item in enumerate(parsed, 1):
            desc = item.get("description", "").strip()
            if not desc:
                continue
            steps.append(
                {"step_number": i, "description": desc, "status": "pending"}
            )

        logger.info("[ProposalSteps] LLM extracted %s steps", len(steps))
        return steps
    except Exception as e:
        logger.warning("[ProposalSteps] LLM extraction failed: %s", e)
        return []
