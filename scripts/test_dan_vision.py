"""
ダン視覚機能テストスクリプト

使用方法:
    python scripts/test_dan_vision.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def test_vision():
    """視覚機能のテスト"""
    from app.tools.browser import get_executor_page

    print("=" * 60)
    print("ダン視覚機能テスト")
    print("=" * 60)

    page = await get_executor_page()

    # Amazonにアクセス
    print("\n[1] Amazonにアクセス...")
    await page.goto("https://www.amazon.co.jp/")
    await page.wait_for_timeout(3000)

    # ボット検知ページの確認と処理
    print("\n[1.5] ボット検知ページの確認...")
    state = await page.get_page_state()

    # 「ショッピングを続ける」ボタンがあればクリック
    continue_buttons = [e for e in state["interactive_elements"]
                        if "ショッピングを続ける" in e.get('text', '')]
    if continue_buttons:
        print(f"ボット検知ページ検出、{continue_buttons[0]['ref']}をクリック...")
        await page.click_by_ref(continue_buttons[0]['ref'])
        await page.wait_for_timeout(3000)

    # ページ状態を取得
    print("\n[2] ページ状態を取得...")
    state = await page.get_page_state()

    print(f"\n--- ページサマリー ---")
    summary = state["summary"]

    def safe_print(s):
        """Windows console safe print"""
        try:
            print(s)
        except UnicodeEncodeError:
            print(s.encode('ascii', errors='replace').decode('ascii'))

    safe_print(f"タイトル: {summary['title']}")
    safe_print(f"URL: {summary['url']}")
    print(f"メインテキスト（先頭200文字）:")
    main_text = summary['main_text'][:200].replace('\n', ' ')
    safe_print(f"  {main_text}...")

    print(f"\n--- インタラクティブ要素 ({state['element_count']}個) ---")
    for elem in state["interactive_elements"][:10]:
        text = elem['text'][:30] if elem['text'] else '(no text)'
        print(f"  {elem['ref']:8} | {elem['role']:12} | {text}")

    # 検索ボックスを探す（inputまたはtextareaのみ）
    print("\n[3] 検索ボックスを探す...")
    search_elements = [e for e in state["interactive_elements"]
                       if e['tag'] in ('input', 'textarea')
                       and (e['role'] in ('searchbox', 'textbox', 'search', 'combobox')
                            or 'search' in e['id'].lower()
                            or 'search' in e['name'].lower()
                            or e['type'] == 'text')]

    if search_elements:
        search_box = search_elements[0]
        print(f"検索ボックス発見: {search_box['ref']} (tag={search_box['tag']}, role={search_box['role']}, id={search_box['id']})")

        # ref IDで入力
        print("\n[4] ref IDで検索キーワードを入力...")
        await page.fill_by_ref(search_box['ref'], "Python本")
        await page.wait_for_timeout(1000)

        print("入力完了！")
    else:
        print("検索ボックスが見つかりません（inputタグなし）")
        # 検出した要素のうち、入力可能そうなものを表示
        input_elements = [e for e in state["interactive_elements"] if e['tag'] in ('input', 'textarea', 'select')]
        print(f"入力要素数: {len(input_elements)}")
        for elem in input_elements[:5]:
            print(f"  {elem['ref']:8} | {elem['tag']:10} | type={elem['type']} | id={elem['id']}")

    # スクリーンショット
    print("\n[5] スクリーンショット保存...")
    await page.screenshot("dan_vision_test.png")
    print("保存: dan_vision_test.png")

    print("\n" + "=" * 60)
    print("テスト完了！")
    print("=" * 60)

    return True


async def main():
    try:
        success = await test_vision()
        return success
    except Exception as e:
        print(f"\nエラー発生: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
