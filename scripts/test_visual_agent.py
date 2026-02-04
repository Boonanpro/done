"""
VisualAgent 動作確認テスト

テストケース1: DuckDuckGo検索で「天気」と検索
（Googleは自動化検出でCAPTCHAが出るため、DuckDuckGoを使用）
"""

import asyncio
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.executors.visual.agent import VisualAgent
from app.executors.visual.recorder import BrowserRecorder


async def test_duckduckgo_search():
    """テストケース1: DuckDuckGo検索"""
    print("=" * 60)
    print("テストケース1: DuckDuckGoで「天気」と検索")
    print("=" * 60)

    # レコーダーとエージェントを作成
    recorder = BrowserRecorder(user_id="test_user")
    agent = VisualAgent(recorder=recorder, max_steps=10)

    # タスクを実行
    result = await agent.execute_task(
        task="DuckDuckGoで「天気」と検索して、検索結果を確認する",
        site="duckduckgo.com",
        initial_url="https://duckduckgo.com",
    )

    print("\n" + "=" * 60)
    print("結果:")
    print("=" * 60)
    print(f"Success: {result.get('success')}")
    print(f"Message: {result.get('message', result.get('error', 'N/A'))}")
    print(f"Steps: {result.get('steps', 'N/A')}")
    print(f"Tokens: {result.get('total_tokens', 'N/A')}")

    # ログファイルの確認
    if recorder.session:
        print(f"\nSession ID: {recorder.session.id}")
        print(f"Steps recorded: {len(recorder.session.steps)}")

        # 保存されたファイルを確認
        from app.executors.visual.recorder import LOGS_DIR
        session_dir = LOGS_DIR / recorder.session.id
        if session_dir.exists():
            print(f"\nLog directory: {session_dir}")
            for f in session_dir.iterdir():
                print(f"  - {f.name}")

    return result


if __name__ == "__main__":
    result = asyncio.run(test_duckduckgo_search())
    sys.exit(0 if result.get("success") else 1)
