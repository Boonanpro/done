from scripts.voice_recovery_ledger import RecoveryLedger, Span


def admit(ledger, span=Span(6000, 20000), **kwargs):
    return ledger.reserve(span, now_ms=25000, avg_logprob=kwargs.get('score', -.12),
                          no_speech_prob=.01)


def test_later_correction_does_not_hide_missing_initial_request():
    ledger = RecoveryLedger()
    ledger.observe_native(Span(32000, 38000))
    assert admit(ledger)
    assert not ledger.reserve(Span(32000, 38000), now_ms=40000,
                              avg_logprob=-.1, no_speech_prob=.01)


def test_native_arriving_while_recognizing_cancels_recovery():
    ledger = RecoveryLedger()
    ledger.observe_native(Span(19000, 19500))
    assert not admit(ledger)


def test_tool_started_while_recognizing_cancels_recovery():
    ledger = RecoveryLedger()
    ledger.observe_tool(22000)
    assert not admit(ledger)


def test_uncertain_send_is_not_retried_even_with_different_segmentation():
    ledger = RecoveryLedger()
    assert admit(ledger)
    assert not admit(ledger, Span(6500, 19800))


def test_observed_hallucination_score_and_nonfinite_scores_are_rejected():
    for score in (-.754, float('nan'), float('inf')):
        assert not admit(RecoveryLedger(), score=score)


def test_call_closed_while_recognizing_cancels_recovery():
    ledger = RecoveryLedger()
    ledger.close()
    assert not admit(ledger)
