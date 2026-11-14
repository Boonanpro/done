import copy
import re
from pathlib import Path

import pytest

from app.services import timeline_captions as cap
from app.services import timeline_commands as tc

ROOT = Path(__file__).resolve().parents[1]


def _seq():
    return {'duration': 20, 'format': '16:9', 'tracks': [
        {'id': 'v', 'type': 'video', 'clips': []},
        {'id': 'c', 'type': 'caption', 'clips': [
            {'id': 'cap1', 'track': 'caption', 'text': 'こんにちは', 'timeline_start': 1, 'timeline_end': 3,
             'style': {'font': 'noto-sans', 'fontSize': 1}}]},
    ]}


def test_font_ids_match_frontend_registry():
    src = (ROOT / 'frontend/src/components/video-review/caption-design.ts').read_text(encoding='utf-8')
    block = re.search(r'export const CAPTION_FONTS\b.*?>\s*=\s*\{(.*?)\n\};', src, re.S).group(1)
    ids = re.findall(r"^\s*'([a-z0-9-]+)'\s*:", block, re.M)
    assert tuple(ids) == tc.CAPTION_FONT_IDS


@pytest.mark.parametrize('font', ['Hiragino Sans', 'NotoSansJP', '', None, 3])
def test_add_caption_rejects_unknown_font(font):
    seq = _seq()
    before = copy.deepcopy(seq)
    r = tc.add_caption(seq, text='テスト', timeline_start=5, timeline_end=7, style={'font': font})
    assert not r['ok']
    assert 'noto-sans' in r['error'] and 'dela-gothic' in r['error']
    assert seq == before


def test_add_caption_accepts_known_font_and_no_font():
    seq = _seq()
    assert tc.add_caption(seq, text='a', timeline_start=5, timeline_end=7, style={'font': 'dela-gothic'})['ok']
    assert tc.add_caption(seq, text='b', timeline_start=8, timeline_end=9, style={'fontSize': 1.2})['ok']
    assert tc.add_caption(seq, text='c', timeline_start=10, timeline_end=11)['ok']


def test_set_clip_rejects_unknown_font_atomically():
    seq = _seq()
    before = copy.deepcopy(seq)
    r = tc.set_clip(seq, clip_id='cap1', text='変えない', style={'font': 'Hiragino Sans'})
    assert not r['ok'] and 'mincho' in r['error']
    assert seq == before
    # set_clip_props routes caption text/style through set_clip
    assert not tc.set_clip_props(seq, {}, clip_id='cap1', props={'style': {'font': 'Arial'}})['ok']
    assert seq == before
    assert tc.set_clip(seq, clip_id='cap1', style={'font': 'zen-maru'})['ok']
    assert tc._find_clip(seq, 'cap1')[2]['style']['font'] == 'zen-maru'


def test_auto_captions_rejects_unknown_font_before_replacing(tmp_path):
    seq = _seq()
    before = copy.deepcopy(seq)
    r = cap.auto_captions(seq, {}, tmp_path, [{'t0': 0, 't1': 4, 'text': 'こんにちは'}],
                          style={'font': 'Hiragino Sans'}, replace=True,
                          words=[[1.0, 2.5, 'こんにちは']])
    assert not r['ok'] and 'noto-sans' in r['error']
    assert seq == before  # existing caption in the range was not removed


# The three looks the owner asked for (2026-11-14): refined gothic, red box + white Mincho,
# red slanted heavy gothic. Each must pass add_caption / set_clip / set_clip_props intact.
LOOKS = {
    'plain': {'font': 'hiragino-w6', 'color': '#ffffff', 'outlineColor': '#000000', 'outlineWidth': 1.1,
              'shadow': {'color': 'rgba(0,0,0,0.45)', 'blur': 6, 'dx': 0, 'dy': 3}},
    'red_box': {'font': 'toppan-mincho', 'color': '#ffffff', 'outlineWidth': 0,
                'bg': {'color': '#d0121b', 'opacity': 1, 'radius': 0, 'padX': 0.4, 'padY': 0.14}},
    'red_slant': {'font': 'noto-sans', 'color': '#e5121f', 'outlineColor': '#ffffff', 'outlineWidth': 2.4,
                  'skew': -9, 'fontSize': 1.9},
}


@pytest.mark.parametrize('name', sorted(LOOKS))
def test_caption_looks_pass_every_entry(name):
    look = LOOKS[name]
    seq = _seq()
    r = tc.add_caption(seq, text='勉強より先に事業を始めてください', timeline_start=5, timeline_end=7, style=look)
    assert r['ok'], r
    assert tc._find_clip(seq, r['clip_id'])[2]['style'] == look
    assert tc.set_clip(seq, clip_id='cap1', style=look)['ok']
    assert tc._find_clip(seq, 'cap1')[2]['style'] == {**_seq()['tracks'][1]['clips'][0]['style'], **look}
    seq2 = _seq()
    assert tc.set_clip_props(seq2, {}, clip_id='cap1', props={'style': look})['ok']
    assert tc._find_clip(seq2, 'cap1')[2]['style']['font'] == look['font']


def test_caption_style_clamps_and_rejects_bad_nested():
    seq = _seq()
    assert tc.set_clip(seq, clip_id='cap1', style={'skew': -80})['ok']
    assert tc._find_clip(seq, 'cap1')[2]['style']['skew'] == -30
    before = copy.deepcopy(seq)
    for bad in ({'bg': {'colour': '#000'}}, {'bg': {'opacity': 'x'}}, {'shadow': 'big'}, {'skew': 'x'},
                {'bg': {'opacity': float('nan')}}):
        assert not tc.set_clip(seq, clip_id='cap1', style=bad)['ok'], bad
    assert seq == before
    # null removes the box / slant
    assert tc.set_clip(seq, clip_id='cap1', style={'bg': {'color': '#000'}})['ok']
    assert tc.set_clip(seq, clip_id='cap1', style={'bg': None, 'skew': None})['ok']
    st = tc._find_clip(seq, 'cap1')[2]['style']
    assert 'bg' not in st and 'skew' not in st


def test_mcp_caption_schema_accepts_the_looks():
    jsonschema = pytest.importorskip('jsonschema')
    from app import timeline_mcp_server as srv
    for look in LOOKS.values():
        jsonschema.validate(look, srv._CAPTION_STYLE)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({'font': 'Hiragino Sans'}, srv._CAPTION_STYLE)
