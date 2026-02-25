from app.api.chat_routes import _is_replan_request


def test_is_replan_request_true_cases() -> None:
    assert _is_replan_request("やっぱり方針変更したい")
    assert _is_replan_request("Please replan this project")
    assert _is_replan_request("仕様変更するので再提案して")


def test_is_replan_request_false_case() -> None:
    assert not _is_replan_request("明日の大阪の天気を教えて")

