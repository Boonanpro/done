import asyncio
from app.services import editor_production_handoff as h
from app.services.editor_consultation_sheet import FIELDS, update

def ready():
    return update(None, [{'field': k, 'status': 'confirmed', 'value': k} for k in FIELDS], True)

def fake(monkeypatch, available=True):
    calls = []
    class Decision:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def choose(self, state, questions):
            calls.append((state, questions))
            return {'available': available, 'reason': 'unavailable', 'answers': {
                'workflow': {'choice': 'story', 'confidence': .9}}, 'elapsed_ms': 3}
    monkeypatch.setattr(h, 'Decisions', Decision)
    return calls

def test_trigger_and_repeated_update(monkeypatch):
    calls = fake(monkeypatch)
    sheet = ready()
    selected = asyncio.run(h.select(sheet, None, 'user'))
    assert selected['production_handoff']['workflow'] == 'story'
    assert not selected['production_handoff']['starts_production']
    repeated = asyncio.run(h.select(update(selected, []), selected, 'user'))
    assert len(calls) == 1
    assert not repeated['production_handoff']['new_selection']

def test_incomplete_and_direction_change(monkeypatch):
    calls = fake(monkeypatch)
    selected = asyncio.run(h.select(ready(), None, 'user'))
    incomplete = update(selected, [{'field':'references','status':'unknown','value':''}])
    assert 'production_handoff' not in asyncio.run(h.select(incomplete, selected, 'user'))
    changed = update(selected, [{'field':'subject','status':'confirmed','value':'別の作品'}])
    assert asyncio.run(h.select(changed, selected, 'user'))['production_handoff']['new_selection']
    assert len(calls) == 2

def test_unavailable_hands_control_to_backend_without_false_selection(monkeypatch):
    fake(monkeypatch, False)
    result = asyncio.run(h.select(ready(), None, 'user'))['production_handoff']
    assert result['status'] == 'needs_model_selection'
    assert result['selected_by'] is None and 'workflow' not in result
    assert result['candidates']['story']['next']

def test_assembled_session_has_handoff():
    from app.services.editor_live import session_config
    config = session_config([], [])
    assert 'production_handoff' in config['instructions']
    assert h.GUIDANCE in config['delegation']['responses']['instructions']
