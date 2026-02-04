"""
Amazon Vision Executor テストスクリプト

視覚ベースのアプローチをテスト:
1. 検索 → スクリーンショット取得
2. スクロール
3. 商品クリック
"""

import asyncio
import json
from pathlib import Path
from datetime import datetime

# パスを追加
import sys
sys.path.insert(0, "D:/done")

from app.executors.amazon import AmazonExecutor
from app.tools.browser import get_executor_page, close_executor_browser


async def test_amazon_vision():
    """Amazon Vision Executor のテスト"""

    output_dir = Path("D:/done/amazon_vision_test")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print("=" * 60)
    print("Amazon Vision Executor テスト")
    print("=" * 60)

    # ブラウザを起動（get_executor_pageで自動起動）
    print("\n1. ブラウザを起動...")
    await get_executor_page()

    executor = AmazonExecutor()
    print(f"   Executor: {executor.__class__.__name__}")

    try:
        # Step 1: 検索
        print("\n2. 検索を実行: 'アベンヌウォーター'")
        search_result = await executor._do_search({
            "query": "アベンヌウォーター",
            "target": "50ml 4本",
        })

        print(f"   成功: {search_result.success}")
        print(f"   メッセージ: {search_result.message[:100]}...")

        # スクリーンショットを保存
        if search_result.screenshot_base64:
            import base64
            img_bytes = base64.b64decode(search_result.screenshot_base64)
            img_path = output_dir / f"search_{timestamp}.png"
            with open(img_path, "wb") as f:
                f.write(img_bytes)
            print(f"   スクリーンショット保存: {img_path}")

        # 商品位置を表示
        if search_result.browser_state and search_result.browser_state.get("product_positions"):
            positions = search_result.browser_state["product_positions"]
            print(f"\n   表示中の商品: {len(positions)}件")
            for p in positions[:3]:
                print(f"     - {p.get('title', 'N/A')[:40]}...")
                print(f"       クリック位置: ({p.get('click_x', 0):.0f}, {p.get('click_y', 0):.0f})")

        # Step 2: スクロール
        print("\n3. スクロールテスト...")
        for i in range(3):
            scroll_result = await executor.scroll({
                "direction": "down",
                "amount": 600,
            })

            print(f"   スクロール {i+1}: {scroll_result.success}")

            if scroll_result.details and scroll_result.details.get("screenshot"):
                screenshot_data = scroll_result.details["screenshot"]
                if screenshot_data and screenshot_data.get("base64"):
                    import base64
                    img_bytes = base64.b64decode(screenshot_data["base64"])
                    img_path = output_dir / f"scroll_{timestamp}_{i+1}.png"
                    with open(img_path, "wb") as f:
                        f.write(img_bytes)
                    print(f"   スクリーンショット保存: {img_path}")

            if scroll_result.details and scroll_result.details.get("product_positions"):
                positions = scroll_result.details["product_positions"]
                print(f"   表示中の商品: {len(positions)}件")
                for p in positions[:2]:
                    title = p.get('title', 'N/A')
                    if '50' in title or '4本' in title:
                        print(f"     ★ 見つけた?: {title[:50]}...")

        # Step 3: 商品クリック（ASINで）
        print("\n4. 商品クリックテスト（ASIN指定）...")
        # B09F2Z96Z7 = アベンヌ(Avene) ウオーター50g3本 + 50g増量キット
        click_result = await executor.click_product({
            "asin": "B09F2Z96Z7",
        })

        print(f"   成功: {click_result.success}")
        print(f"   メッセージ: {click_result.message[:200]}...")

        if click_result.details and click_result.details.get("screenshot"):
            screenshot_data = click_result.details["screenshot"]
            if screenshot_data and screenshot_data.get("base64"):
                import base64
                img_bytes = base64.b64decode(screenshot_data["base64"])
                img_path = output_dir / f"product_{timestamp}.png"
                with open(img_path, "wb") as f:
                    f.write(img_bytes)
                print(f"   スクリーンショット保存: {img_path}")

        print("\n" + "=" * 60)
        print("テスト完了！")
        print(f"結果は {output_dir} に保存されました")
        print("=" * 60)

        # 5秒待って確認
        print("\n5秒後にブラウザを閉じます...")
        await asyncio.sleep(5)

    finally:
        await close_executor_browser()


if __name__ == "__main__":
    asyncio.run(test_amazon_vision())
