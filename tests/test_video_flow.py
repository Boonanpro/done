import pytest

from app.services import prompt_store, video_flow as V


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('DAN_PROMPTS_DIR', str(tmp_path / 'prompts'))
    monkeypatch.setattr(V, 'UPLOADS', tmp_path / 'uploads')
    return tmp_path


def test_section_stops_at_same_level():
    text = '# A\nx\n## 切れ目\na\n### 小\nb\n## 次\nc'
    assert V.section(text, '## 切れ目') == '## 切れ目\na\n### 小\nb'
    assert V.section(text, '## 無い') is None
    assert V.section(text, '## 次') == '## 次\nc'


def test_every_stage_heading_exists_in_current_skill(store):
    for case in ('suya-youtube',):
        for st in V.stages(case):
            missing = [(r['id'], r['heading']) for r in st['reads'] if not r['found']]
            assert not missing, (st['id'], missing)
            for p in st['programs']:
                assert p['exists'], p['path']


def test_run_and_frames(store):
    png = store / 'a.png'
    png.write_bytes(b'x')
    run = V.add_run({'title': 't', 'case': 'suya-youtube', 'stages': {'check': {'state': 'bad', 'did': '2コマ', 'frames': [{'src': str(png), 'time': '4.9秒'}]}}})
    src = run['stages']['check']['frames'][0]['src']
    assert src.startswith('/api/v1/files/vflow_') and (store / 'uploads' / src.rsplit('/', 1)[1]).exists()
    with pytest.raises(ValueError):
        V.add_run({'title': 't', 'stages': {'nope': {}}})


def test_text_proposal_applies_only_on_approve(store):
    pid = 'work/relay-header'
    current = prompt_store.text(pid)
    line = next(current[i:i + 6] for i in range(len(current)) if current.count(current[i:i + 6]) == 1)
    p = V.propose({'title': '消す', 'stage': 'learn', 'kind': 'text', 'prompt_id': pid, 'find': line, 'replace': ''})
    assert prompt_store.text(pid) == current
    assert V.proposals()[0]['applies'] is True
    out = V.decide(p['id'], 'approve')
    assert out['state'] == 'approved' and line not in prompt_store.text(pid)
    assert any(h['by'] == 'owner' for h in prompt_store.history(pid))
    with pytest.raises(RuntimeError):
        V.decide(p['id'], 'reject')


def test_reject_changes_nothing_and_stale_find_refused(store):
    pid = 'work/relay-header'
    current = prompt_store.text(pid)
    line = next(l for l in current.split('\n') if l.strip() and current.count(l) == 1)
    p = V.propose({'title': 'x', 'stage': 'learn', 'prompt_id': pid, 'find': line, 'replace': 'NEW'})
    assert V.decide(p['id'], 'reject')['state'] == 'rejected'
    assert prompt_store.text(pid) == current
    q = V.propose({'title': 'y', 'stage': 'learn', 'prompt_id': pid, 'find': line, 'replace': 'NEW'})
    prompt_store.save(pid, current.replace(line, 'changed meanwhile'), 'dan')
    with pytest.raises(RuntimeError):
        V.decide(q['id'], 'approve')
    with pytest.raises(ValueError):
        V.propose({'title': 'z', 'stage': 'learn', 'prompt_id': pid, 'find': 'not in text at all', 'replace': ''})


def test_work_proposal_records_only(store):
    p = V.propose({'title': 'プログラムを足す', 'stage': 'check', 'kind': 'work', 'why': 'w'})
    assert V.decide(p['id'], 'approve')['state'] == 'approved'
