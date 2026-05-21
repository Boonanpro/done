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
_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


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


CHAT_SYSTEM_PROMPT = """あなたはダンの「ダン用Notion」を操作するAIアシスタントです。
ユーザーがチャットで指示を送ってきました。

# 利用可能な操作
ローカルで動いているバックエンドAPI (http://127.0.0.1:8000/api/v1/dan-notion) を Bash + curl で操作してください。
認証は環境変数 DAN_NOTION_JWT を Bearer ヘッダで使ってください: `-H "Authorization: Bearer $DAN_NOTION_JWT"`

# エンドポイント
- GET  /pages                                    全ルートページ
- GET  /blocks/{id}                              単一ブロック取得
- GET  /blocks/{id}/children                     子ブロック一覧
- POST /blocks                                   作成 {type, parent_id, properties, content, icon, tags, after_block_id}
- PATCH /blocks/{id}                             更新 {properties?, content?, icon?, is_starred?, tags?}
- DELETE /blocks/{id}                            削除（論理）
- POST /blocks/{id}/move                         移動 {parent_id, after_block_id, before_block_id}
- GET  /blocks/{id}/versions                     バージョン履歴
- POST /blocks/{id}/restore/{version}            指定バージョンに戻す
- POST /search   {query, limit}                  自然言語検索
- GET  /notifications                            通知一覧

# Block の type
page / paragraph / heading / bullet_list / numbered_list / checklist / task /
quote / code / divider / callout / image / video / audio / pdf / file / embed /
email / calendar_event / table / database / bookmark / invoice / meeting_note / proposal_ref

# ページ/フォルダ規約 (重要)
- ルートページ = テキストエディタ的な文書ページ (ビュー切替なし)
- フォルダ = メディア整理用のサブページ。以下の両方を必ず設定すること:
    properties.is_folder = true
    properties.view_mode = 'grid'   (初期表示。ユーザーが後で list に切替可能)
  例: {"type":"page","parent_id":"<root>","properties":{"title":"請求書","is_folder":true,"view_mode":"grid"},"icon":"💳"}
- フォルダ配下にさらにサブフォルダを作る場合も同じ規約を適用
- メディアファイル (image/video/pdf/file) はフォルダ配下に入れる
- 絵文字の二重表示を避けるため、properties.title には絵文字を入れないこと。
  代わりに icon フィールドに絵文字だけを設定する
  ❌ {"title":"📄 PDF資料","icon":"📄"}
  ✅ {"title":"PDF資料","icon":"📄"}

# 振る舞い
1. ユーザーの依頼を理解し、必要なAPI呼び出しを計画
2. Bash ツールで curl を実行
3. 結果を簡潔に報告（実行したアクション + 作成/更新したブロックのIDやURL）
4. 不可逆な操作（削除、外部送信）を行う場合は最初にユーザーへ確認のメッセージを返してから実行

# 制約
- 必ず日本語で応答する
- 余計な前置きはせず、簡潔に
"""


class AutopilotRunner:
    """単一の trigger_run を実行するヘッドレスエージェント"""

    def __init__(
        self,
        user_id: str,
        trigger: dict,
        payload: dict,
        mode: str = "trigger",
        chat_message: Optional[str] = None,
        user_jwt: Optional[str] = None,
    ):
        self.sb = get_supabase_client().client
        self.user_id = user_id
        self.trigger = trigger
        self.payload = payload
        self.mode = mode
        self.chat_message = chat_message
        self.user_jwt = user_jwt
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
        if self.mode == "chat" and self.chat_message:
            return f"# ユーザーからのチャット\n{self.chat_message}\n"

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
                    self._trace("thinking", {"text": block.get("thinking", "")[:20000]})
                elif btype == "text":
                    self._trace("message", {"text": block.get("text", "")[:20000]})
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
                    text = content if isinstance(content, str) else json.dumps(content)[:3000]
                    self._trace("tool_result", {
                        "tool_use_id": block.get("tool_use_id"),
                        "text": text[:3000],
                    })
            return

        if ev_type == "result":
            self._trace("complete", {
                "result": ev.get("result", "")[:20000],
                "is_error": ev.get("is_error", False),
            })

    def _spawn_cli(self, prompt: str, resume_session_id: Optional[str] = None) -> tuple[int, dict]:
        """CLI を起動して stream-json を逐次パース。終了コードと最終結果を返す"""
        claude_cmd, cli_js = _resolve_claude_cli()
        if not claude_cmd:
            self._trace("error", {"message": "claude CLI が見つかりません"})
            return 127, {"error": "cli_not_found"}

        system_prompt = CHAT_SYSTEM_PROMPT if self.mode == "chat" else AUTOPILOT_SYSTEM_PROMPT

        cmd = [claude_cmd] + ([cli_js] if cli_js else []) + [
            "-p", prompt,
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            "--dangerously-skip-permissions",
            "--model", "opus",
            "--max-turns", "50",
            "--append-system-prompt", system_prompt,
        ]

        if resume_session_id:
            cmd.extend(["--resume", resume_session_id])

        env = _build_env()
        if self.user_jwt:
            env["DAN_NOTION_JWT"] = self.user_jwt
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
                creationflags=_NO_WINDOW,
            )
        except Exception as e:
            self._trace("error", {"message": f"failed to spawn CLI: {e}"})
            return 1, {"error": str(e)}

        assert proc.stdout is not None
        assert proc.stderr is not None

        # stderr を別スレッドで吸い取る
        stderr_lines: list[str] = []

        def _drain_stderr():
            try:
                for line in proc.stderr:  # type: ignore
                    stderr_lines.append(line.rstrip())
            except Exception:
                pass

        threading.Thread(target=_drain_stderr, daemon=True).start()

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

        # 失敗していたら stderr を error trace に保存
        is_failure = rc != 0 or last_result.get("is_error") or not last_result.get("text")
        if is_failure:
            stderr_text = "\n".join(stderr_lines)[-2000:]
            self._trace("error", {
                "phase": "cli_exit",
                "rc": rc,
                "stderr": stderr_text,
                "last_result": last_result,
            })
            # session not found 判定: stderr に該当メッセージがあれば
            lower = stderr_text.lower()
            session_invalid = any(
                kw in lower
                for kw in (
                    "no conversation found with session id",
                    "could not find session",
                    "session not found",
                    "invalid session",
                    "session_id",
                )
            )
            last_result["_session_invalid"] = session_invalid
            last_result["_stderr"] = stderr_text

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


def execute_chat_async(
    user_id: str, trigger: dict, message: str, user_jwt: str
) -> str:
    """チャットからの呼び出し。run_id を作成してすぐ返し、別スレッドで実行

    文脈保持: trigger.config.last_session_id があれば --resume で継続し、
             完了時に最新の cli_session_id を上書き保存する
    """
    runner = AutopilotRunner(
        user_id=user_id,
        trigger=trigger,
        payload={"kind": "chat", "message": message},
        mode="chat",
        chat_message=message,
        user_jwt=user_jwt,
    )
    runner._create_run()
    run_id = runner.run_id
    runner._trace("message", {"role": "user", "text": message[:20000]})

    resume_session_id: Optional[str] = (trigger.get("config") or {}).get("last_session_id")

    def _worker():
        try:
            prompt = runner._build_prompt()
            attempt = 0
            result: dict = {}
            resume = resume_session_id
            max_attempts = 2
            while attempt < max_attempts:
                runner._trace("decision", {
                    "phase": "attempt",
                    "attempt": attempt + 1,
                    "resume": bool(resume),
                })
                rc, result = runner._spawn_cli(prompt, resume_session_id=resume)

                # 成功条件: rc=0 かつ is_error=false かつ text 非空
                text_ok = bool(result.get("text"))
                if rc == 0 and not result.get("is_error") and text_ok:
                    runner._finish_run("succeeded", result)
                    # 次回のために session_id を保存
                    if runner.cli_session_id:
                        try:
                            from app.services.supabase_client import get_supabase_client
                            sb = get_supabase_client().client
                            cfg = dict(trigger.get("config") or {})
                            cfg["last_session_id"] = runner.cli_session_id
                            sb.table("triggers").update({"config": cfg}).eq("id", trigger["id"]).execute()
                        except Exception as e:
                            logger.warning("failed to persist last_session_id: %s", e)
                    return

                attempt += 1
                # リトライの resume 判定:
                # - stderr に session 無効を示すパターンがあれば resume を外す
                # - それ以外は resume を維持して文脈を保つ
                if result.get("_session_invalid"):
                    runner._trace("decision", {"phase": "resume_drop", "reason": "session_invalid"})
                    resume = None

            runner._finish_run(
                "failed",
                result,
                error=(result.get("_stderr") or result.get("text") or f"rc={rc}")[:1000],
            )
        except Exception as e:
            logger.exception("chat worker crashed")
            try:
                runner._finish_run("failed", {}, error=str(e)[:500])
            except Exception:
                pass

    t = threading.Thread(target=_worker, daemon=True, name=f"chat-{run_id}")
    t.start()
    return run_id
