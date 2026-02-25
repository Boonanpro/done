from app.services.proposal_steps import extract_steps


def test_extract_steps_from_plan_section_numbered_list() -> None:
    text = """
## 実行計画
1. 要件を整理する
2. APIを実装する
3. テストを実行する
"""
    steps = extract_steps(text)
    assert len(steps) == 3
    assert steps[0]["description"] == "要件を整理する"
    assert steps[1]["description"] == "APIを実装する"
    assert steps[2]["description"] == "テストを実行する"


def test_extract_steps_from_generic_numbered_list() -> None:
    text = """
前置き
1. first
2. second
"""
    steps = extract_steps(text)
    assert len(steps) == 2
    assert steps[0]["description"] == "first"
    assert steps[1]["description"] == "second"

