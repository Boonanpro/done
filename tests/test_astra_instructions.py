from pathlib import Path
import re

from app.agent import cli_runner, codex_runner
from app.agent.backend_parity import parity_doc_paths
from app.agent.v2.tools import SkillRegistry


def test_skill_catalog_keeps_existing_capabilities_and_precise_descriptions():
    SkillRegistry.reload()
    skills = {skill.name: skill for skill in SkillRegistry.list_all()}
    expected = {p.parent.name for p in Path('.claude/skills').glob('*/SKILL.md')}
    assert expected <= skills.keys()
    assert all(len(skills[name].description) < 200 for name in expected)
    for name in ('build', 'self-dev', 'media-gen', 'skill-creator'):
        path = Path('.claude/skills') / name / 'SKILL.md'
        for link in re.findall(r'\]\(([^)]+)\)', path.read_text(encoding='utf-8')):
            assert (path.parent / link).exists(), (name, link)


def test_instruction_change_rotates_thread_but_room_state_does_not(monkeypatch):
    monkeypatch.delenv('DAN_PARITY_DOCS', raising=False)
    assert parity_doc_paths()[0].name == 'AGENTS.md'
    first = codex_runner.compute_static_hash('room A')
    assert first
    assert first == codex_runner.compute_static_hash('room B')
    monkeypatch.setattr(cli_runner, '_ABSOLUTE_RULES', cli_runner._ABSOLUTE_RULES + '\nChanged policy')
    assert first != codex_runner.compute_static_hash('room A')


def test_project_context_does_not_override_existing_authorization():
    assert '承認するまで実装は着手しない' not in cli_runner._CLI_PROJECT_TEMPLATE
    assert '報告だけして次の指示を待て' not in cli_runner._ABSOLUTE_RULES
