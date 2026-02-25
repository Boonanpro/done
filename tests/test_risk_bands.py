from app.agent.risk_bands import classify_risk_band, is_red_action


def test_is_red_action_detects_red_keywords() -> None:
    assert is_red_action("購入を確定してください")
    assert is_red_action("個人情報を入力します")


def test_is_red_action_returns_false_for_safe_text() -> None:
    assert not is_red_action("READMEを更新します")


def test_classify_risk_band_basic() -> None:
    assert classify_risk_band("購入を確定する") == "red"
    assert classify_risk_band("設定を更新する") == "yellow"
    assert classify_risk_band("コードを修正する") == "green"

