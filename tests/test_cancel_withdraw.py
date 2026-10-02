"""A reply to a message the user withdrew by cancelling is not kept (docs/current/chat-timeline-definition.md)."""
import time

from app.agent import cli_runner as C


def test_a_turn_answering_withdrawn_words_keeps_nothing_and_a_resend_is_answered():
    room = 'room-withdraw'
    C._turn_inputs.pop(room, None); C._withdrawn_words.pop(room, None)
    C.note_turn_input(room, '[返信先…]\n試験A: 了解とだけ返して')
    C.note_withdrawn(room, ['試験A: 了解とだけ返して\n[添付画像: /api/v1/files/x.png]'])
    assert C._answers_withdrawn(room)
    assert C._save_ai_message_sync(room, '了解') is False
    time.sleep(0.01)
    C.note_turn_input(room, '試験A: 了解とだけ返して')   # sent again after the cancel: a new turn, answered normally
    assert not C._answers_withdrawn(room)


def test_withdrawing_a_follow_up_does_not_touch_the_turn_already_working():
    room = 'room-followup'
    C._turn_inputs.pop(room, None); C._withdrawn_words.pop(room, None)
    C.note_turn_input(room, 'ブラウザで example.com を開いて題名を読んで')
    C.note_withdrawn(room, ['やっぱり題名だけでいい'])
    assert not C._answers_withdrawn(room)
