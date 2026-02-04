"""
Multiple skill proposal tests

Tests for _parse_proposals function
"""

import sys
sys.path.insert(0, "D:/done")

from app.services.skill_generator_claude import _parse_proposals, _parse_single_proposal


def test_single_proposal():
    """Single proposal (no separator)"""
    stdout = """
DECISION: create
REASON: New site without existing skill
GRANULARITY_OK: true
SKILL_NAME: amazon_search
DESCRIPTION: Amazonで商品を検索する
SITE: amazon.co.jp
ACTIONS: search
PARAMETERS: [{"name": "keyword", "type": "string", "required": true, "description": "検索キーワード"}]
STEPS: ["検索欄を選択する","キーワードを入力する","検索ボタンを押す"]
ANALYSIS: {"success_factors":["検索欄を特定できた"],"visual_required_steps":[],"selector_ok_steps":[1,2],"notes":""}
"""

    proposals = _parse_proposals(stdout)

    assert len(proposals) == 1, f"Expected 1 proposal, got {len(proposals)}"
    assert proposals[0]["decision"] == "create"
    assert proposals[0]["skill_name"] == "amazon_search"
    print("[PASS] Single proposal test")


def test_multiple_proposals():
    """Multiple proposals (with separator)"""
    stdout = """
---PROPOSAL 1---
DECISION: create
REASON: Login and purchase can be separated
GRANULARITY_OK: true
SKILL_NAME: amazon_login
DESCRIPTION: Amazonアカウントにログインする
SITE: amazon.co.jp
ACTIONS: login
PARAMETERS: [{"name": "email", "type": "string", "required": true, "description": "メールアドレス"}]
STEPS: ["ログインページを開く","メールアドレスを入力する","パスワードを入力する"]
ANALYSIS: {"success_factors":["ログインフォームを特定できた"],"visual_required_steps":[],"selector_ok_steps":[1,2,3],"notes":""}

---PROPOSAL 2---
DECISION: create
REASON: Purchase flow
GRANULARITY_OK: true
SKILL_NAME: amazon_purchase
DESCRIPTION: Amazonで商品を検索して購入する
SITE: amazon.co.jp
ACTIONS: search, add_to_cart, checkout
PARAMETERS: [{"name": "keyword", "type": "string", "required": true, "description": "検索キーワード"}]
STEPS: ["商品を検索する","商品をカートに追加する","レジに進む"]
ANALYSIS: {"success_factors":["検索と購入フローを正しく実行できた"],"visual_required_steps":[2],"selector_ok_steps":[1,3],"notes":""}

---END PROPOSALS---
"""

    proposals = _parse_proposals(stdout)

    assert len(proposals) == 2, f"Expected 2 proposals, got {len(proposals)}"
    assert proposals[0]["decision"] == "create"
    assert proposals[0]["skill_name"] == "amazon_login"
    assert proposals[1]["decision"] == "create"
    assert proposals[1]["skill_name"] == "amazon_purchase"
    print("[PASS] Multiple proposals test")


def test_mixed_proposals_with_skip():
    """Mixed proposals with skip"""
    stdout = """
---PROPOSAL 1---
DECISION: skip
REASON: Existing skill can handle login
GRANULARITY_OK: true

---PROPOSAL 2---
DECISION: create
REASON: New purchase flow
GRANULARITY_OK: true
SKILL_NAME: amazon_purchase_v2
DESCRIPTION: Amazonで商品を購入する（改良版）
SITE: amazon.co.jp
ACTIONS: purchase
PARAMETERS: [{"name": "keyword", "type": "string", "required": true, "description": "検索キーワード"}]
STEPS: ["商品を検索する","購入する"]
ANALYSIS: {"success_factors":["購入フローを正しく実行できた"],"visual_required_steps":[],"selector_ok_steps":[1],"notes":""}

---END PROPOSALS---
"""

    proposals = _parse_proposals(stdout)

    assert len(proposals) == 2, f"Expected 2 proposals, got {len(proposals)}"
    assert proposals[0]["decision"] == "skip"
    assert proposals[1]["decision"] == "create"
    assert proposals[1]["skill_name"] == "amazon_purchase_v2"
    print("[PASS] Mixed proposals with skip test")


def test_max_three_proposals():
    """Max 3 proposals limit"""
    stdout = """
---PROPOSAL 1---
DECISION: create
REASON: Test 1
GRANULARITY_OK: true
SKILL_NAME: skill_1
DESCRIPTION: Skill 1
SITE: example.com
ACTIONS: action1
PARAMETERS: []
STEPS: []
ANALYSIS: {}

---PROPOSAL 2---
DECISION: create
REASON: Test 2
GRANULARITY_OK: true
SKILL_NAME: skill_2
DESCRIPTION: Skill 2
SITE: example.com
ACTIONS: action2
PARAMETERS: []
STEPS: []
ANALYSIS: {}

---PROPOSAL 3---
DECISION: create
REASON: Test 3
GRANULARITY_OK: true
SKILL_NAME: skill_3
DESCRIPTION: Skill 3
SITE: example.com
ACTIONS: action3
PARAMETERS: []
STEPS: []
ANALYSIS: {}

---PROPOSAL 4---
DECISION: create
REASON: Test 4 (should be ignored)
GRANULARITY_OK: true
SKILL_NAME: skill_4
DESCRIPTION: Skill 4
SITE: example.com
ACTIONS: action4
PARAMETERS: []
STEPS: []
ANALYSIS: {}

---END PROPOSALS---
"""

    proposals = _parse_proposals(stdout)

    assert len(proposals) == 3, f"Expected 3 proposals (max), got {len(proposals)}"
    assert proposals[2]["skill_name"] == "skill_3"
    print("[PASS] Max three proposals test")


def test_extend_proposal():
    """Extend proposal parsing"""
    stdout = """
DECISION: extend
REASON: Can add action to existing skill
TARGET_SKILL: amazon
NEW_ACTIONS: purchase, checkout
GRANULARITY_OK: true
SKILL_NAME: amazon
DESCRIPTION: Amazonの購入機能を追加
SITE: amazon.co.jp
ACTIONS: purchase, checkout
PARAMETERS: [{"name": "product_url", "type": "string", "required": true, "description": "商品URL"}]
STEPS: ["商品ページを開く","カートに追加する","購入する"]
ANALYSIS: {"success_factors":["既存のログイン機能と統合できた"],"visual_required_steps":[],"selector_ok_steps":[1,2],"notes":""}
"""

    proposals = _parse_proposals(stdout)

    assert len(proposals) == 1, f"Expected 1 proposal, got {len(proposals)}"
    assert proposals[0]["decision"] == "extend"
    assert proposals[0]["target_skill"] == "amazon"
    assert proposals[0]["new_actions"] == ["purchase", "checkout"]
    print("[PASS] Extend proposal test")


def test_empty_output():
    """Empty output"""
    proposals = _parse_proposals("")
    # Empty output may result in 0 proposals or 1 with default decision
    assert len(proposals) <= 1
    print("[PASS] Empty output test")


if __name__ == "__main__":
    print("Testing _parse_proposals function...\n")

    test_single_proposal()
    test_multiple_proposals()
    test_mixed_proposals_with_skip()
    test_max_three_proposals()
    test_extend_proposal()
    test_empty_output()

    print("\nAll tests passed!")
