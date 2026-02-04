"""
VisualAgent 動作確認テスト

テストケース3: Amazonで商品詳細ページまで遷移
- 検索
- スクロール（必要な場合）
- 商品クリック
- 詳細ページ確認
"""

import asyncio
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.executors.visual.agent import VisualAgent
from app.executors.visual.recorder import BrowserRecorder


async def test_amazon_product_detail():
    """テストケース3: Amazon商品詳細ページ遷移"""
    print("=" * 60)
    print("テストケース3: Amazonで商品詳細ページまで遷移")
    print("=" * 60)

    # レコーダーとエージェントを作成
    recorder = BrowserRecorder(user_id="test_user")
    agent = VisualAgent(recorder=recorder, max_steps=20)

    # タスクを実行
    result = await agent.execute_task(
        task="""Amazonで「アベンヌウォーター 50ml」を検索し、
検索結果から商品をクリックして商品詳細ページを表示する。
商品詳細ページで商品名と価格を確認してdoneで報告する。""",
        site="amazon.co.jp",
        initial_url="https://www.amazon.co.jp",
    )

    print("\n" + "=" * 60)
    print("結果:")
    print("=" * 60)
    print(f"Success: {result.get('success')}")
    # Unicodeエンコード問題を回避
    message = result.get('message', result.get('error', 'N/A'))
    try:
        print(f"Message: {message}")
    except UnicodeEncodeError:
        print(f"Message: {message.encode('ascii', 'replace').decode()}")
    print(f"Steps: {result.get('steps', 'N/A')}")
    print(f"Tokens: {result.get('total_tokens', 'N/A')}")

    # 抽出データがあれば表示
    if result.get('extracted_data'):
        print("\n抽出データ:")
        for k, v in result['extracted_data'].items():
            try:
                print(f"  {k}: {v}")
            except UnicodeEncodeError:
                print(f"  {k}: {str(v).encode('ascii', 'replace').decode()}")

    # ログファイルの確認
    if recorder.session:
        print(f"\nSession ID: {recorder.session.id}")
        print(f"Steps recorded: {len(recorder.session.steps)}")

        # 実行したアクション一覧
        print("\nアクション履歴:")
        for step in recorder.session.steps:
            action = step.action.value if hasattr(step.action, 'value') else step.action
            desc = step.params.get('description', step.params.get('text', ''))[:30] if step.params else ''
            print(f"  {step.index}. {action}: {desc}")

        # 保存されたファイルを確認
        from app.executors.visual.recorder import LOGS_DIR
        session_dir = LOGS_DIR / recorder.session.id
        if session_dir.exists():
            print(f"\nLog directory: {session_dir}")

    return result


if __name__ == "__main__":
    result = asyncio.run(test_amazon_product_detail())
    sys.exit(0 if result.get("success") else 1)
