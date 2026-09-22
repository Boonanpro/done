import copy
from scripts.enrich_production_library import validate, choose
from app.services.reference_url_index import observation_search_text
from app.services import reference_url_index as index
import pytest


def example():
    return {'accessible': True, 'summary': 'A film with warm side lighting',
            'observations': [{'start': i*10, 'end': i*10+8, 'visual': 'person',
                              'motion': 'pan', 'audio': 'speech'} for i in range(3)],
            'facets': {'lighting': [{'label': 'warm side lighting', 'observation_indices': [1]}]},
            'quality_review': {'verdict': 'candidate', 'reason': 'controlled lighting'},
            'techniques': [{'name': 'reveal', 'observation_index': 1, 'observed': 'pan reveals person',
                            'reproduction_proposal': 'Possible Blender animation'}]}


def test_evidence_rejects_invented_ranges_and_unlinked_labels():
    value = example()
    assert validate(value, 30)
    for edit in ('range', 'label', 'overlap', 'approval'):
        invalid = copy.deepcopy(value)
        if edit == 'range': invalid['observations'][-1]['end'] = 100
        if edit == 'label': invalid['facets']['lighting'][0]['observation_indices'] = [20]
        if edit == 'overlap': invalid['observations'][0]['end'] = 12
        if edit == 'approval': invalid['quality_review']['verdict'] = 'approved'
        assert not validate(invalid, 30)


def test_search_respects_scene_scope_and_does_not_assert_implementation():
    value = example()
    assert observation_search_text(value, 0) == ''
    text = observation_search_text(value, 1)
    assert 'warm side lighting' in text and 'reveal' in text
    assert 'Blender' not in text


def test_collection_does_not_starve_less_popular_genres():
    rows = [{'id': str(i), 'labels': {'primary_genre': 'ads' if i < 5 else 'film'},
             'publisher': str(i), 'duration_seconds': 60, 'views_at_discovery': 100-i} for i in range(6)]
    result = choose(rows, 2, set())
    assert {r['labels']['primary_genre'] for r in result} == {'ads', 'film'}
    assert all(r['id'] != '0' for r in choose(rows, 2, {'0'}))


@pytest.mark.asyncio
async def test_dense_scene_evidence_splits_below_choice_count_limit(monkeypatch):
    rows = [{'id': str(i), 'search_text': '照明とカメラの観察' * 70} for i in range(80)]
    monkeypatch.setattr(index, 'candidates', lambda scope: rows)
    seen = set()
    async def judge(user, state, questions, **kwargs):
        choices = questions['reference']['criteria']
        real = {k: v for k, v in choices.items() if k != 'none'}
        assert len(index.choice_batches(real)) == 1
        seen.update(real)
        return {'available': True, 'answers': {'reference': {'probabilities': {k: .9 for k in real}}}}
    monkeypatch.setattr(index.editor_jev, 'judge', judge)
    result = await index.search('u', 'lighting', scope='technique')
    assert result['available'] and result['batch_count'] > 1
    assert len(seen) == 80
