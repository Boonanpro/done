from app.services.voice_request_dispatch import RequestDispatch


def test_native_request_without_delegation_is_dispatched_once():
    d = RequestDispatch()
    d.heard('記事を見せて', 1)
    assert d.reserve(2) is None
    assert d.reserve(3) == 1
    assert d.reserve(5) is None


def test_automatic_delegation_cancels_pending_fallback():
    d = RequestDispatch()
    d.heard('記事を見せて', 1)
    d.backend_started()
    d.backend_finished()
    assert d.reserve(3) is None


def test_followup_during_backend_is_kept_until_backend_finishes():
    d = RequestDispatch()
    d.heard('別案を作って', 1)
    d.backend_started()
    d.heard('数字は変えないで', 2)
    assert d.reserve(4) is None
    d.backend_finished()
    assert d.reserve(4) == 2


def test_fragments_reset_quiet_interval():
    d = RequestDispatch()
    d.heard('別案を', 1)
    d.heard('作って', 2)
    assert d.reserve(3) is None
    assert d.reserve(4) == 2


def test_uncertain_send_and_disconnect_never_retry():
    d = RequestDispatch()
    d.heard('見せて', 1)
    assert d.reserve(3) == 1
    d.backend_finished()
    assert d.reserve(10) is None
    d.heard('もう一度', 11)
    d.close()
    assert d.reserve(20) is None


def test_response_acknowledgement_does_not_consume_new_correction():
    d = RequestDispatch()
    d.heard('別案を作って', 1)
    assert d.reserve(3) == 1
    d.heard('数字はそのままで', 4)
    d.backend_started()  # response.created for the already reserved turn
    d.backend_started()  # continuation after a tool result
    d.backend_finished()
    assert d.reserve(6) == 2
