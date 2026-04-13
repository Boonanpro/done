"""ダン用Notion: Autopilot Celery タスク

役割:
  1. 30秒ごとに triggers をポーリングし、発火条件を満たすものを検出
  2. 検出したトリガーを Celery タスクとして dispatch
  3. AutopilotRunner で実行 (Claude Code CLI -p モード)

トリガー種別ごとの発火条件:
  - cron       : config.cron_expr の次回実行時刻を超えた
  - gmail      : 前回チェック後に config.query にマッチする新着メールあり
  - calendar   : config.minutes_before 後に予定がある
  - block_changed: 前回チェック後に config.parent_id 配下の blocks が更新された
  - manual     : ユーザーが手動発火した時のみ (ここではスキップ)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from app.agent.autopilot.runner import execute_trigger
from app.services.supabase_client import get_supabase_client
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="autopilot.dispatch_due_triggers")
def dispatch_due_triggers() -> dict:
    """発火条件を満たすトリガーを検出して実行キューに入れる"""
    sb = get_supabase_client().client
    triggers = (
        sb.table("triggers")
        .select("*")
        .eq("is_enabled", True)
        .execute()
        .data
        or []
    )

    fired = 0
    for trig in triggers:
        try:
            payload = _check_trigger(sb, trig)
            if payload is None:
                continue
            run_one_trigger.delay(trig["user_id"], trig, payload)
            fired += 1
        except Exception as e:
            logger.exception("trigger %s check failed: %s", trig["id"], e)

    return {"checked": len(triggers), "fired": fired}


@celery_app.task(name="autopilot.run_one_trigger", queue="default")
def run_one_trigger(user_id: str, trigger: dict, payload: dict) -> dict:
    """単一トリガーを実行する。AutopilotRunner に処理を委譲"""
    return execute_trigger(user_id, trigger, payload)


# ============================================================
# 各種トリガーの発火条件チェック
# ============================================================

def _check_trigger(sb, trig: dict) -> dict[str, Any] | None:
    """
    トリガーを検査し、発火させるなら payload を返す。
    発火しないなら None を返す。
    """
    kind = trig["kind"]
    config = trig.get("config") or {}
    last = trig.get("last_fired_at")
    last_dt = _parse_dt(last) if last else None

    if kind == "cron":
        return _check_cron(config, last_dt)

    if kind == "gmail":
        return _check_gmail(sb, trig["user_id"], config, last_dt)

    if kind == "block_changed":
        return _check_block_changed(sb, trig["user_id"], config, last_dt)

    if kind == "calendar":
        return _check_calendar(sb, trig["user_id"], config, last_dt)

    # manual / chat_command / collab はイベント駆動 (push) のためここではスキップ
    return None


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _check_cron(config: dict, last_dt: datetime | None) -> dict | None:
    """
    config = {"interval_seconds": 3600}  または
    config = {"cron_expr": "0 9 * * *"}
    """
    now = datetime.now(timezone.utc)
    if "interval_seconds" in config:
        interval = int(config["interval_seconds"])
        if last_dt is None or (now - last_dt).total_seconds() >= interval:
            return {"fired_at": now.isoformat(), "kind": "cron"}
        return None

    if "cron_expr" in config:
        try:
            from croniter import croniter
            base = last_dt or now
            it = croniter(config["cron_expr"], base)
            next_run = it.get_next(datetime)
            if next_run <= now:
                return {"fired_at": now.isoformat(), "cron_expr": config["cron_expr"]}
        except ImportError:
            logger.warning("croniter not installed, skipping cron trigger")
    return None


def _check_gmail(sb, user_id: str, config: dict, last_dt: datetime | None) -> dict | None:
    """
    config = {"query": "from:invoice@", "table": "gmail_messages"}
    既存の gmail_messages テーブルを参照して新着があれば payload を返す。
    """
    table = config.get("table", "gmail_messages")
    query_filter = config.get("query", "")
    try:
        q = sb.table(table).select("*").eq("user_id", user_id)
        if last_dt:
            q = q.gt("created_at", last_dt.isoformat())
        if "from" in query_filter:
            sender = query_filter.split("from:", 1)[1].strip().split()[0]
            q = q.ilike("from_address", f"%{sender}%")
        rows = q.limit(20).execute().data or []
        if not rows:
            return None
        return {"kind": "gmail", "matched_count": len(rows), "messages": rows[:5]}
    except Exception as e:
        logger.warning("gmail check failed: %s", e)
        return None


def _check_block_changed(sb, user_id: str, config: dict, last_dt: datetime | None) -> dict | None:
    parent_id = config.get("parent_id")
    q = (
        sb.table("blocks")
        .select("id, type, updated_at")
        .eq("user_id", user_id)
        .is_("deleted_at", "null")
    )
    if parent_id:
        q = q.eq("parent_id", parent_id)
    if last_dt:
        q = q.gt("updated_at", last_dt.isoformat())
    rows = q.limit(20).execute().data or []
    if not rows:
        return None
    return {"kind": "block_changed", "changed_count": len(rows), "blocks": rows[:5]}


def _check_calendar(sb, user_id: str, config: dict, last_dt: datetime | None) -> dict | None:
    # 既存の calendar_events テーブルを想定。詳細実装は preset triggers 側に委ねる
    minutes_before = int(config.get("minutes_before", 60))
    return {"kind": "calendar", "minutes_before": minutes_before}


# ============================================================
# Celery Beat スケジュール
# ============================================================

celery_app.conf.beat_schedule = celery_app.conf.beat_schedule or {}
celery_app.conf.beat_schedule.update({
    'autopilot-dispatch-every-30s': {
        'task': 'autopilot.dispatch_due_triggers',
        'schedule': 30.0,
    },
})

# task_handlers から import されるよう include に追加
celery_app.conf.update(
    include=list(set((celery_app.conf.include or []) + ["app.tasks.autopilot_tasks"]))
)
