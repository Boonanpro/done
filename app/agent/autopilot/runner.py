"""ダン用Notion: Autopilot Runner

Claude Code CLI を `-p --output-format stream-json` モードで起動し、
イベント駆動の自律エージェントループ (CMAライク) を実現する。

ポイント:
  - ANTHROPIC_API_KEY を env から削除して Max 定額プランで動かす
  - stream-json を逐次パースし、agent_traces にリアルタイム保存
  - 思考プロセス (thinking) / ツール呼び出し / 結果 / 自己修復 を全てトレース
  - エラー時は最大3回まで自己修復ループ (reasoning付き再投入)
  - trigger_runs を running → succeeded/failed に遷移

既存の app/agent/cli_runner.py を参考に簡略化したヘッドレス版。
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


# 自律エージェント用のシステムプロンプト
AUTOPILOT_SYSTEM_PROMPT = """あなたはダンの自律エージェントです。
ユーザー定義のトリガーが発火し、あなたに自律的なタスクが委ねられました。

原則:
1. ユーザーの介入なしに、必要な調査・判断・実行を行ってください
2. 思考プロセスを明示的に説明してください (UIで可視化されます)
3. エラーが発生したら原因を分析し、自己修復を試みてください
4. 不可逆な操作 (送信/購入/削除) を行う場合は dan_notifications テーブルに通知を作成してユーザーの承認を待ってください
5. 完了したら結果を JSON 形式で要約してください

利用可能な情報源: dan-notion blocks, gmail, calendar, collab messages
"""


def _resolve_claude_cli() -> tuple[Optional[str], Optional[str]]:
    """Claude CLI の実行パスを解決する (cli_runner.py と同様)"""
    claude_path = shutil.which("claude")
    if not claude_path:
        return None, None
    if claude_path.lower().endswith(".cmd"):
        node_path = shutil.which("node")
        npm_dir = os.path.dirname(claude_path)
        cli_js = os.path.join(
            npm_dir, "node_modules", "@anthropic-ai", "claude-code", "cli.js"
        )
        if node_path and os.path.exists(cli_js):
            return node_path, cli_js
        return claude_path, None
    return claude_path, None


def _build_env() -> dict:
    """ANTHROPIC_API_KEY を削除して Max 定額プランを強制"""
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "ANTHROPIC_API_KEY")}
    env["CLAUDE_CODE_ENABLE_TASKS"] = "true"
    from app.config import settings
    for key, val in [
        ("SUPABASE_URL", settings.SUPABASE_URL),
        ("SUPABASE_KEY", settings.SUPABASE_KEY),
        ("SUPABASE_SERVICE_ROLE_KEY", settings.SUPABASE_SERVICE_ROLE_KEY),
    ]:
        if val and key not in env:
            env[key] = val
    return env


class AutopilotRunner:
    """単一の trigger_run を実行するヘッドレスエージェント"""

    def __init__(self, user_id: str, trigger: dict, payload: dict):
        self.sb = get_supabase_client().client
        self.user_id = user_id
        self.trigger = trigger
        self.payload = payload
        self.run_id: Optional[str] = None
        self.cli_session_id: Optional[str] = None

    # ============================================================
    # トレース保存
    # ============================================================

    def _trace(self, event_type: str, content: dict[str, Any]) -> None:
        try:
            self.sb.table("agent_traces").insert({
                "user_id": self.user_id,
                "trigger_run_id": self.run_id,
                "agent_name": f"autopilot:{self.trigger['name']}",
                "event_type": event_type,
                "content": content,
            }).execute()
        except Exception as e:
            logger.warning("trace insert failed: %s", e)

    def _create_run(self) -> str:
        res = self.sb.table("trigger_runs").insert({
            "trigger_id": self.trigger["id"],
            "user_id": self.user_id,
            "status": "running",
            "payload": self.payload,
        }).execute()
        run = res.data[0]
        self.run_id = run["id"]
        return self.run_id

    def _finish_run(self, status: str, result: dict, error: Optional[str] = None) -> None:
        update = {
            "status": status,
            "result": result,
            "finished_at": datetime.now(timezone.utc).isoformat(),
        }
        if error:
            update["error"] = error
        if self.cli_session_id:
            update["cli_session_id"] = self.cli_session_id
        self.sb.table("trigger_runs").update(update).eq("id", self.run_id).execute()

        # トリガー側の last_fired_at / fire_count を更新
        try:
            self.sb.rpc("noop", {}).execute() if False else None
            self.sb.table("triggers").update({
                "last_fired_at": datetime.now(timezone.utc).isoformat(),
                "fire_count": (self.trigger.get("fire_count") or 0) + 1,
            }).eq("id", self.trigger["id"]).execute()
        except Exception as e:
            logger.warning("trigger fire_count update failed: %s", e)

    # ============================================================
    # プロンプト構築
    # ============================================================

    def _build_prompt(self) -> str:
        """トリガー設定とペイロードからプロンプトを構築"""
        actions_desc = json.dumps(self.trigger.get("actions") or [], ensure_ascii=False, indent=2)
        payload_desc = json.dumps(self.payload, ensure_ascii=False, indent=2)
        return f"""# トリガー: {self.trigger['name']}
{self.trigger.get('description') or ''}

## イベントペイロード
```json
{payload_desc}
```

## 実行すべきアクション
```json
{actions_desc}
```

このイベントに対して、上記アクションを順に実行してください。
完了したら結果を簡潔に報告してください。
"""

    # ============================================================
    # CLI 実行 + イベント解析
    # ============================================================

    def _parse_event(self, line: str) -> None:
        """stream-json の 1行をパースして agent_traces に保存"""
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return

        ev_type = ev.get("type")

        if ev_type == "system" and ev.get("subtype") == "init":
            self.cli_session_id = ev.get("session_id")
            self._trace("decision", {"phase": "init", "session_id": self.cli_session_id})
            return

        if ev_type == "assistant":
            msg = ev.get("message", {})
            for block in msg.get("content", []):
                btype = block.get("type")
                if btype == "thinking":
                    self._trace("thinking", {"text": block.get("thinking", "")[:2000]})
                elif btype == "text":
                    self._trace("message", {"text": block.get("text", "")[:2000]})
                elif btype == "tool_use":
                    self._trace("tool_call", {
                        "tool": block.get("name"),
                        "input": block.get("input"),
                        "tool_use_id": block.get("id"),
                    })
            return

        if ev_type == "user":
            msg = ev.get("message", {})
            for block in msg.get("content", []):
                if block.get("type") == "tool_result":
                    content = block.get("content")
                    text = content if isinstance(content, str) else json.dumps(content)[:1000]
                    self._trace("tool_result", {
                        "tool_use_id": block.get("tool_use_id"),
                        "text": text[:1500],
                    })
            return

        if ev_type == "result":
            self._trace("complete", {
                "result": ev.get("result", "")[:2000],
                "is_error": ev.get("is_error", False),
            })

    def _spawn_cli(self, prompt: str) -> tuple[int, dict]:
        """CLI を起動して stream-json を逐次パース。終了コードと最終結果を返す"""
        claude_cmd, cli_js = _resolve_claude_cli()
        if not claude_cmd:
            self._trace("error", {"message": "claude CLI が見つかりません"})
            return 127, {"error": "cli_not_found"}

        cmd = [claude_cmd] + ([cli_js] if cli_js else []) + [
            "-p", prompt,
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", "opus",
            "--max-turns", "50",
        ]

        env = _build_env()
        last_result: dict = {}

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                text=True,
                encoding="utf-8",
                bufsize=1,
            )
        except Exception as e:
            self._trace("error", {"message": f"failed to spawn CLI: {e}"})
            return 1, {"error": str(e)}

        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            self._parse_event(line)
            try:
                ev = json.loads(line)
                if ev.get("type") == "result":
                    last_result = {
                        "text": ev.get("result", ""),
                        "is_error": ev.get("is_error", False),
                    }
            except json.JSONDecodeError:
                pass

        rc = proc.wait()
        return rc, last_result

    # ============================================================
    # メインループ (自己修復付き)
    # ============================================================

    def execute(self, max_repair: int = 2) -> dict:
        """trigger_run を作成 → CLI 起動 → 結果保存"""
        self._create_run()
        prompt = self._build_prompt()

        attempt = 0
        last_error: Optional[str] = None
        result: dict = {}

        while attempt <= max_repair:
            self._trace("decision", {"phase": "attempt", "attempt": attempt + 1})
            rc, result = self._spawn_cli(prompt)

            if rc == 0 and not result.get("is_error"):
                self._finish_run("succeeded", result)
                return {"status": "succeeded", "result": result}

            last_error = result.get("text") or f"CLI exit code {rc}"
            attempt += 1
            if attempt <= max_repair:
                self._trace("self_repair", {
                    "attempt": attempt,
                    "previous_error": last_error[:500],
                })
                # 自己修復用にプロンプトに失敗情報を追記
                prompt = (
                    self._build_prompt()
                    + f"\n\n## 前回の試行で発生したエラー\n{last_error}\n\n原因を分析して再試行してください。"
                )

        self._finish_run("failed", result, error=last_error)
        return {"status": "failed", "error": last_error}


def execute_trigger(user_id: str, trigger: dict, payload: dict | None = None) -> dict:
    """トリガーを単発実行 (Celery タスクから呼ばれる)"""
    runner = AutopilotRunner(user_id, trigger, payload or {})
    return runner.execute()


def execute_trigger_async(user_id: str, trigger: dict, payload: dict | None = None) -> str:
    """別スレッドで非同期実行する。FastAPI からの手動発火用"""
    run_holder: dict = {}

    def _worker():
        try:
            run_holder["result"] = execute_trigger(user_id, trigger, payload)
        except Exception as e:
            logger.exception("autopilot worker crashed")
            run_holder["error"] = str(e)

    t = threading.Thread(target=_worker, daemon=True, name=f"autopilot-{trigger['id']}")
    t.start()
    return f"started:{trigger['id']}"
