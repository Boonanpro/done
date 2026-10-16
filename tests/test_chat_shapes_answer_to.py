"""The owner's answer to a part (Choice / Input) is an ordinary human message「<問い> → <答え>」 plus the
link to the part it answers, saved as the message's ai_context.answer_to (chat_routes._answer_to_context,
chat_service.send_message ai_context)."""
import inspect

from app.api.chat_routes import _answer_to_context
from app.models.chat_schemas import MessageSendRequest


def test_answer_to_context_keeps_only_known_keys_and_bounds_values() -> None:
    link = _answer_to_context({"message_id": "m1", "part": "p0a1b2c3d", "kind": "choice", "value": "A",
                               "question": "進め方", "extra": "dropped"})
    assert link == {"answer_to": {"message_id": "m1", "part": "p0a1b2c3d", "kind": "choice", "value": "A", "question": "進め方"}}
    long = _answer_to_context({"message_id": "m" * 100, "part": "p", "kind": "input", "value": "v" * 500})
    assert len(long["answer_to"]["message_id"]) == 64 and len(long["answer_to"]["value"]) == 300
    assert "question" not in long["answer_to"]


def test_answer_to_context_rejects_malformed() -> None:
    assert _answer_to_context(None) is None
    assert _answer_to_context("x") is None
    assert _answer_to_context({"message_id": "m", "part": "p", "kind": "other", "value": "A"}) is None
    assert _answer_to_context({"message_id": "", "part": "p", "kind": "choice"}) is None
    assert _answer_to_context({"message_id": "m", "part": "", "kind": "choice"}) is None


def test_request_model_and_service_signature_carry_the_link() -> None:
    req = MessageSendRequest(content="進め方 → A", session_id="room", answer_to={"message_id": "m", "part": "p", "kind": "choice", "value": "A"})
    assert req.answer_to["part"] == "p"
    assert MessageSendRequest(content="hi").answer_to is None
    from app.services.chat_service import ChatService
    assert "ai_context" in inspect.signature(ChatService.send_message).parameters
