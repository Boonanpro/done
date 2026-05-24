"""gpt-realtime-2 Realtime API アクセス診断スクリプト。

OPENAI_API_KEY が Realtime API を使えるか、音声レイヤーで使う
本番セッション設定（delegate_to_dan ツール込み）が通るかを確認する。

実行: python scripts/check_realtime.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx

from app.config import settings
from app.services.realtime_service import (
    CLIENT_SECRETS_ENDPOINT,
    REALTIME_MODEL,
    build_session_config,
)


def post(session: dict) -> tuple[int, object]:
    """client_secrets エンドポイントにセッション設定を投げて結果を返す。"""
    resp = httpx.post(
        CLIENT_SECRETS_ENDPOINT,
        headers={
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        json={"session": session},
        timeout=30.0,
    )
    try:
        return resp.status_code, resp.json()
    except Exception:
        return resp.status_code, resp.text


def main() -> int:
    if not settings.OPENAI_API_KEY:
        print("NG: OPENAI_API_KEY が未設定です（.env を確認）")
        return 1
    key = settings.OPENAI_API_KEY
    print(f"OPENAI_API_KEY: ...{key[-6:]}  (長さ {len(key)})")

    # [1] 最小構成 — キー自体に Realtime アクセス権があるか
    print("\n[1] 最小構成でトークン発行をテスト...")
    status, body = post({"type": "realtime", "model": REALTIME_MODEL})
    print(f"  HTTP {status}")
    if status != 200:
        print(f"  応答: {json.dumps(body, ensure_ascii=False)[:800]}")
        print(f"\nNG: このキーは Realtime API（{REALTIME_MODEL}）を使えません。")
        print("    → platform.openai.com で Realtime アクセスのある API キーが必要です。")
        return 1
    value = body.get("value", "") if isinstance(body, dict) else ""
    print(f"  OK: ephemeral key 発行成功（prefix={value[:3]}）")

    # [2] 本番セッション設定（realtime_service.build_session_config と同一）
    print("\n[2] delegate_to_dan ツール込みの本番構成をテスト...")
    status, body = post(build_session_config())
    print(f"  HTTP {status}")
    if status != 200:
        print(f"  応答: {json.dumps(body, ensure_ascii=False)[:1200]}")
        print("\n注意: 最小構成は通ったが本番構成が失敗。build_session_config を直す必要あり。")
        return 2
    print("  OK: 本番構成でもトークン発行成功")
    if isinstance(body, dict):
        eff = body.get("session", {})
        print(f"  有効セッション（正規化後）: {json.dumps(eff, ensure_ascii=False)[:1800]}")
    print("\nOK: gpt-realtime-2 をこのキーで利用できます。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
