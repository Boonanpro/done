"""
Amazon検索のデバッグテスト

直接Executorを呼び出してエラーを確認する
"""

import asyncio
import logging
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

# ログを標準出力に表示（UTF-8強制）
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

async def test_search():
    # Executorをインポート
    from app.executors.amazon.executor import AmazonExecutor

    executor = AmazonExecutor()

    print("=" * 60)
    print("Amazon検索テスト")
    print("=" * 60)

    # テスト1: シンプルなクエリ + match_title
    params = {
        "query": "アベンヌウォーター",
        "match_title": "4本",
        "quantity": 1,
    }

    print(f"\nパラメータ: {params}")
    print("-" * 60)

    try:
        result = await executor.search(
            params=params,
            credentials=None,
            user_id="test_user"
        )

        print(f"\n結果:")
        print(f"  success: {result.success}")
        print(f"  message: {result.message[:200] if result.message else 'None'}...")
        if result.options:
            print(f"  options: {len(result.options)} 件")
            for opt in result.options[:3]:
                print(f"    - {opt.title[:50]}...")
        if hasattr(result, 'error_type') and result.error_type:
            print(f"  error_type: {result.error_type}")
        if hasattr(result, 'failure_reason') and result.failure_reason:
            print(f"  failure_reason: {result.failure_reason}")

    except Exception as e:
        print(f"\n例外発生: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "=" * 60)
    print("テスト完了")
    print("=" * 60)

if __name__ == "__main__":
    asyncio.run(test_search())
