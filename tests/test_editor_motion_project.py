from pathlib import Path
import json
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
    assert not (project / 'BRIEF.md').exists()
    assert not (project / 'design.md').exists()
    assert not (project / 'AGENTS.md').exists()
    assert not (project / '.thumbnails').exists()


def test_new_project_does_not_require_a_preexisting_style(tmp_path):
    result=motion.prepare(tmp_path)
    project=Path(result['project_dir'])
    html=(project/'index.html').read_text(encoding='utf-8')
    assert 'data-composition-id="main"' in html
    assert (project/'assets/gsap.min.js').is_file()
    assert 'reference-01' not in html
    assert not (project/'BRIEF.md').exists()


def test_write_source_keeps_unicode_and_literals_and_stays_in_working_copy(tmp_path):
    project=Path(motion.prepare(tmp_path)['project_dir'])
    text='帰る前に、ひと息。\nconst label = `${name}`; // $1 "quotes"'
    motion.write_file(tmp_path,project,'scenes/title.js',text)
    assert (project/'scenes/title.js').read_text(encoding='utf-8')==text
    with pytest.raises(ValueError):
        motion.write_file(tmp_path,project,'../../escape.js',text)
    with pytest.raises(ValueError):
        motion.write_file(tmp_path,project,tmp_path/'escape.js',text)


def test_renderer_honors_project_version_and_rejects_mismatched_checks(tmp_path):
    package=tmp_path/'package.json'
    package.write_text(json.dumps({'scripts':{'check':'npx hyperframes@0.8.31 check','render':'npx hyperframes@0.8.31 render'}}))
    assert motion.project_version(tmp_path)=='0.8.31'
    package.write_text(json.dumps({'scripts':{'check':'npx hyperframes@0.8.33 check','render':'npx hyperframes@0.8.31 render'}}))
    with pytest.raises(ValueError): motion.project_version(tmp_path)


def test_npx_found_under_homebrew_lib_layout(tmp_path):
    # Homebrew: bin/node and lib/node_modules/npm/bin/npx-cli.js are siblings' children.
    (tmp_path/'bin').mkdir(); node=tmp_path/'bin/node'; node.write_text('')
    cli=tmp_path/'lib/node_modules/npm/bin/npx-cli.js'; cli.parent.mkdir(parents=True); cli.write_text('')
    assert motion._npx_cli(node)==cli


def test_npx_found_beside_windows_node(tmp_path):
    node=tmp_path/'node.exe'; node.write_text('')
    cli=tmp_path/'node_modules/npm/bin/npx-cli.js'; cli.parent.mkdir(parents=True); cli.write_text('')
    assert motion._npx_cli(node)==cli


def test_installed_cli_preferred_from_mac_npx_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(motion.Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('LOCALAPPDATA', raising=False); monkeypatch.delenv('npm_config_cache', raising=False)
    pkg=tmp_path/'.npm/_npx/abc/node_modules/hyperframes'; (pkg/'bin').mkdir(parents=True)
    (pkg/'package.json').write_text(json.dumps({'version':'0.8.33'})); (pkg/'bin/hyperframes.mjs').write_text('')
    monkeypatch.setattr(motion.shutil, 'which', lambda name: '/usr/bin/node' if name=='node' else None)
    assert motion.hyperframes_command('0.8.33')==['/usr/bin/node', str(pkg/'bin/hyperframes.mjs')]


def test_composition_length_read_from_main(tmp_path):
    (tmp_path/'index.html').write_text('<div data-composition-id="main" data-start="0" data-duration="18.33"></div><div data-duration="1.7"></div>')
    assert motion.composition_seconds(tmp_path)==18.33
