"""
Learning Service - スキル最適化のための学習基盤

アクション単位の実行記録とパターンから学習したルールを管理。
汎用的な設計で、任意のサイト・アクション・状態要件に対応。

## アーキテクチャ
- SQL集計: リトライパターン、アクション順序の統計
- LLM推論: パターンから因果関係を推論（GPT-4o mini / Gemini 2.5 Flash）
- 全履歴: 直近N日制限なし、すべてのデータを活用
"""

import logging
import asyncio
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
    pattern_type: str  # 'state_requirement', 'action_sequence', etc.
    scope: Dict[str, Any]  # { site, action, action_category, ... }
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "pattern_type": self.pattern_type,
            "scope": self.scope,
            "observed_pattern": self.observed_pattern,
            "inferred_rule": self.inferred_rule,
            "confidence": self.confidence,
            "evidence_count": self.evidence_count,
            "is_active": self.is_active,
            "manually_verified": self.manually_verified,
        }


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

    Args:
        session_id: AgentRunner のセッションID
        action_name: アクション名（click, type, add-to-cart 等）
        technical_success: 技術的に成功したか
        context: 実行時のコンテキスト（logged_in, page_url 等）
        user_id: ユーザーID
        browser_session_id: VisualAgent のセッションID
        site: サイトドメイン
        skill_name: スキル名
        action_params: アクションのパラメータ
        expected_outcome: 期待した結果
        actual_outcome: 実際の結果

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
        # テーブルが存在しない場合は警告のみ（マイグレーション未適用）
        if "could not find" in error_msg.lower() or "PGRST205" in error_msg:
            logger.warning(f"learning_events table not found. Apply migration 017_learning_system.sql")
            return None
        logger.error(f"Failed to record learning event: {e}")
        return None


async def update_user_value_success(
    event_id: str,
    user_value_success: bool,
    reason: Optional[str] = None,
) -> bool:
    """
    イベントの user_value_success を更新

    Args:
        event_id: イベントID
        user_value_success: ユーザーにとって価値があったか
        reason: 判定理由

    Returns:
        成功したか
    """
    try:
        supabase = _get_supabase()

        supabase.table("learning_events").update({
            "user_value_success": user_value_success,
            "user_value_evaluated_at": datetime.now().isoformat(),
            "user_value_reason": reason,
        }).eq("id", event_id).execute()

        logger.debug(f"Updated user_value_success for event {event_id}: {user_value_success}")
        return True

    except Exception as e:
        logger.error(f"Failed to update user_value_success: {e}")
        return False


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


async def get_events_for_analysis(
    site: Optional[str] = None,
    action_name: Optional[str] = None,
    skill_name: Optional[str] = None,
    limit: int = 1000,
) -> List[LearningEvent]:
    """分析用にイベントを取得"""
    try:
        supabase = _get_supabase()

        query = supabase.table("learning_events").select("*")

        if site:
            query = query.eq("site", site)
        if action_name:
            query = query.eq("action_name", action_name)
        if skill_name:
            query = query.eq("skill_name", skill_name)

        result = query.order("created_at", desc=True).limit(limit).execute()
        return [LearningEvent.from_dict(row) for row in result.data]

    except Exception as e:
        logger.error(f"Failed to get events for analysis: {e}")
        return []


# ============================================
# ルール管理
# ============================================

async def upsert_learned_rule(
    pattern_type: str,
    scope: Dict[str, Any],
    observed_pattern: Dict[str, Any],
    inferred_rule: Dict[str, Any],
    confidence: float = 0.5,
) -> Optional[LearnedRule]:
    """
    学習ルールを追加または更新

    同じ scope + pattern_type のルールが存在すれば evidence_count を増やし、
    confidence を更新。なければ新規作成。

    Args:
        pattern_type: パターン種別
        scope: スコープ
        observed_pattern: 観察されたパターン
        inferred_rule: 推論されたルール
        confidence: 信頼度

    Returns:
        作成/更新されたルール
    """
    try:
        supabase = _get_supabase()

        # スコープをJSON文字列に変換してユニークキーを作成
        scope_key = json.dumps(scope, sort_keys=True, ensure_ascii=False)

        # 既存ルールを検索（pattern_type でフィルタし、Pythonで scope を比較）
        existing_query = supabase.table("learned_rules").select("*").eq(
            "pattern_type", pattern_type
        ).eq("is_active", True).execute()

        # Python側で scope が一致するものを探す
        matching_rule = None
        for row in existing_query.data:
            row_scope = row.get("scope", {})
            row_scope_key = json.dumps(row_scope, sort_keys=True, ensure_ascii=False)
            if row_scope_key == scope_key:
                matching_rule = row
                break

        if matching_rule:
            # 既存ルールを更新
            rule_data = matching_rule
            new_evidence_count = rule_data["evidence_count"] + 1
            # confidence を加重平均で更新
            new_confidence = (
                rule_data["confidence"] * rule_data["evidence_count"] + confidence
            ) / new_evidence_count

            supabase.table("learned_rules").update({
                "evidence_count": new_evidence_count,
                "confidence": new_confidence,
                "last_evidence_at": datetime.now().isoformat(),
                "observed_pattern": observed_pattern,  # 最新のパターンで更新
            }).eq("id", rule_data["id"]).execute()

            logger.info(f"Updated learned rule: {pattern_type} for {scope}, confidence: {new_confidence:.2f}")

            rule_data["evidence_count"] = new_evidence_count
            rule_data["confidence"] = new_confidence
            return LearnedRule.from_dict(rule_data)
        else:
            # 新規ルールを作成
            rule_id = str(uuid4())
            data = {
                "id": rule_id,
                "pattern_type": pattern_type,
                "scope": scope,
                "observed_pattern": observed_pattern,
                "inferred_rule": inferred_rule,
                "confidence": confidence,
                "evidence_count": 1,
                "last_evidence_at": datetime.now().isoformat(),
            }

            supabase.table("learned_rules").insert(data).execute()
            logger.info(f"Created learned rule: {pattern_type} for {scope}")

            return LearnedRule.from_dict(data)

    except Exception as e:
        logger.error(f"Failed to upsert learned rule: {e}")
        return None


async def get_rules_for_skill(
    site: Optional[str] = None,
    skill_name: Optional[str] = None,
    actions: Optional[List[str]] = None,
    min_confidence: float = 0.3,
) -> List[LearnedRule]:
    """
    スキル生成時に参照するルールを取得

    Args:
        site: サイトドメイン
        skill_name: スキル名
        actions: アクション名のリスト
        min_confidence: 最小信頼度

    Returns:
        適用可能なルールのリスト
    """
    try:
        supabase = _get_supabase()

        # アクティブで信頼度が閾値以上のルールを取得
        result = supabase.table("learned_rules").select("*").eq(
            "is_active", True
        ).gte("confidence", min_confidence).order("confidence", desc=True).execute()

        rules = [LearnedRule.from_dict(row) for row in result.data]

        # スコープでフィルタリング
        filtered_rules = []
        for rule in rules:
            scope = rule.scope

            # サイトマッチ
            if scope.get("site"):
                if site and scope["site"] != site:
                    continue

            # スキルマッチ
            if scope.get("skill_name"):
                if skill_name and scope["skill_name"] != skill_name:
                    continue

            # アクションマッチ
            if scope.get("action"):
                if actions and scope["action"] not in actions:
                    continue

            filtered_rules.append(rule)

        return filtered_rules

    except Exception as e:
        error_msg = str(e)
        # テーブルが存在しない場合は警告のみ
        if "could not find" in error_msg.lower() or "PGRST205" in error_msg:
            logger.debug("learned_rules table not found. Apply migration 017_learning_system.sql")
            return []
        logger.error(f"Failed to get rules for skill: {e}")
        return []


async def get_all_active_rules() -> List[LearnedRule]:
    """全てのアクティブなルールを取得"""
    try:
        supabase = _get_supabase()

        result = supabase.table("learned_rules").select("*").eq(
            "is_active", True
        ).order("confidence", desc=True).execute()

        return [LearnedRule.from_dict(row) for row in result.data]

    except Exception as e:
        logger.error(f"Failed to get all active rules: {e}")
        return []


# ============================================
# イベントリンク（因果関係、将来用）
# ============================================

async def link_events(
    source_event_id: str,
    target_event_id: str,
    link_type: str,
    confidence: float = 0.5,
    metadata: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    イベント間のリンクを作成

    Args:
        source_event_id: ソースイベントID
        target_event_id: ターゲットイベントID
        link_type: リンク種別（caused_by, followed_by, invalidated_by, retry_of）
        confidence: 信頼度
        metadata: 追加情報

    Returns:
        成功したか
    """
    try:
        supabase = _get_supabase()

        supabase.table("event_links").insert({
            "id": str(uuid4()),
            "source_event_id": source_event_id,
            "target_event_id": target_event_id,
            "link_type": link_type,
            "confidence": confidence,
            "metadata": metadata or {},
        }).execute()

        return True

    except Exception as e:
        logger.error(f"Failed to link events: {e}")
        return False


# ============================================
# ユーティリティ
# ============================================

def format_rules_for_prompt(rules: List[LearnedRule]) -> str:
    """
    学習ルールをプロンプト用にフォーマット

    Args:
        rules: ルールのリスト

    Returns:
        プロンプトに注入する文字列
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


def extract_context_variables(events: List[LearningEvent]) -> List[str]:
    """イベントの context から全ての変数名を抽出"""
    variables = set()
    for event in events:
        if event.context:
            variables.update(event.context.keys())
    return list(variables)


# ============================================
# パターン検出（user_id ベース）
# ============================================

async def get_user_action_history(
    user_id: str,
    site: Optional[str] = None,
    limit: int = 500,
) -> List[LearningEvent]:
    """
    特定ユーザーの行動履歴を時系列で取得

    Args:
        user_id: ユーザーID
        site: 対象サイト（省略時は全サイト）
        limit: 取得件数上限

    Returns:
        時系列順の行動履歴
    """
    try:
        supabase = _get_supabase()

        query = supabase.table("learning_events").select("*").eq("user_id", user_id)
        if site:
            query = query.eq("site", site)

        result = query.order("created_at").limit(limit).execute()
        return [LearningEvent.from_dict(row) for row in result.data]

    except Exception as e:
        error_msg = str(e)
        if "could not find" in error_msg.lower() or "PGRST205" in error_msg:
            return []
        logger.error(f"Failed to get user action history: {e}")
        return []


async def detect_retry_patterns(
    site: Optional[str] = None,
    min_occurrences: int = 3,
) -> List[Dict[str, Any]]:
    """
    リトライパターンを検出（user_id ベース）

    「同じアクションを短期間で繰り返す」パターンを検出。
    これは最初のアクションが期待通りに動作しなかったことを示唆する。

    例: add-to-cart (logged_in=False) → 時間経過 → add-to-cart (同じ商品)
        → 最初の add-to-cart が無効だった可能性

    Args:
        site: 対象サイト（省略時は全サイト）
        min_occurrences: パターン認定に必要な最小発生回数

    Returns:
        検出されたパターンのリスト
    """
    events = await get_events_for_analysis(site=site, limit=5000)

    if len(events) < min_occurrences:
        logger.debug(f"Not enough events for retry pattern detection: {len(events)}")
        return []

    # user_id でグループ化
    users: Dict[str, List[LearningEvent]] = {}
    for event in events:
        if not event.user_id:
            continue
        if event.user_id not in users:
            users[event.user_id] = []
        users[event.user_id].append(event)

    # 各ユーザーの履歴を時系列でソート
    for user_id in users:
        users[user_id].sort(key=lambda e: e.created_at)

    # リトライパターンを検出
    # {(action, context_var, context_val): {"retry_count": N, "no_retry_count": M}}
    pattern_stats: Dict[tuple, Dict[str, int]] = {}

    for user_id, user_events in users.items():
        # 同じアクションの連続/近接を検出
        for i, event in enumerate(user_events):
            action = event.action_name
            if action in ("click", "scroll", "type", "wait"):  # 低レベルアクションは除外
                continue

            # このアクションの後、同じアクションが再度実行されたか？
            retry_detected = False
            for j in range(i + 1, min(i + 20, len(user_events))):  # 後続20イベント以内
                later_event = user_events[j]
                if later_event.action_name == action:
                    # 同じアクションが再度実行された = リトライ
                    retry_detected = True
                    break

            # コンテキスト変数ごとに統計を取る
            if event.context:
                for var, val in event.context.items():
                    if var in ("page_url",):  # 除外
                        continue

                    key = (action, var, str(val))
                    if key not in pattern_stats:
                        pattern_stats[key] = {"retry": 0, "no_retry": 0}

                    if retry_detected:
                        pattern_stats[key]["retry"] += 1
                    else:
                        pattern_stats[key]["no_retry"] += 1

    # パターンを抽出
    patterns = []
    for (action, var, val), stats in pattern_stats.items():
        total = stats["retry"] + stats["no_retry"]
        if total < min_occurrences:
            continue

        retry_rate = stats["retry"] / total

        # リトライ率が高い = その状態でアクションすると問題が起きやすい
        if retry_rate >= 0.3:  # 30%以上のリトライ率
            # 反対の値でのリトライ率を確認
            opposite_retry_rate = 0
            for (other_action, other_var, other_val), other_stats in pattern_stats.items():
                if other_action == action and other_var == var and other_val != val:
                    other_total = other_stats["retry"] + other_stats["no_retry"]
                    if other_total >= min_occurrences:
                        other_rate = other_stats["retry"] / other_total
                        opposite_retry_rate = min(opposite_retry_rate, other_rate) if opposite_retry_rate > 0 else other_rate

            # 反対の値でリトライ率が低い場合、このパターンは有意
            if opposite_retry_rate < retry_rate * 0.5:  # 半分以下
                patterns.append({
                    "type": "retry_pattern",
                    "action": action,
                    "context_var": var,
                    "problematic_value": val,
                    "retry_rate": retry_rate,
                    "opposite_retry_rate": opposite_retry_rate,
                    "evidence_count": total,
                    "site": site,
                })

    return patterns


async def detect_action_sequence_patterns(
    site: Optional[str] = None,
    min_occurrences: int = 3,
) -> List[Dict[str, Any]]:
    """
    アクション順序パターンを検出（user_id ベース）

    「アクションAの前にアクションBを実行するとリトライ率が下がる」パターンを検出。
    例: add-to-cart の前に login → リトライ率低下

    Args:
        site: 対象サイト（省略時は全サイト）
        min_occurrences: パターン認定に必要な最小発生回数

    Returns:
        検出されたパターンのリスト
    """
    events = await get_events_for_analysis(site=site, limit=5000)

    if len(events) < min_occurrences:
        return []

    patterns = []

    # user_id でグループ化（時系列順）
    users: Dict[str, List[LearningEvent]] = {}
    for event in events:
        if not event.user_id:
            continue
        if event.user_id not in users:
            users[event.user_id] = []
        users[event.user_id].append(event)

    # 各ユーザーを時系列でソート
    for user_id in users:
        users[user_id].sort(key=lambda e: e.created_at)

    # アクションペアの統計を収集
    # {(target_action, preceded_by_action): {"retry": N, "no_retry": M}}
    action_pairs: Dict[tuple, Dict[str, int]] = {}

    for user_id, user_events in users.items():
        for i, event in enumerate(user_events):
            target_action = event.action_name
            if target_action in ("click", "scroll", "type", "wait"):  # 低レベルアクションは除外
                continue

            # 直前10イベント内のアクションを確認
            preceded_by = set()
            for j in range(max(0, i - 10), i):
                prev = user_events[j].action_name
                if prev not in ("click", "scroll", "type", "wait"):
                    preceded_by.add(prev)

            # このアクションの後にリトライがあるか確認
            retry_detected = False
            for j in range(i + 1, min(i + 20, len(user_events))):
                if user_events[j].action_name == target_action:
                    retry_detected = True
                    break

            # 前にあったアクションごとに統計
            for prev_action in preceded_by:
                key = (target_action, prev_action)
                if key not in action_pairs:
                    action_pairs[key] = {"retry": 0, "no_retry": 0}

                if retry_detected:
                    action_pairs[key]["retry"] += 1
                else:
                    action_pairs[key]["no_retry"] += 1

    # パターン検出: 前にあるとリトライ率が下がるアクション
    for (target_action, prev_action), stats in action_pairs.items():
        total = stats["retry"] + stats["no_retry"]
        if total < min_occurrences:
            continue

        retry_rate_with = stats["retry"] / total

        # 前にない場合のリトライ率と比較
        # 簡略化: リトライ率が低ければ良いパターン
        if retry_rate_with <= 0.2:  # 20%以下のリトライ率
            patterns.append({
                "type": "action_sequence",
                "target_action": target_action,
                "should_precede": prev_action,
                "retry_rate_with": retry_rate_with,
                "evidence_count": total,
                "site": site,
            })

    return patterns


async def _validate_causal_relationship(
    pattern: Dict[str, Any],
    pattern_type: str,
) -> Dict[str, Any]:
    """
    LLMでパターンが因果関係かどうかを検証

    統計的な相関が因果関係として意味があるかをLLMで判定。
    例:
    - "logged_in=False → retry多い" → 因果的（ログインが必要な操作だから）
    - "cart_count=3 → retry多い" → 偶然（カート数と操作成功に因果関係なし）

    Args:
        pattern: 検出されたパターン
        pattern_type: "retry_pattern" or "action_sequence"

    Returns:
        {
            "is_causal": bool,
            "reason": str,
            "suggested_rule": Optional[Dict]  # 因果的な場合、推奨ルール
        }
    """
    if not settings.GOOGLE_GEMINI_API_KEY:
        # APIキーがない場合はスキップ（後方互換性）
        return {"is_causal": True, "reason": "LLM validation skipped (no API key)"}

    import google.generativeai as genai

    genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-2.5-flash")

    # パターンから重要な情報を抽出
    context_var = pattern.get("context_var", pattern.get("should_precede", "unknown"))
    problematic_value = pattern.get("problematic_value", "")
    action = pattern.get("action", pattern.get("target_action", "unknown"))

    prompt = f"""You are determining if a statistical correlation represents TRUE CAUSATION.

Pattern: When {context_var}={problematic_value}, action "{action}" fails frequently.

To determine causality, ask yourself:
1. Does {context_var} LOGICALLY affect whether {action} can succeed?
2. Would changing {context_var} actually prevent the failure?
3. Is there a MECHANISM by which {context_var} causes the failure?

If you cannot identify a logical mechanism, it's likely coincidental.

Reply JSON only:
{{"is_causal":true/false,"reason":"brief explanation","prerequisite":"what to do first, or null if not causal"}}"""

    # リトライロジック（最大3回）
    last_error = None
    for attempt in range(3):
        try:
            response = await model.generate_content_async(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.1,
                    max_output_tokens=8000,
                ),
            )

            content = response.text.strip()
            logger.debug(f"Raw LLM response: {repr(content[:300])}")

            # JSON部分を抽出
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            elif content.startswith("{"):
                pass  # Already JSON
            else:
                # JSONを探す
                start = content.find("{")
                end = content.rfind("}") + 1
                if start >= 0 and end > start:
                    content = content[start:end]

            logger.debug(f"Extracted JSON: {repr(content[:200])}")
            result = json.loads(content)
            logger.info(f"Causal validation: {context_var}={problematic_value} -> is_causal={result.get('is_causal')}")
            return result

        except json.JSONDecodeError as e:
            last_error = e
            logger.debug(f"Causal validation attempt {attempt+1} failed: {e}")
            await asyncio.sleep(0.5)  # 少し待ってリトライ
            continue
        except Exception as e:
            last_error = e
            break

    logger.warning(f"Causal validation failed after retries: {last_error}")
    # エラー時は保守的に false を返す（無効なルールを作らない）
    return {"is_causal": False, "reason": f"Validation error: {last_error}"}


async def analyze_and_learn(
    site: Optional[str] = None,
    min_occurrences: int = 3,
) -> Dict[str, Any]:
    """
    蓄積されたデータを分析し、ルールを学習（user_id ベース）

    定期的に実行して、新しいパターンを検出・ルール化する。
    リトライパターン（同じアクションの繰り返し）から因果関係を推論。

    Args:
        site: 対象サイト（省略時は全サイト）
        min_occurrences: パターン認定に必要な最小発生回数

    Returns:
        分析結果のサマリ
    """
    result = {
        "retry_patterns_detected": 0,
        "sequence_patterns_detected": 0,
        "rules_created": 0,
        "rules_updated": 0,
        "errors": [],
    }

    try:
        # リトライパターンを検出（user_id ベース）
        retry_patterns = await detect_retry_patterns(
            site=site,
            min_occurrences=min_occurrences,
        )
        result["retry_patterns_detected"] = len(retry_patterns)

        # 検出したパターンをLLMで因果検証してからルール化
        result["patterns_validated"] = 0
        result["patterns_rejected"] = 0

        for pattern in retry_patterns:
            try:
                # LLMで因果関係を検証
                validation = await _validate_causal_relationship(pattern, "retry_pattern")

                if not validation.get("is_causal", False):
                    # 因果関係なし → ルール化しない
                    logger.info(f"Pattern rejected (not causal): {pattern.get('context_var')}={pattern.get('problematic_value')}, reason: {validation.get('reason')}")
                    result["patterns_rejected"] += 1
                    continue

                result["patterns_validated"] += 1

                # LLMが提案した prerequisite を使用
                prerequisite = validation.get("prerequisite")
                if prerequisite and prerequisite != "null" and prerequisite.lower() != "none":
                    inferred_rule = {
                        "prerequisite": prerequisite,
                        "reason": validation.get("reason", ""),
                    }
                else:
                    # prerequisite がない場合はスキップ（無効なルールを作らない）
                    logger.info(f"Pattern validated but no prerequisite suggested: {pattern.get('context_var')}={pattern.get('problematic_value')}")
                    continue

                scope = {
                    "site": pattern.get("site"),
                    "action": pattern.get("action"),
                }
                scope = {k: v for k, v in scope.items() if v is not None}

                # confidence = 1 - retry_rate（リトライ率が低いほど良い）
                confidence = 1.0 - pattern["retry_rate"]

                rule = await upsert_learned_rule(
                    pattern_type="retry_pattern",
                    scope=scope,
                    observed_pattern={
                        "context_var": pattern["context_var"],
                        "problematic_value": pattern["problematic_value"],
                        "retry_rate": pattern["retry_rate"],
                        "causal_reason": validation.get("reason"),
                    },
                    inferred_rule=inferred_rule,
                    confidence=confidence,
                )

                if rule:
                    if rule.evidence_count == 1:
                        result["rules_created"] += 1
                    else:
                        result["rules_updated"] += 1

            except Exception as e:
                result["errors"].append(f"retry_pattern rule error: {e}")

        # アクション順序パターンを検出
        sequence_patterns = await detect_action_sequence_patterns(
            site=site,
            min_occurrences=min_occurrences,
        )
        result["sequence_patterns_detected"] = len(sequence_patterns)

        # 検出したパターンをLLMで因果検証してからルール化
        for pattern in sequence_patterns:
            try:
                # LLMで因果関係を検証
                validation = await _validate_causal_relationship(pattern, "action_sequence")

                if not validation.get("is_causal", False):
                    logger.info(f"Sequence pattern rejected: {pattern.get('should_precede')} -> {pattern.get('target_action')}, reason: {validation.get('reason')}")
                    result["patterns_rejected"] = result.get("patterns_rejected", 0) + 1
                    continue

                result["patterns_validated"] = result.get("patterns_validated", 0) + 1

                scope = {
                    "site": pattern.get("site"),
                    "action": pattern["target_action"],
                }
                scope = {k: v for k, v in scope.items() if v is not None}

                # confidence = 1 - retry_rate（リトライ率が低いほど良い）
                confidence = 1.0 - pattern["retry_rate_with"]

                # LLMが提案したルールを使用、なければ検出結果を使用
                suggested_rule = validation.get("suggested_rule")
                if suggested_rule and "should_do_first" in suggested_rule:
                    inferred_rule = suggested_rule
                else:
                    inferred_rule = {"should_do_first": [pattern["should_precede"]]}

                rule = await upsert_learned_rule(
                    pattern_type="action_sequence",
                    scope=scope,
                    observed_pattern={
                        "should_precede": pattern["should_precede"],
                        "retry_rate_with": pattern["retry_rate_with"],
                        "causal_reason": validation.get("reason"),
                    },
                    inferred_rule=inferred_rule,
                    confidence=confidence,
                )

                if rule:
                    if rule.evidence_count == 1:
                        result["rules_created"] += 1
                    else:
                        result["rules_updated"] += 1

            except Exception as e:
                result["errors"].append(f"action_sequence rule error: {e}")

        logger.info(
            f"Learning analysis complete: "
            f"{result['retry_patterns_detected']} retry patterns, "
            f"{result['sequence_patterns_detected']} sequence patterns, "
            f"{result['rules_created']} new rules, "
            f"{result['rules_updated']} updated rules"
        )

    except Exception as e:
        logger.error(f"Learning analysis failed: {e}")
        result["errors"].append(str(e))

    return result


# ============================================
# LLM 因果推論（ハイブリッド分析の一部）
# ============================================

async def _call_llm_for_inference(
    patterns: List[Dict[str, Any]],
    context_summary: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    LLMを呼び出してパターンから因果関係を推論

    SQL集計で得られたパターンをLLMに渡し、
    より高レベルな因果関係やアクションの推奨を生成。

    Args:
        patterns: SQL集計で検出されたパターン
        context_summary: サイト/スキルのコンテキスト情報

    Returns:
        LLMが推論した因果関係と推奨事項
    """
    if not patterns:
        return []

    try:
        import google.generativeai as genai

        # Gemini 2.5 Flash を使用
        if not settings.GOOGLE_GEMINI_API_KEY:
            logger.debug("GOOGLE_GEMINI_API_KEY not set, skipping LLM inference")
            return []

        genai.configure(api_key=settings.GOOGLE_GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = f"""Analyze these browser automation patterns and infer causal relationships.

Patterns:
{json.dumps(patterns, indent=2)}

Context:
{json.dumps(context_summary, indent=2)}

Return a JSON array. Each item should have:
- pattern_type: "causal_inference"
- cause: string (what causes the retry/failure)
- effect: string (what happens as a result)
- recommendation: string (actionable improvement)
- confidence: number 0-1
- affected_actions: string array

Output valid JSON array only."""

        response = await model.generate_content_async(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.3,
                max_output_tokens=2000,
                response_mime_type="application/json",
            ),
        )

        content = response.text

        # JSON部分を抽出（念のため）
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        inferences = json.loads(content.strip())
        logger.info(f"LLM inference returned {len(inferences)} causal relationships")
        return inferences

    except Exception as e:
        logger.warning(f"LLM inference failed (falling back to rule-based): {e}")
        return []


# ============================================
# 自動分析（セッション終了時トリガー）
# ============================================

_analysis_lock = asyncio.Lock()
_last_analysis_time: Optional[datetime] = None
_MIN_ANALYSIS_INTERVAL_SECONDS = 60  # 最小分析間隔（連続トリガー防止）


async def trigger_auto_analysis(
    session_id: str,
    site: Optional[str] = None,
) -> Dict[str, Any]:
    """
    セッション終了時に自動分析をトリガー

    連続呼び出しを防ぐため、最小間隔を設ける。
    分析は非同期で実行され、結果はログに記録。

    Args:
        session_id: 終了したセッションID
        site: 分析対象サイト（省略時は全サイト）

    Returns:
        分析結果（スキップされた場合はその理由）
    """
    global _last_analysis_time

    async with _analysis_lock:
        now = datetime.now()

        # 連続トリガー防止
        if _last_analysis_time:
            elapsed = (now - _last_analysis_time).total_seconds()
            if elapsed < _MIN_ANALYSIS_INTERVAL_SECONDS:
                logger.debug(f"Skipping auto-analysis: only {elapsed:.1f}s since last analysis")
                return {"skipped": True, "reason": f"min_interval ({_MIN_ANALYSIS_INTERVAL_SECONDS}s)"}

        _last_analysis_time = now

    logger.info(f"Starting auto-analysis for session {session_id}")

    try:
        # 基本分析（SQL集計）
        basic_result = await analyze_and_learn(site=site, min_occurrences=2)

        # パターンが検出された場合、LLM推論を追加
        if basic_result["retry_patterns_detected"] > 0 or basic_result["sequence_patterns_detected"] > 0:
            # 検出されたパターンを取得
            retry_patterns = await detect_retry_patterns(site=site, min_occurrences=2)
            sequence_patterns = await detect_action_sequence_patterns(site=site, min_occurrences=2)

            all_patterns = retry_patterns + sequence_patterns

            # LLM推論
            context_summary = {"site": site, "session_id": session_id}
            llm_inferences = await _call_llm_for_inference(all_patterns, context_summary)

            basic_result["llm_inferences"] = len(llm_inferences)

            # LLM推論結果をルール化
            for inference in llm_inferences:
                if inference.get("confidence", 0) >= 0.7:
                    await upsert_learned_rule(
                        pattern_type="llm_causal_inference",
                        scope={
                            "site": site,
                            "actions": inference.get("affected_actions", []),
                        },
                        observed_pattern={
                            "cause": inference.get("cause"),
                            "effect": inference.get("effect"),
                        },
                        inferred_rule={
                            "recommendation": inference.get("recommendation"),
                        },
                        confidence=inference.get("confidence", 0.7),
                    )
                    basic_result["rules_created"] = basic_result.get("rules_created", 0) + 1

        # ルールが作成/更新された場合、スキル更新を自動適用
        if basic_result.get("rules_created", 0) > 0 or basic_result.get("rules_updated", 0) > 0:
            try:
                from app.services import skill_updater

                # 提案を生成して自動適用（dry_run=False）
                update_result = await skill_updater.auto_update_skills(
                    min_confidence=0.3,  # 低い閾値で全て適用
                    dry_run=False,       # 実際に適用
                )

                basic_result["skill_updates"] = {
                    "proposals_generated": update_result.get("proposals_generated", 0),
                    "proposals_applied": update_result.get("proposals_applied", 0),
                    "errors": update_result.get("errors", []),
                }

                if update_result.get("proposals_applied", 0) > 0:
                    logger.info(
                        f"Auto-applied {update_result['proposals_applied']} skill updates"
                    )
            except Exception as e:
                logger.warning(f"Skill auto-update failed: {e}")
                basic_result["skill_update_error"] = str(e)

        # 低信頼度ルールを無効化（十分な証拠がある場合のみ）
        deactivated = await _deactivate_low_confidence_rules(threshold=0.3, min_evidence=5)
        basic_result["rules_deactivated"] = deactivated

        return basic_result

    except Exception as e:
        logger.error(f"Auto-analysis failed: {e}")
        return {"error": str(e)}


async def _deactivate_low_confidence_rules(
    threshold: float = 0.3,
    min_evidence: int = 5,
) -> int:
    """
    信頼度が閾値以下かつ十分な証拠があるルールを無効化

    データが増えても信頼度が低いままのルールは、
    因果関係がない可能性が高いため無効化する。

    Args:
        threshold: 無効化する信頼度の閾値
        min_evidence: 無効化に必要な最小証拠数（少数データでの誤無効化を防ぐ）

    Returns:
        無効化されたルール数
    """
    try:
        supabase = _get_supabase()

        # 低信頼度かつ十分な証拠があるルールを無効化
        result = supabase.table("learned_rules").update({
            "is_active": False,
        }).eq("is_active", True).lt("confidence", threshold).gte(
            "evidence_count", min_evidence
        ).execute()

        count = len(result.data) if result.data else 0
        if count > 0:
            logger.info(f"Deactivated {count} low-confidence rules (confidence < {threshold}, evidence >= {min_evidence})")
        return count

    except Exception as e:
        logger.error(f"Failed to deactivate low-confidence rules: {e}")
        return 0


async def get_learning_stats() -> Dict[str, Any]:
    """
    学習システムの統計情報を取得

    Returns:
        - total_events: 総イベント数
        - total_rules: 総ルール数
        - active_rules: アクティブなルール数
        - sites_tracked: 追跡中のサイト数
        - last_analysis: 最後の分析日時
    """
    try:
        supabase = _get_supabase()

        # イベント数
        events_result = supabase.table("learning_events").select("id", count="exact").execute()
        total_events = events_result.count if hasattr(events_result, 'count') else len(events_result.data)

        # ルール数
        rules_result = supabase.table("learned_rules").select("id, is_active").execute()
        total_rules = len(rules_result.data)
        active_rules = sum(1 for r in rules_result.data if r.get("is_active"))

        # サイト数
        sites_result = supabase.table("learning_events").select("site").execute()
        sites = set(r.get("site") for r in sites_result.data if r.get("site"))

        return {
            "total_events": total_events,
            "total_rules": total_rules,
            "active_rules": active_rules,
            "sites_tracked": len(sites),
            "sites": list(sites),
            "last_analysis": _last_analysis_time.isoformat() if _last_analysis_time else None,
        }

    except Exception as e:
        logger.error(f"Failed to get learning stats: {e}")
        return {"error": str(e)}
