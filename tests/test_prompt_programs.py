"""A program edited on the board must change only the separate trial's answer."""
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api import prompt_programs as programs
from scripts.try_program_draft import apply_draft


def test_board_edit_changes_trial_answer_and_preserves_original(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    repo.mkdir()
    path = 'app/services/conversation_circuit.py'
    (repo / path).parent.mkdir(parents=True)
    original = (programs.ROOT / path).read_text()
    (repo / path).write_text(original)
    catalog = Path('frontend/src/components/prompts/program-sources.json')
    (repo / catalog).parent.mkdir(parents=True)
    (repo / catalog).write_text(json.dumps({'reply': [path]}))
    def git(*args):
        subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)
    git('init')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-m', 'before')
    trial = tmp_path / 'trial'
    git('worktree', 'add', '-b', 'dan/board-test', str(trial))
    monkeypatch.setenv('DAN_PROMPTS_DIR', str(tmp_path / 'prompts'))
    monkeypatch.setattr(programs, 'ROOT', repo)
    monkeypatch.setattr(programs, 'CATALOG', repo / catalog)
    item = programs.source(path)
    changed = original.replace("detail=detail or ''", "detail='確認した返事：' + (detail or '')", 1)
    assert changed != original
    def answer():
        spec = importlib.util.spec_from_file_location('trial_circuit', trial / path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.step('2026-11-24', 'reply', 'ダンの返事', '届きました')['detail']
    assert answer() == '届きました'
    body = programs.TrialDraft(path=path, base_sha=item['sha'], text=changed, scenario='返事の先頭に確認したことが出る')
    draft = Path(programs.save_draft(body)['draft'])
    assert json.loads(draft.read_text())['text'] == changed
    assert programs.last_change(path)['diff'].startswith(subprocess.check_output(['git','-C',str(repo),'rev-parse','--short','HEAD'],text=True).strip())
    apply_draft(draft, trial, draft.parent)
    assert answer() == '確認した返事：届きました'
    assert (repo / path).read_text() == original
    with pytest.raises(ValueError):
        apply_draft(draft, trial, draft.parent)
    body.base_sha = hashlib.sha256(b'other version').hexdigest()
    with pytest.raises(HTTPException) as exc:
        programs.save_draft(body)
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        programs.source('../.env')
    assert exc.value.status_code == 404
