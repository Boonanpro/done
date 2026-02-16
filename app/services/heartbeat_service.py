"""
Heartbeat Service - Danの定期的な自律起動

OpenClawスタイルのheartbeat: 定期的にDanが自律起動し、
記憶の整理・スキル提案・exec_codeによる自己拡張を行う。

設定は ~/.dan/workspace/HEARTBEAT.md で管理。
"""

import re
import asyncio
import logging
from datetime import datetime, time
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

WORKSPACE_DIR = Path.home() / ".dan" / "workspace"
HEARTBEAT_CONFIG_PATH = WORKSPACE_DIR / "HEARTBEAT.md"

DEFAULT_CONFIG = {
    "enabled": False,
    "interval_minutes": 30,
    "quiet_hours": "23:00-07:00",
    "max_runs_per_day": 20,
    "max_tool_calls": 10,
}

HEARTBEAT_PROMPT_PATH = WORKSPACE_DIR / "HEARTBEAT_PROMPT.md"

HEARTBEAT_PROMPT_FALLBACK = """あなたは自律的に起動しました。MEMORY.mdを確認し、特記事項があればメモを残してください。なければ「特記事項なし」と返してください。"""


def _load_heartbeat_prompt() -> str:
    """HEARTBEAT_PROMPT.mdから指示を読み込む。なければフォールバック。"""
    if HEARTBEAT_PROMPT_PATH.exists():
        try:
            return HEARTBEAT_PROMPT_PATH.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to load heartbeat prompt: {e}")
    return HEARTBEAT_PROMPT_FALLBACK


def _load_config() -> dict:
    """HEARTBEAT.mdから設定を読み込む"""
    config = DEFAULT_CONFIG.copy()

    if not HEARTBEAT_CONFIG_PATH.exists():
        return config

    try:
        text = HEARTBEAT_CONFIG_PATH.read_text(encoding="utf-8")
        for match in re.finditer(r"^- (\w+): (.+)$", text, re.MULTILINE):
            key, value = match.group(1), match.group(2).strip()
            if key == "enabled":
                config["enabled"] = value.lower() == "true"
            elif key == "interval_minutes":
                config["interval_minutes"] = int(value)
            elif key == "quiet_hours":
                config["quiet_hours"] = value
            elif key == "max_runs_per_day":
                config["max_runs_per_day"] = int(value)
            elif key == "max_tool_calls":
                config["max_tool_calls"] = int(value)
    except Exception as e:
        logger.warning(f"Failed to load heartbeat config: {e}")

    return config


def _in_quiet_hours(config: dict) -> bool:
    """現在が静音時間帯かどうか"""
    quiet = config.get("quiet_hours", "")
    if not quiet or "-" not in quiet:
        return False

    try:
        start_str, end_str = quiet.split("-")
        start_h, start_m = map(int, start_str.strip().split(":"))
        end_h, end_m = map(int, end_str.strip().split(":"))
        start = time(start_h, start_m)
        end = time(end_h, end_m)
        now = datetime.now().time()

        if start <= end:
            return start <= now <= end
        else:
            # 日をまたぐ場合（例: 23:00-07:00）
            return now >= start or now <= end
    except Exception:
        return False


async def _get_daily_run_count() -> int:
    """今日のheartbeat実行回数を取得"""
    try:
        from app.services.supabase_client import get_supabase_client
        client = get_supabase_client().client
        today = datetime.now().strftime("%Y-%m-%d")
        result = client.table("heartbeat_runs").select(
            "id", count="exact"
        ).gte("created_at", f"{today}T00:00:00").execute()
        return result.count or 0
    except Exception as e:
        logger.warning(f"Failed to get daily run count: {e}")
        return 0


async def _get_user_id() -> Optional[str]:
    """usersテーブルから最初のユーザーIDを取得"""
    try:
        from app.services.supabase_client import get_supabase_client
        client = get_supabase_client().client
        result = client.table("users").select("id").limit(1).execute()
        if result.data:
            return result.data[0]["id"]
    except Exception as e:
        logger.warning(f"Failed to get user id: {e}")
    return None


async def _log_run(user_id: str, result: dict):
    """実行結果をheartbeat_runsテーブルに記録"""
    try:
        from app.services.supabase_client import get_supabase_client
        client = get_supabase_client().client
        response_text = result.get("response", "")
        if len(response_text) > 5000:
            response_text = response_text[:5000]
        client.table("heartbeat_runs").insert({
            "user_id": user_id,
            "response": response_text,
            "tools_used": result.get("tool_results", []),
            "status": "error" if result.get("error") else "success",
            "error": result.get("error"),
        }).execute()
    except Exception as e:
        logger.warning(f"Failed to log heartbeat run: {e}")


async def _check_frontend_health() -> Optional[str]:
    """フロントエンド(localhost:3000)の状態を確認。正常ならNone、異常ならエラー情報を返す"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:3000", timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status >= 500:
                    body = await resp.text()
                    return f"HTTP {resp.status}: {body[:500]}"
                # 200でもエラーページの可能性をチェック
                body = await resp.text()
                if "Build Error" in body or "Module not found" in body or "Unhandled Runtime Error" in body:
                    return f"ビルドエラー検出: {body[:500]}"
                return None
    except aiohttp.ClientConnectorError:
        return "フロントエンド(localhost:3000)に接続できません。プロセスが停止している可能性があります。"
    except asyncio.TimeoutError:
        return "フロントエンド(localhost:3000)が応答しません（タイムアウト）。"
    except Exception as e:
        return f"フロントエンド確認中にエラー: {e}"


def _build_prompt(frontend_error: Optional[str] = None) -> str:
    """Heartbeatプロンプトを構築"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    instructions = _load_heartbeat_prompt()
    prompt = f"[Heartbeat] 自動チェックイン。現在時刻: {now}\n\n{instructions}"

    if frontend_error:
        prompt += f"""

⚠️ フロントエンド異常検出:
{frontend_error}

最優先で対応してください:
1. bash で frontend/src/ 内の最近変更されたファイルを確認する（git diff, git log）
2. エラー原因を特定する
3. 修正して画面を復旧させる
4. 修正後、画面が正常に表示されることを確認する
"""

    return prompt


async def run_heartbeat() -> dict:
    """
    Heartbeatを1回実行する

    Returns:
        実行結果 or {"skipped": "reason"}
    """
    config = _load_config()

    if not config["enabled"]:
        return {"skipped": "disabled"}

    if _in_quiet_hours(config):
        logger.debug("Heartbeat skipped: quiet hours")
        return {"skipped": "quiet_hours"}

    daily_count = await _get_daily_run_count()
    if daily_count >= config["max_runs_per_day"]:
        logger.debug(f"Heartbeat skipped: daily limit ({daily_count}/{config['max_runs_per_day']})")
        return {"skipped": "daily_limit"}

    user_id = await _get_user_id()
    if not user_id:
        logger.warning("Heartbeat skipped: no user found")
        return {"skipped": "no_user"}

    frontend_error = await _check_frontend_health()
    if frontend_error:
        logger.warning(f"Frontend health check failed: {frontend_error}")

    prompt = _build_prompt(frontend_error=frontend_error)

    try:
        from app.agent.v2.runner import create_runner

        runner = await create_runner(
            session_id=f"heartbeat-{user_id}",
            user_id=user_id,
            on_reasoning_step=None,
        )
        result = await runner.process_message(prompt)
        await _log_run(user_id, result)

        # 非trivialな結果をcompanionセッションに音声プッシュ
        response_text = result.get("response", "")
        if response_text and "特記事項なし" not in response_text:
            try:
                from app.services.voice_push import push_voice_message
                await push_voice_message(user_id, response_text)
            except Exception:
                pass

        logger.info("Heartbeat completed successfully")
        return result
    except Exception as e:
        logger.error(f"Heartbeat execution failed: {e}")
        await _log_run(user_id, {"error": str(e)})
        return {"error": str(e)}


async def heartbeat_loop():
    """
    Heartbeatメインループ（バックグラウンドタスク）

    起動後60秒待ってから、設定されたintervalで繰り返す。
    """
    # 起動直後は待機（他のサービスの初期化を待つ）
    await asyncio.sleep(60)
    logger.info("Heartbeat loop started")

    while True:
        config = _load_config()
        interval = config.get("interval_minutes", 30) * 60

        try:
            result = await run_heartbeat()
            if "skipped" in result:
                logger.debug(f"Heartbeat skipped: {result['skipped']}")
        except Exception as e:
            logger.error(f"Heartbeat loop error: {e}")

        await asyncio.sleep(interval)
