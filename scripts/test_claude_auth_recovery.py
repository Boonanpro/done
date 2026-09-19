# -*- coding: utf-8 -*-
"""Claude CLI ログイン切れの検知と .env トークン注入の回帰テスト。

背景 (2026-09-19): ダンコアが使う `claude` CLI の Max ログインが失効し、Claude を
使う部屋が全部「CLI exited with code 1」相当で黙って使えなくなった。
このテストは実 `claude` を使わず、以下を検証する:

  (1) _is_auth_error_text — CLI の典型的なログイン切れ文言だけを拾う
  (2) _inject_claude_cli_auth — .env の CLAUDE_CODE_OAUTH_TOKEN が CLI env に入る
      （プロセス環境変数が優先 / 未設定なら何もしない）
  (3) StreamingSession.raw_tail — result を出さずに死んだプロセスの非JSON行
      (例: "Not logged in · Please run /login") を後から参照できる
"""
import os
import sys
import tempfile
import types
from pathlib import Path

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJ)

try:  # pydantic が無い環境（リモートサンドボックス）では settings をスタブ
    import app.config  # noqa: F401
except Exception:
    stub = types.ModuleType("app.config")
    stub.settings = types.SimpleNamespace(
        CLAUDE_CODE_OAUTH_TOKEN="", SUPABASE_URL="", SUPABASE_KEY="", SUPABASE_SERVICE_ROLE_KEY="",
    )
    sys.modules["app.config"] = stub

import app.agent.cli_runner as cr  # noqa: E402
from app.agent.streaming_session import StreamingSession  # noqa: E402


def test_auth_error_detection():
    positives = [
        "Not logged in · Please run /login",
        "Invalid API key · Please run /login",
        "OAuth token has expired · Please run /login",
        'API Error: 401 {"type":"error","error":{"type":"authentication_error","message":"Invalid authentication credentials"}}',
    ]
    negatives = [
        "",
        None,
        "API Error: 400 messages.3.content.0: thinking blocks cannot be modified",
        "Tool call could not be parsed",
        "ユーザーのログインページを開きました",  # 通常の会話に出る「ログイン」は拾わない
        "git push failed: remote: Permission denied (403)",
    ]
    for t in positives:
        assert cr._is_auth_error_text(t), f"should detect: {t!r}"
    for t in negatives:
        assert not cr._is_auth_error_text(t), f"false positive: {t!r}"
    assert "claude login" in cr._recovery_message("auth_expired", "ja")
    assert "CLAUDE_CODE_OAUTH_TOKEN" in cr._recovery_message("auth_expired", "en")
    print("[OK] auth error detection")


def test_token_injection():
    with tempfile.TemporaryDirectory() as td:
        orig_root = cr.PROJECT_ROOT
        cr.PROJECT_ROOT = Path(td)
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        try:
            # (a) .env 無し → 何も注入しない
            env = {}
            cr._inject_claude_cli_auth(env)
            assert "CLAUDE_CODE_OAUTH_TOKEN" not in env
            # (b) .env にトークン → 注入される（引用符・コメント行も処理）
            (Path(td) / ".env").write_text(
                "# comment\nSUPABASE_URL=x\nCLAUDE_CODE_OAUTH_TOKEN=\"sk-ant-oat01-dotenv\"\n",
                encoding="utf-8",
            )
            env = {}
            cr._inject_claude_cli_auth(env)
            assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-dotenv", env
            # (c) プロセス環境変数（=既に env に入っている）が優先
            env = {"CLAUDE_CODE_OAUTH_TOKEN": "sk-ant-oat01-env"}
            cr._inject_claude_cli_auth(env)
            assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat01-env"
        finally:
            cr.PROJECT_ROOT = orig_root
    print("[OK] token injection from .env")


_FAKE = r'''
import sys
sys.stdin.readline()
sys.stdout.write("Not logged in · Please run /login\n")
sys.stdout.flush()
sys.exit(1)
'''


def test_raw_tail_after_logged_out_exit():
    with tempfile.TemporaryDirectory() as td:
        fake = os.path.join(td, "fake_cli.py")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(_FAKE)
        s = StreamingSession("room-auth", lambda: [sys.executable, fake], dict(os.environ), td)
        res = s.run_turn("hi", lambda ev: None, timeout=10)
        assert res is None, res
        assert not s.is_alive()
        assert cr._is_auth_error_text(s.raw_tail()), s.raw_tail()
    print("[OK] raw_tail captures logged-out output")


if __name__ == "__main__":
    test_auth_error_detection()
    test_token_injection()
    test_raw_tail_after_logged_out_exit()
    print("ALL OK")
