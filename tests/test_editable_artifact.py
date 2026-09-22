"""The build helper must preserve releases and reject stale review results."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location('editable_artifact', Path(__file__).resolve().parents[1] / 'scripts/editable_artifact.py')
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


def test_scaffold_preserves_existing_release_and_rejects_path_escape(tmp_path):
    workflow.scaffold('sample-lp', 'Sample', tmp_path)
    target = workflow.artifact_dir('sample-lp', tmp_path)
    release = target / 'release.gen.json'
    release.write_text('{"saved":true}', encoding='utf-8')
    with pytest.raises(ValueError, match='already exists'):
        workflow.scaffold('sample-lp', 'Replace', tmp_path)
    assert json.loads(release.read_text()) == {'saved': True}
    for invalid in ('../outside', 'a/b', 'a\\b', 'publish', ''):
        with pytest.raises(ValueError):
            workflow.scaffold(invalid, 'Bad', tmp_path)


def test_finish_requires_current_sources_and_review(tmp_path):
    workflow.scaffold('sample-lp', 'Sample', tmp_path)
    target = workflow.artifact_dir('sample-lp', tmp_path)
    shared = target.parent / 'shared.tsx'
    shared.write_text('export const text = "before";', encoding='utf-8')
    (target / 'page-body.tsx').write_text("import { text } from '../shared';", encoding='utf-8')
    report_dir = tmp_path / 'report'
    workflow.write_json(report_dir / 'audit.json', {
        'slug': 'sample-lp', 'structuralPass': True, 'extraFiles': [],
        'fingerprint': workflow.source_fingerprint(target, []),
    })
    with patch.object(workflow, 'artifact_dir', return_value=target):
        with pytest.raises(ValueError, match='Describe'):
            workflow.finish('sample-lp', report_dir, '', False)
        result = workflow.finish('sample-lp', report_dir, 'Visual and edit checks passed', False)
        assert result['registration'] == 'not requested'
        shared.write_text('export const text = "after";', encoding='utf-8')
        with pytest.raises(ValueError, match='changed after audit'):
            workflow.finish('sample-lp', report_dir, 'Old review', False)


def test_failed_audit_cannot_finish(tmp_path):
    workflow.write_json(tmp_path / 'audit.json', {'slug': 'sample-lp', 'structuralPass': False})
    with pytest.raises(ValueError, match='passing audit'):
        workflow.finish('sample-lp', tmp_path, 'Looks good', False)
