import numpy as np
from app.services.source_alignment import match_samples


def test_matches_original_after_a_cut_with_different_gain():
    original=np.random.default_rng(42).normal(size=3000)
    edited=np.concatenate((original[:400],original[900:]))
    found=match_samples(edited,original*0.4+0.2,at=8,window=2,rate=100)
    assert found['candidate_time']==13
    assert found['correlation']>.999


def test_silence_does_not_claim_a_source_match():
    found=match_samples(np.zeros(1000),np.ones(2000),at=1,window=2,rate=100)
    assert found['match'] is None and found['reason']=='silence'
