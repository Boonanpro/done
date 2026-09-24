import pytest

from app.services.jev_decisions import choice_answers


def question(n):
    return {'answer': {'type': 'choice', 'criteria': {f'k{i}': f'item {i}' for i in range(n)}}}


def answer(probs, choice):
    return {'answers': {'answer': {'type': 'choice', 'choice': choice, 'confidence': max(probs.values()), 'probabilities': probs}}}


def test_rounded_probabilities_of_many_options_are_accepted_and_renormalised():
    """2 decimals over 38 options sum to 0.99 (a third of the saved-address lookups were thrown away, 2026-09-24)."""
    probs = {f'k{i}': 0.0 for i in range(38)}
    probs.update(k0=0.64, k1=0.35)                     # sum 0.99
    out = choice_answers(answer(probs, 'k0'), question(38))
    assert abs(sum(out['answer']['probabilities'].values()) - 1) < 1e-9 and out['answer']['choice'] == 'k0'


def test_a_distribution_far_from_one_is_still_rejected():
    probs = {f'k{i}': 0.0 for i in range(4)}
    probs.update(k0=0.5, k1=0.3)                       # sum 0.8 with 4 options: not rounding
    with pytest.raises(ValueError):
        choice_answers(answer(probs, 'k0'), question(4))
