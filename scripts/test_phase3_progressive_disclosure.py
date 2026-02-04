"""Phase 3 動作確認: Progressive Disclosure実装"""

import sys
sys.path.insert(0, "D:/done")

from app.agent.v2.tools import SkillRegistry, format_tool_result

def test_progressive_disclosure():
    """ツール実行結果にスキル本文が注入されるか確認"""
    # スキルをリロード
    SkillRegistry.reload()

    # ex-reservationを取得
    skill = SkillRegistry.get("ex-reservation")

    # モックツール実行結果
    result = {
        "success": True,
        "message": "検索完了: のぞみ123号 東京→新大阪 19:00発",
        "options": [
            {"title": "のぞみ123号", "price": 14000}
        ]
    }

    # format_tool_resultを呼び出し
    formatted = format_tool_result(result, "ex-reservation", "search", skill=skill)

    print("=== format_tool_result output ===")
    print(f"Text length: {len(formatted.text)} chars")
    print()

    # 出力の先頭部分を表示
    print("--- First 500 chars ---")
    print(formatted.text[:500])
    print()

    # 検証
    assert "[TOOL RESULT: ex-reservation search]" in formatted.text, "Should have tool result header"
    assert "## スキルマニュアル" in formatted.text, "Should have skill manual section"

    # スキル本文（markdown_content）が含まれているか
    assert "EX予約" in formatted.text or "SmartEX" in formatted.text, "Should contain skill content"

    # アクションマニュアルが含まれているか
    assert "## search アクション詳細" in formatted.text, "Should have action manual section"

    print("[OK] Progressive Disclosure: skill content injected")

    # スキルなしの場合のテスト（後方互換性）
    formatted_no_skill = format_tool_result(result, "ex-reservation", "search", skill=None)
    assert "[TOOL RESULT:" in formatted_no_skill.text, "Should work without skill"
    assert "## スキルマニュアル" not in formatted_no_skill.text, "Should not have skill manual without skill"

    print("[OK] Backward compatibility: works without skill")

    print()
    print("=== Phase 3 test complete ===")

if __name__ == "__main__":
    test_progressive_disclosure()
