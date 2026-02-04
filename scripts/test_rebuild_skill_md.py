"""
Test _rebuild_skill_md function directly

Tests:
1. Actions table is not duplicated (no "アクション一覧" + "Actions")
2. Requires column only contains login (not search)
"""
import sys
from pathlib import Path

sys.path.insert(0, "D:/done")

from app.services.skill_generator_claude import _rebuild_skill_md


def create_test_skill():
    """Create test rakuten skill with SKILL.md and action files"""
    skill_dir = Path("D:/done/.claude/skills/rakuten")
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Create SKILL.md with Japanese "アクション一覧" table (to test deletion)
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text("""# Rakuten Skill

楽天市場のスキル

## アクション一覧
| アクション | 説明 | 前提 | ドキュメント |
|-----------|------|------|-------------|
| `login` | ログインする | - | actions/login.md |
| `view-cart` | カートを見る | login | actions/view-cart.md |

## 実行フロー
```
実行可能なフロー:
1. login
2. view-cart (要: login)
```

## その他
補足情報
""", encoding="utf-8")

    # Create actions directory
    actions_dir = skill_dir / "actions"
    actions_dir.mkdir(exist_ok=True)

    # Create login.md (no 認証要件)
    (actions_dir / "login.md").write_text("""# login

楽天にログインする

## 手順
1. ログインページにアクセス
2. メールアドレスを入力
3. パスワードを入力
4. ログインボタンをクリック
""", encoding="utf-8")

    # Create view-cart.md (has 認証要件)
    (actions_dir / "view-cart.md").write_text("""# view-cart

カートを表示する

**認証要件**: ログイン済みであること

## 手順
1. カートページにアクセス
2. 商品一覧を表示
""", encoding="utf-8")

    # Create search.md (no 認証要件, but mentions 検索結果)
    (actions_dir / "search.md").write_text("""# search

商品を検索する

## 手順
1. 検索ボックスにキーワードを入力
2. 検索ボタンをクリック
3. 検索結果が表示される
""", encoding="utf-8")

    # Create add-to-cart.md (has 認証要件 AND mentions 検索結果)
    (actions_dir / "add-to-cart.md").write_text("""# add-to-cart

商品をカートに追加する

**認証要件**: ログイン済みであること

## 前提条件
- 検索結果または商品詳細ページが表示されていること

## 手順
1. 商品の「カートに入れる」ボタンをクリック
2. カートに追加されたことを確認
""", encoding="utf-8")

    print(f"[OK] Created test skill at {skill_dir}")
    return skill_dir


def test_rebuild_skill_md():
    """Test _rebuild_skill_md function"""
    skill_dir = create_test_skill()
    skill_md = skill_dir / "SKILL.md"

    print("\n" + "=" * 60)
    print("  Before _rebuild_skill_md()")
    print("=" * 60)
    print(skill_md.read_text(encoding="utf-8"))

    # Call the function
    _rebuild_skill_md(skill_dir)

    print("\n" + "=" * 60)
    print("  After _rebuild_skill_md()")
    print("=" * 60)
    content = skill_md.read_text(encoding="utf-8")
    print(content)

    # Verify
    print("\n" + "=" * 60)
    print("  Verification")
    print("=" * 60)

    tests_passed = True

    # Test 1: No "アクション一覧" table
    if "## アクション一覧" in content:
        print("[FAIL] 'アクション一覧' table still exists (should be deleted)")
        tests_passed = False
    else:
        print("[OK] 'アクション一覧' table removed")

    # Test 2: Only one "## Actions" section
    actions_count = content.count("## Actions")
    if actions_count == 1:
        print(f"[OK] Exactly 1 '## Actions' section found")
    else:
        print(f"[FAIL] Found {actions_count} '## Actions' sections (expected 1)")
        tests_passed = False

    # Test 3: add-to-cart Requires should be "login" only (not "login, search")
    # Find the add-to-cart row
    import re
    add_to_cart_match = re.search(r'\| `add-to-cart` \|[^|]*\|([^|]*)\|', content)
    if add_to_cart_match:
        requires = add_to_cart_match.group(1).strip()
        if requires == "login":
            print(f"[OK] add-to-cart Requires = '{requires}' (correct)")
        elif "search" in requires:
            print(f"[FAIL] add-to-cart Requires = '{requires}' (should not contain 'search')")
            tests_passed = False
        else:
            print(f"[WARN] add-to-cart Requires = '{requires}'")
    else:
        print("[FAIL] Could not find add-to-cart row in Actions table")
        tests_passed = False

    # Test 4: search Requires should be "-" (no dependencies)
    search_match = re.search(r'\| `search` \|[^|]*\|([^|]*)\|', content)
    if search_match:
        requires = search_match.group(1).strip()
        if requires == "-":
            print(f"[OK] search Requires = '{requires}' (correct)")
        else:
            print(f"[FAIL] search Requires = '{requires}' (should be '-')")
            tests_passed = False
    else:
        print("[FAIL] Could not find search row in Actions table")
        tests_passed = False

    print("\n" + "=" * 60)
    if tests_passed:
        print("  ALL TESTS PASSED!")
    else:
        print("  SOME TESTS FAILED")
    print("=" * 60)

    return tests_passed


if __name__ == "__main__":
    success = test_rebuild_skill_md()
    sys.exit(0 if success else 1)
