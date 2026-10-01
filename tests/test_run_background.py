"""Work running in the background (a job) is not the chat's own turn: the chat does not show it as thinking."""
from app.services.run_service import background


def test_a_job_run_is_background_and_a_chat_turn_is_not():
    assert background({'metadata': {'started_by': 'command_center'}})
    assert not background({'metadata': {'started_by': 'follow_up'}}) and not background({'metadata': None})
