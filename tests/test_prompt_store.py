"""The instructions moved out of the code (2026-11-17) reach the models unchanged, and the /prompts screen's saves,
history and putting a version back work on the files the code reads."""
import json
import os
import re
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STARTED = '作業「{label}」は作業の部屋で始まっている。結果はまだ出ていない。結果や確かめたいことが出たら届く。'
BEFORE = json.loads((ROOT / 'tests' / 'fixtures' / 'prompts_before_move.json').read_text(encoding='utf-8'))


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('DAN_PROMPTS_DIR', str(tmp_path / 'prompts'))
    monkeypatch.setenv('DAN_PROMPTS_WORKSPACE', str(tmp_path / 'ws'))
    from app.services import prompt_store
    prompt_store._cache.clear()
    yield prompt_store
    prompt_store._cache.clear()


def test_moved_text_is_the_same_as_in_the_code_before(store):
    from app.services import (voice_plain, voice_responses, voice_router, voice_lookup, voice_parts, make_job_runner,
                              parallel_job_runner, command_center, api_job_runner)
    now = {
        'voice_plain.POLICIES': voice_plain.POLICIES,
        'voice_responses.INSTRUCTIONS': voice_responses.INSTRUCTIONS,
        'voice_responses.PLAIN_RULES': voice_responses.PLAIN_RULES,
        'voice_responses.BACKGROUND_RULES': voice_responses.BACKGROUND_RULES,
        'voice_router.ROUTES': voice_router.ROUTES, 'voice_router.ASK': voice_router.ASK,
        'voice_router.WORK': voice_router.WORK, 'voice_router.REPLY': voice_router.REPLY,
        'voice_router.CALENDAR': voice_router.CALENDAR, 'voice_router.PROMISE': voice_router.PROMISE.pattern,
        'voice_router.LUNA_RULES': voice_router.LUNA_RULES, 'voice_router.CALL_JOB_NOTE': voice_router.CALL_JOB_NOTE,
        'voice_lookup.INSTRUCTIONS': voice_lookup.INSTRUCTIONS, 'voice_parts.VOICE_TASK': voice_parts.VOICE_TASK,
        'make_job_runner.ORIGIN_NOTE': make_job_runner.ORIGIN_NOTE,
        'parallel_job_runner.JOB_RULES': parallel_job_runner.JOB_RULES,
        'command_center.CONFIRMATION_RULE': command_center.CONFIRMATION_RULE,
        'api_job_runner.JOB_INSTRUCTIONS': api_job_runner.JOB_INSTRUCTIONS,
    }
    for name, value in now.items():
        assert value == BEFORE[name], name
    assert '\n' + store.text('work/codex-job-rules') + '\n' == BEFORE['command_job_runner.codex_block']
    assert store.fill('call/persona', owner='本田樹さん（呼び名はみきさん）', whose='みきさん') == BEFORE['voice_plain.persona(本田樹,みきさん)']
    assert store.text('work/relay-header') == '【作業の依頼】'
    assert store.text('call/router-job-started') == STARTED


def test_every_catalog_entry_reads(store):
    for item in store.catalog()['prompts']:
        if item.get('workspace_file'): continue   # the owner's own files (RULES.md…), tested below
        assert store.text(item['id']).strip(), item['id']
    places = {p['id'] for p in store.catalog()['places']}
    assert all(item['place'] in places for item in store.catalog()['prompts'])


def test_a_saved_change_reaches_the_code_at_once_and_can_be_put_back(store):
    from app.services import voice_router
    first = store.history('call/router-job-started')
    assert [r['by'] for r in first] == ['seed']
    out = store.save('call/router-job-started', '「{label}」を始めたよ。', by='owner', note='言い方を変える',
                     base_sha=store.sha(STARTED))
    assert out['saved']
    assert store.text('call/router-job-started') == '「{label}」を始めたよ。'
    assert [r['by'] for r in store.history('call/router-job-started')] == ['owner', 'seed']
    store.revert('call/router-job-started', first[0]['sha'])
    assert store.text('call/router-job-started') == STARTED
    # a sections file: the code sees the change and the route keys are kept
    routes = store.text('call/router-routes').replace('今の時刻・日付・曜日が要る', '今の時刻が要る')
    store.save('call/router-routes', routes, by='owner')
    assert voice_router.ROUTES['clock'].startswith('今の時刻が要る')
    assert list(voice_router.ROUTES) == BEFORE_KEYS


BEFORE_KEYS = list(BEFORE['voice_router.ROUTES'])


def test_a_save_that_would_break_the_code_is_refused(store):
    routes = re.sub(r'## clock\n[^\n]+\n\n', '', store.text('call/router-routes'))
    with pytest.raises(ValueError, match='clock'):
        store.save('call/router-routes', routes, by='owner')
    with pytest.raises(ValueError, match='owner'):
        store.save('call/persona', 'あなたはダン。{whose}の手伝いをします。', by='owner')
    with pytest.raises(ValueError):
        store.save('call/policies', '  \n', by='owner')
    with pytest.raises(ValueError):
        store.save('call-code/stage-instructions', '何か', by='owner')


def test_a_change_made_meanwhile_is_not_overwritten(store):
    old = store.sha(store.text('call/luna-rules'))
    store.save('call/luna-rules', store.text('call/luna-rules') + '追記。', by='dan')
    with pytest.raises(RuntimeError):
        store.save('call/luna-rules', 'みきさんの直し', by='owner', base_sha=old)


def test_an_edit_outside_the_screen_is_recorded_as_dans(store):
    store.text('call/make-origin-note')
    path = store.path_of('call/make-origin-note')
    time.sleep(0.01)
    path.write_text('（ダンが直接書いた）\n', encoding='utf-8')
    os.utime(path, None)
    assert store.text('call/make-origin-note') == '（ダンが直接書いた）'
    latest = store.history('call/make-origin-note')[0]
    assert latest['by'] == 'dan' and '画面の外' in latest['note']


def test_workspace_files_keep_their_place(store, tmp_path):
    ws = tmp_path / 'ws'
    ws.mkdir()
    (ws / 'RULES.md').write_text('# 決まり\n- 一つ目\n', encoding='utf-8')
    assert store.text('workspace/rules') == '# 決まり\n- 一つ目\n'
    store.save('workspace/rules', '# 決まり\n- 一つ目\n- 二つ目\n', by='owner')
    assert (ws / 'RULES.md').read_text(encoding='utf-8') == '# 決まり\n- 一つ目\n- 二つ目\n'
    assert [r['by'] for r in store.history('workspace/rules')] == ['owner', 'dan']


def test_skill_save_tracks_learning_and_refuses_stale_edit(store, monkeypatch, tmp_path):
    from app.agent.v2.tools import SkillRegistry
    name = 'talking-demo-editing/references/suya-youtube'
    key = 'skill/' + name
    monkeypatch.setattr(store, 'REPO', tmp_path)
    source = tmp_path / store.entry(key)['source_file']
    source.parent.mkdir(parents=True)
    source.write_text('冒頭\n中盤\n本編\n終わり')
    base = store.text(key)
    edited = base.replace('冒頭', '冒頭は実写')
    store.save(key, edited, by='owner', base_sha=store.sha(base))
    source.write_text(base.replace('本編', '本編は明るく'))
    learned = SkillRegistry.get_prompt(name + '.md')
    assert learned == edited.replace('本編', '本編は明るく')
    with pytest.raises(RuntimeError):
        store.save(key, '別の修正', base_sha=store.sha(edited))
    source.write_text(source.read_text().replace('冒頭', 'インタビューから始める'))
    assert 'インタビューから始める' in SkillRegistry.get_prompt(name)
    store.revert(key, store.sha(edited))
    assert SkillRegistry.get_prompt(name) == edited


def test_skill_library_discovers_manuals_and_nested_pages(store, monkeypatch, tmp_path):
    from app.services.skill_versions import page_text, skill_pages
    from app.agent.v2.tools import SkillRegistry

    monkeypatch.setattr(store, 'REPO', tmp_path)
    root = tmp_path / '.claude/skills'
    skill = root / 'camera'
    (skill / 'recipes').mkdir(parents=True)
    (skill / 'SKILL.md').write_text('# Camera')
    (skill / 'recipes/撮影.md').write_text('# 撮影手順')
    (skill / 'script.py').write_text('# executable')
    (skill / 'outside.md').symlink_to(tmp_path / 'private.md')
    (tmp_path / 'private.md').write_text('private')
    assert {p['id'] for p in skill_pages()} == {'skill/camera', 'skill/camera/recipes/撮影'}
    for path in ('camera/recipes/撮影', 'camera'):
        key = 'skill/' + path
        before = store.text(key)
        store.save(key, before + ' 修正', by='owner', base_sha=store.sha(before))
        assert SkillRegistry.get_prompt(path) == before + ' 修正'
        assert page_text(tmp_path / store.entry(key)['source_file']) == before + ' 修正'
        with pytest.raises(RuntimeError):
            store.revert(key, store.sha(before), base_sha=store.sha(before))
        store.revert(key, store.sha(before))
        assert store.text(key) == before
        assert len(store.history(key)) == 3
    for invalid in ('camera/outside', 'camera/../private', 'camera/SKILL', 'camera//recipes/撮影'):
        with pytest.raises(KeyError):
            store.text('skill/' + invalid)


def test_where_dan_works_is_marked_and_a_save_ends_it(store):
    """2026-11-22: the screen lights the lines Dan is changing; Dan says where before he writes."""
    assert store.working() == {}
    routes = store.text('call/router-routes')
    third = routes.split('\n')[2]
    out = store.mark('call/router-routes', find=third, note='言い方')
    assert (out['from'], out['to'], out['state']) == (3, 3, 'editing')
    assert store.working()['id'] == 'call/router-routes' and store.working()['title']
    with pytest.raises(ValueError):
        store.mark('call/router-routes', find='全文に無い文')
    store.save('call/router-job-started', '「{label}」を始めた。', by='dan', note='試し')
    assert store.working()['state'] == 'saved' and store.working()['id'] == 'call/router-job-started'
    store.save('call/router-job-started', '「{label}」を始めたよ。', by='owner')   # the owner's own save is not Dan's work
    assert store.working()['state'] == 'saved'
