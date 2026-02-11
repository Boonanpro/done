"""
Learning Service - スキル最適化のための学習基盤

アクション単位の実行記録を管理。
スキル生成時にルールを参照する。
"""

import logging
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from uuid import uuid4

from app.config import settings

logger = logging.getLogger(__name__)


# ============================================
# データクラス
# ============================================

@dataclass
class LearningEvent:
    """学習イベント（アクション単位の実行記録）"""
    id: str
    user_id: Optional[str]
    session_id: str
    browser_session_id: Optional[str]
    site: Optional[str]
    skill_name: Optional[str]
    action_name: str
    action_params: Dict[str, Any]
    technical_success: bool
    user_value_success: Optional[bool]
    context: Dict[str, Any]
    expected_outcome: Optional[Dict[str, Any]]
    actual_outcome: Optional[Dict[str, Any]]
    created_at: datetime

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearningEvent":
        return cls(
            id=data.get("id", str(uuid4())),
            user_id=data.get("user_id"),
            session_id=data.get("session_id", ""),
            browser_session_id=data.get("browser_session_id"),
            site=data.get("site"),
            skill_name=data.get("skill_name"),
            action_name=data.get("action_name", ""),
            action_params=data.get("action_params", {}),
            technical_success=data.get("technical_success", False),
            user_value_success=data.get("user_value_success"),
            context=data.get("context", {}),
            expected_outcome=data.get("expected_outcome"),
            actual_outcome=data.get("actual_outcome"),
            created_at=data.get("created_at", datetime.now()),
        )


@dataclass
class LearnedRule:
    """学習したルール"""
    id: str
    pattern_type: str
    scope: Dict[str, Any]
    observed_pattern: Dict[str, Any]
    inferred_rule: Dict[str, Any]
    confidence: float
    evidence_count: int
    is_active: bool = True
    manually_verified: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LearnedRule":
        return cls(
            id=data.get("id", str(uuid4())),
            pattern_type=data.get("pattern_type", ""),
            scope=data.get("scope", {}),
            observed_pattern=data.get("observed_pattern", {}),
            inferred_rule=data.get("inferred_rule", {}),
            confidence=data.get("confidence", 0.5),
            evidence_count=data.get("evidence_count", 1),
            is_active=data.get("is_active", True),
            manually_verified=data.get("manually_verified", False),
            created_at=data.get("created_at", datetime.now()),
            updated_at=data.get("updated_at", datetime.now()),
        )


# ============================================
# Supabase クライアント
# ============================================

def _get_supabase():
    """Supabase クライアントを取得"""
    from supabase import create_client
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


# ============================================
# イベント記録
# ============================================

async def record_action_event(
    session_id: str,
    action_name: str,
    technical_success: bool,
    context: Dict[str, Any],
    user_id: Optional[str] = None,
    browser_session_id: Optional[str] = None,
    site: Optional[str] = None,
    skill_name: Optional[str] = None,
    action_params: Optional[Dict[str, Any]] = None,
    expected_outcome: Optional[Dict[str, Any]] = None,
    actual_outcome: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    アクション実行イベントを記録

    Returns:
        作成されたイベントのID、失敗時は None
    """
    try:
        supabase = _get_supabase()

        event_id = str(uuid4())
        data = {
            "id": event_id,
            "user_id": user_id,
            "session_id": session_id,
            "browser_session_id": browser_session_id,
            "site": site,
            "skill_name": skill_name,
            "action_name": action_name,
            "action_params": action_params or {},
            "technical_success": technical_success,
            "context": context,
            "expected_outcome": expected_outcome,
            "actual_outcome": actual_outcome,
        }

        supabase.table("learning_events").insert(data).execute()
        logger.debug(f"Recorded learning event: {action_name} on {site}")
        return event_id

    except Exception as e:
        error_msg = str(e)
        if "could not find" in error_msg.lower() or "PGRST205" in error_msg:
            logger.warning(f"learning_events table not found. Apply migration 017_learning_system.sql")
            return None
        logger.error(f"Failed to record learning event: {e}")
        return None


async def get_events_for_session(
    session_id: str,
    browser_session_id: Optional[str] = None,
) -> List[LearningEvent]:
    """セッションのイベントを取得"""
    try:
        supabase = _get_supabase()

        query = supabase.table("learning_events").select("*").eq("session_id", session_id)
        if browser_session_id:
            query = query.eq("browser_session_id", browser_session_id)

        result = query.order("created_at").execute()
        return [LearningEvent.from_dict(row) for row in result.data]

    except Exception as e:
        logger.error(f"Failed to get events for session: {e}")
        return []


# ============================================
# ルール参照（スキル生成時に使用）
# ============================================

async def get_rules_for_skill(
    site: Optional[str] = None,
    skill_name: Optional[str] = None,
    actions: Optional[List[str]] = None,
    min_confidence: float = 0.3,
) -> List[LearnedRule]:
    """
    スキル生成時に参照するルールを取得
    """
    try:
        supabase = _get_supabase()

        result = supabase.table("learned_rules").select("*").eq(
            "is_active", True
        ).gte("confidence", min_confidence).order("confidence", desc=True).execute()

        rules = [LearnedRule.from_dict(row) for row in result.data]

        # スコープでフィルタリング
        filtered_rules = []
        for rule in rules:
            scope = rule.scope

            if scope.get("site"):
                if site and scope["site"] != site:
                    continue

            if scope.get("skill_name"):
                if skill_name and scope["skill_name"] != skill_name:
                    continue

            if scope.get("action"):
                if actions and scope["action"] not in actions:
                    continue

            filtered_rules.append(rule)

        return filtered_rules

    except Exception as e:
        error_msg = str(e)
        if "could not find" in error_msg.lower() or "PGRST205" in error_msg:
            logger.debug("learned_rules table not found. Apply migration 017_learning_system.sql")
            return []
        logger.error(f"Failed to get rules for skill: {e}")
        return []


def format_rules_for_prompt(rules: List[LearnedRule]) -> str:
    """
    学習ルールをプロンプト用にフォーマット
    """
    if not rules:
        return "（学習済みルールなし）"

    lines = []
    for rule in rules:
        scope = rule.scope
        action = scope.get("action", "不明")
        site = scope.get("site", "全サイト")

        inferred = rule.inferred_rule
        requires = inferred.get("requires_state", {})

        if requires:
            requires_str = ", ".join(f"{k}={v}" for k, v in requires.items())
            lines.append(
                f"- {action} ({site}): requires {requires_str} "
                f"(confidence: {rule.confidence:.0%}, evidence: {rule.evidence_count})"
            )

        should_first = inferred.get("should_do_first", [])
        if should_first:
            lines.append(
                f"- {action} ({site}): should do first: {', '.join(should_first)} "
                f"(confidence: {rule.confidence:.0%}, evidence: {rule.evidence_count})"
            )

    return "\n".join(lines) if lines else "（学習済みルールなし）"
