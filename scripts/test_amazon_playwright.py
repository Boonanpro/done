"""
Amazon Executor (Playwright版) テストスクリプト

使用方法:
    python scripts/test_amazon_playwright.py
"""

import asyncio
import sys
import os

# プロジェクトルートをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_amazon_search():
    """Amazon検索のテスト"""
    from app.executors.amazon import AmazonExecutor

    print("=" * 60)
    print("Amazon Executor (Playwright版) テスト")
    print("=" * 60)

    executor = AmazonExecutor()

    # 検索テスト
    print("\n[テスト1] 商品検索")
    print("-" * 40)

    result = await executor._do_search({
        "query": "USBケーブル",
        "quantity": 1,
    })

    print(f"成功: {result.success}")
    # Windows console encoding issue workaround - replace yen sign
    msg = result.message.replace('\xa5', '\\').replace('¥', 'Y')
    print(f"メッセージ:\n{msg}")

    if result.options:
        opt = result.options[0]
        print(f"\n提案商品:")
        print(f"  タイトル: {opt.title}")
        print(f"  価格: {opt.price}")
        print(f"  詳細: {opt.details}")

    if result.screenshot_path:
        print(f"\nスクリーンショット: {result.screenshot_path}")

    return result.success


async def main():
    try:
        success = await test_amazon_search()

        print("\n" + "=" * 60)
        if success:
            print("テスト成功!")
        else:
            print("テスト失敗")
        print("=" * 60)

    except Exception as e:
        print(f"\nエラー発生: {e}")
        import traceback
        traceback.print_exc()
        return False

    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
