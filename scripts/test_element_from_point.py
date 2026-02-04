"""
document.elementFromPoint(x, y) で取れる情報を検証

座標クリック時に、その要素のセレクタ情報がどの程度取れるか調べる。
"""
import asyncio
from playwright.async_api import async_playwright


async def get_element_info_at_point(page, x: int, y: int) -> dict:
    """座標から要素情報を取得"""
    result = await page.evaluate(f"""
    () => {{
        const elem = document.elementFromPoint({x}, {y});
        if (!elem) return null;

        // 基本情報
        const info = {{
            tagName: elem.tagName.toLowerCase(),
            id: elem.id || null,
            className: elem.className || null,
            name: elem.getAttribute('name'),
            type: elem.getAttribute('type'),
            placeholder: elem.getAttribute('placeholder'),
            role: elem.getAttribute('role'),
            ariaLabel: elem.getAttribute('aria-label'),
            dataTestId: elem.getAttribute('data-testid'),

            // テキスト内容（短く）
            textContent: (elem.textContent || '').trim().slice(0, 50),
            innerText: (elem.innerText || '').trim().slice(0, 50),

            // 位置・サイズ
            rect: elem.getBoundingClientRect(),
        }};

        // 推奨セレクタを生成
        const selectors = [];

        // 1. ID（最強）
        if (elem.id) {{
            selectors.push({{ type: 'id', selector: '#' + elem.id, reliability: 'high' }});
        }}

        // 2. name属性
        if (elem.getAttribute('name')) {{
            selectors.push({{
                type: 'name',
                selector: elem.tagName.toLowerCase() + '[name="' + elem.getAttribute('name') + '"]',
                reliability: 'high'
            }});
        }}

        // 3. data-testid（テスト用属性、安定）
        if (elem.getAttribute('data-testid')) {{
            selectors.push({{
                type: 'data-testid',
                selector: '[data-testid="' + elem.getAttribute('data-testid') + '"]',
                reliability: 'high'
            }});
        }}

        // 4. role + aria-label（アクセシビリティ属性）
        if (elem.getAttribute('role') && elem.getAttribute('aria-label')) {{
            selectors.push({{
                type: 'role+aria',
                selector: 'role=' + elem.getAttribute('role') + '[name="' + elem.getAttribute('aria-label') + '"]',
                reliability: 'medium'
            }});
        }}

        // 5. placeholder（入力フィールド用）
        if (elem.getAttribute('placeholder')) {{
            selectors.push({{
                type: 'placeholder',
                selector: '[placeholder="' + elem.getAttribute('placeholder') + '"]',
                reliability: 'medium'
            }});
        }}

        // 6. class（不安定、最終手段）
        if (elem.className && typeof elem.className === 'string' && elem.className.trim()) {{
            const classes = elem.className.trim().split(/\\s+/).slice(0, 2);
            if (classes.length > 0 && classes[0].length < 30) {{
                selectors.push({{
                    type: 'class',
                    selector: elem.tagName.toLowerCase() + '.' + classes.join('.'),
                    reliability: 'low'
                }});
            }}
        }}

        info.possibleSelectors = selectors;
        info.bestSelector = selectors.length > 0 ? selectors[0].selector : null;

        return info;
    }}
    """)
    return result


async def main():
    print("=" * 70)
    print("document.elementFromPoint(x, y) の検証")
    print("=" * 70)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page(viewport={'width': 1024, 'height': 768})

        # DuckDuckGoにアクセス
        print("\n1. DuckDuckGoにアクセス...")
        await page.goto("https://duckduckgo.com")
        await page.wait_for_timeout(2000)

        # 検索ボックスの座標（VisualAgentログから）
        x, y = 407, 59

        print(f"\n2. 座標 ({x}, {y}) の要素情報を取得...")
        info = await get_element_info_at_point(page, x, y)

        if info:
            print(f"\n{'=' * 70}")
            print("要素情報")
            print('=' * 70)
            print(f"タグ:        {info['tagName']}")
            print(f"ID:          {info['id']}")
            print(f"class:       {info['className']}")
            print(f"name:        {info['name']}")
            print(f"type:        {info['type']}")
            print(f"placeholder: {info['placeholder']}")
            print(f"role:        {info['role']}")
            print(f"aria-label:  {info['ariaLabel']}")
            print(f"data-testid: {info['dataTestId']}")

            print(f"\n{'=' * 70}")
            print("生成可能なセレクタ")
            print('=' * 70)
            for sel in info.get('possibleSelectors', []):
                print(f"[{sel['reliability']:6}] {sel['type']:15} -> {sel['selector']}")

            print(f"\n推奨セレクタ: {info['bestSelector']}")
        else:
            print("要素が見つかりませんでした")

        # 他のサイトでも検証
        print(f"\n{'=' * 70}")
        print("3. 他のサイトでも検証（Google）...")
        print('=' * 70)

        await page.goto("https://www.google.com")
        await page.wait_for_timeout(2000)

        # Googleの検索ボックス付近
        info2 = await get_element_info_at_point(page, 500, 300)
        if info2:
            print(f"タグ:        {info2['tagName']}")
            print(f"ID:          {info2['id']}")
            print(f"name:        {info2['name']}")
            print(f"aria-label:  {info2['ariaLabel']}")
            print(f"\n生成可能なセレクタ:")
            for sel in info2.get('possibleSelectors', []):
                print(f"[{sel['reliability']:6}] {sel['type']:15} -> {sel['selector']}")

        input("\nEnterキーを押すと終了します...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
