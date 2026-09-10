from pathlib import Path
import pytest
from app.services import editor_motion_project as motion


def test_fork_preserves_source_and_excludes_render_cache(tmp_path):
    src = tmp_path / 'original'; src.mkdir()
    (src / 'index.html').write_text('original')
    (src / 'renders').mkdir(); (src / 'renders/video.mp4').write_bytes(b'cache')
    result = motion.prepare(tmp_path / 'room', src)
    Path(result['entry']).write_text('changed')
    assert (src / 'index.html').read_text() == 'original'
    assert not (Path(result['project_dir']) / 'renders').exists()


def test_nested_destination_rejected(tmp_path):
    (tmp_path / 'index.html').write_text('source')
    with pytest.raises(ValueError):
        motion.copy_source(tmp_path, tmp_path / 'child')


def test_approved_template_does_not_reuse_reference_audio(tmp_path):
    result = motion.prepare(tmp_path, template=True)
    project = Path(result['project_dir'])
    assert '<audio ' not in (project / 'index.html').read_text(encoding='utf-8')
    assert not (project / 'assets/reference-audio.m4a').exists()
