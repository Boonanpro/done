"""scripts/disk_tidy.py の決め方を、作り物の作業場所で確かめる（本物のファイルには触らない）。"""
import importlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

OLD = time.time() - 10 * 86400


def _file(p: Path, size=6_000_000, mtime=OLD, text=None):
    p.parent.mkdir(parents=True, exist_ok=True)
    if text is not None:
        p.write_text(text, encoding='utf-8')
    else:
        with open(p, 'wb') as f:
            f.write(os.urandom(1024) * (size // 1024))
    os.utime(p, (mtime, mtime))
    return p


@pytest.fixture
def dt(tmp_path, monkeypatch):
    ws, live, data = tmp_path / 'ws', tmp_path / 'live', tmp_path / 'data'
    (live / 'uploads/production-assets/room').mkdir(parents=True)
    ws.mkdir()
    monkeypatch.setenv('DAN_WORKSPACE', str(ws))
    monkeypatch.setenv('DAN_LIVE_TREE', str(live))
    monkeypatch.setenv('DISK_TIDY_DATA', str(data))
    import disk_tidy
    m = importlib.reload(disk_tidy)
    monkeypatch.setattr(m, 'open_paths', lambda: set())
    return m, ws, live, data


def _plan(m):
    plan = m.Plan()
    m.plan_media(plan, set(), m.protected_paths(), m.load_clients(), m.ledger_archived())
    return {Path(i['path']).name: i for i in plan.items}, plan


def test_old_versions_go_latest_and_used_stay(dt):
    m, ws, live, _ = dt
    out = ws / 'fukurou-clients/nakamura/edit/out'
    for v in (1, 2, 3):
        _file(out / f'full_v{v}.mp4')
    _file(out / 'full_v1_freeze.mp4')                 # 書き出しの途中
    _file(out / 'full_v2_x108.mp4')                   # v2 の派生（v3 がある）
    used = _file(out / 'full_v0.mp4')                 # エディターの作品が使っている
    (live / 'uploads/production-assets/room/assets.json').write_text(json.dumps([{'path': str(used)}]))
    _file(ws / 'fukurou-clients/nakamura/edit/make_v3.py', text="src='full_v1.mp4'", mtime=time.time() - 5 * 86400)   # 後から作った記録が v1 を使う
    items, _ = _plan(m)
    assert 'full_v3.mp4' not in items                 # いちばん新しい版は残る
    assert 'full_v0.mp4' not in items                 # 作品が使う物は残る
    assert items['full_v2.mp4']['kind'] == 'versions'
    assert items['full_v2_x108.mp4']['kind'] == 'versions'
    assert items['full_v1_freeze.mp4']['kind'] == 'scratch'
    assert 'full_v1.mp4' not in items                 # 後の版の記録が使っているので残る（記録の時刻が新しい）


def test_recent_versions_and_scratch_stay(dt):
    m, ws, _, _ = dt
    d = ws / 'pornanti_x/edit'
    _file(d / 'cut_v1.mp4', mtime=time.time() - 3 * 86400)    # 7日たっていない
    _file(d / 'cut_v2.mp4')
    _file(d / '_tmp_audio.wav', mtime=time.time() - 3600)      # 2日たっていない
    _file(d / '_mix.wav')
    items, _ = _plan(m)
    assert 'cut_v1.mp4' not in items and '_tmp_audio.wav' not in items
    assert items['_mix.wav']['kind'] == 'scratch'


def test_version_dirs_only_media_and_not_code(dt):
    m, ws, _, _ = dt
    _file(ws / 'proj/edit/v5/out_v5.mp4')
    _file(ws / 'proj/edit/v6/out_v6.mp4')
    _file(ws / 'proj/fixtures/v1/data.json', text='{}')
    _file(ws / 'proj/fixtures/v2/data.json', text='{}')
    for d in ('edit/v5', 'edit/v6', 'fixtures/v1', 'fixtures/v2'):
        os.utime(ws / 'proj' / d, (OLD, OLD))
    items, _ = _plan(m)
    assert items['v5']['kind'] == 'versions'
    assert 'v1' not in items                          # コードの v1/v2 は触らない
    # 新しい版の記録が ../v5/ を使っていれば残す
    _file(ws / 'proj/edit/v6/render.py', text="V='../v5/out_v5.mp4'", mtime=time.time())
    items, _ = _plan(m)
    assert 'v5' not in items


def test_repository_copies_are_skipped(dt):
    m, ws, _, _ = dt
    _file(ws / 'copy/done/AGENTS.md', text='x')
    _file(ws / 'copy/done/scripts/out_v1.mp4')
    _file(ws / 'copy/done/scripts/out_v2.mp4')
    items, _ = _plan(m)
    assert 'out_v1.mp4' not in items


def test_originals_and_deliveries_are_copied_never_deleted_first(dt, tmp_path, monkeypatch):
    m, ws, _, data = dt
    cam = _file(ws / 'fukurou-clients/xenomagic/shoot-20261107/C0291.MP4')
    phone = _file(ws / 'fukurou-clients/nakamura/take1-20261104/IMG_1282.MOV')
    sent = _file(ws / 'fukurou-clients/nakamura/send/LINE特典動画_編集版.mp4')
    other = _file(ws / 'someone/raw/C0001.MP4')       # お客さんの対応が無い
    items, plan = _plan(m)
    assert items['C0291.MP4']['dest'] == '案件/スヤさん/2026-11-07_撮影/カメラ/C0291.MP4'
    assert items['IMG_1282.MOV']['dest'] == '案件/中村さん/2026-11-04_撮影/スマホ/IMG_1282.MOV'
    assert items['LINE特典動画_編集版.mp4']['dest'].startswith('案件/中村さん/') and '_納品/' in items['LINE特典動画_編集版.mp4']['dest']
    assert 'C0001.MP4' not in items
    assert all(i['kind'] == 'archive' for i in plan.items)
    nas = tmp_path / 'nas'
    (nas / '案件').mkdir(parents=True)
    monkeypatch.setattr(m, 'nas_root', lambda: nas)
    res = m.execute(plan)
    assert res['failed'] == 0 and res['freed'] == 0           # 写すだけで、Mac の物は消さない
    assert cam.exists() and phone.exists() and sent.exists() and other.exists()
    assert (nas / '案件/スヤさん/2026-11-07_撮影/カメラ/C0291.MP4').stat().st_size == cam.stat().st_size
    assert not list(nas.rglob('*.partial'))
    # 写して14日たつまでは Mac の物を消す候補にしない
    items, _ = _plan(m)
    assert 'C0291.MP4' not in items
    # 14日たった（記録の時刻と更新時刻を戻す）→ Mac の物を消す。NASの写しは残る
    lines = [json.loads(l) for l in open(data / 'ledger.jsonl', encoding='utf-8')]
    for r in lines:
        r['t'] -= 15 * 86400
    (data / 'ledger.jsonl').write_text('\n'.join(json.dumps(r, ensure_ascii=False) for r in lines) + '\n', encoding='utf-8')
    old = time.time() - 20 * 86400
    os.utime(cam, (old, old))
    items, plan = _plan(m)
    assert items['C0291.MP4']['kind'] == 'archived-local'
    m.execute(plan)
    assert not cam.exists()
    assert (nas / '案件/スヤさん/2026-11-07_撮影/カメラ/C0291.MP4').exists()


def test_archive_refuses_when_copy_differs(dt, tmp_path, monkeypatch):
    m, ws, _, _ = dt
    src = _file(ws / 'fukurou-clients/xenomagic/shoot-20261107/C0300.MP4')
    nas = tmp_path / 'nas'
    (nas / '案件').mkdir(parents=True)
    real = m.sha256
    calls = {'n': 0}

    def flaky(p):
        calls['n'] += 1
        return 'bad' if str(p).endswith('.partial') else real(p)
    monkeypatch.setattr(m, 'sha256', flaky)
    with pytest.raises(RuntimeError):
        m.archive_one(src, nas, '案件/スヤさん/2026-11-07_撮影/カメラ/C0300.MP4')
    assert src.exists() and not list(nas.rglob('C0300*'))


def test_low_space_wakes_once(dt, monkeypatch):
    m, _, _, data = dt
    woke = []
    monkeypatch.setitem(sys.modules, 'app.services.followups', type(sys)('f'))
    sys.modules['app.services.followups'].schedule_followup = lambda room, note, d, u=None: woke.append(note) or {'message': 'ok'}
    monkeypatch.setitem(sys.modules, 'app.services.owner', type(sys)('o'))
    sys.modules['app.services.owner'].resolve_owner_user_id = lambda: 'u'
    data.mkdir(parents=True, exist_ok=True)
    m.wake_dan('空きが少ない')
    m.wake_dan('空きが少ない')
    assert len(woke) == 1
