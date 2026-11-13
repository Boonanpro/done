"""Macの空きを保つ毎晩の片付け（2026-11-13 みきさん「余計なものでデータが圧迫されない仕組み」「残すべきものはNASに」）。

11/13 に手で片付けた時（空き22GB→288GB）と同じ決め方を毎回くり返す:

  releases   ダン自身の古い版の控え。今使っている版・ひとつ前の版・動いている処理が使う版・新しい3つ・1日以内の版は残す。
  worktrees  直し終わった作業場所（work.py）。main に全部入っていて、書きかけ・閉じていない処理・2日以内の手が無い物だけ。
  versions   同じ動画の古い版（…v6 / v7 … と番号が付いた物の、いちばん新しい番号より前）。7日たった物だけ。
  scratch    書き出しの途中にできたファイル（_ で始まる映像・音、_pre_v・_tmp・.npy など）。2日たった物だけ。
  archive    撮影した元の映像と納品物を NAS の 案件/<お客さん>/<日付>_撮影|_納品/ へ写す（大きさとSHA-256を読み戻して照合）。
             Mac の方は、写し終わって14日たち、作品が使っていない物だけ消す。

どの段でも消さない物: エディターの作品が使う素材（uploads/production-assets の記録に出てくるパス）、
send/・納品 の中の物、撮影の元映像（NASへ写すだけ）、いま開かれているファイル、作業場所の書きかけ。

  python scripts/disk_tidy.py            # 試運転: 消す候補と大きさを出すだけ
  python scripts/disk_tidy.py --go       # 実行
  python scripts/disk_tidy.py --scheduled  # launchd から1時間ごと。前の実行から20時間たったか空きが100GBを切ったら --go
                                           # の片付けをし、それでも100GBを切っていたらダンを本体の部屋で起こす（12時間に1回まで）

記録: ~/.dan/workspace/data/disk-tidy/（ledger.jsonl に消した物・写した物を1行ずつ、sizes/<日付>.json に大きさの記録）。
お客さんの名前の対応は同じ所の clients.json（無ければ既定を書く）。
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = Path(os.environ.get('DAN_LIVE_TREE', str(Path.home() / 'done')))
WS = Path(os.environ.get('DAN_WORKSPACE', str(Path.home() / 'dan-workspace')))
DATA = Path(os.environ.get('DISK_TIDY_DATA', str(Path.home() / '.dan/workspace/data/disk-tidy')))
ASSETS = LIVE / 'uploads/production-assets'
NAS_MOUNT = Path.home() / '.dan/mnt/nas'
NAS_SMB = '127.0.0.1:10445/personal_folder'       # root の中継 com.dan.lanforward（Mac の利用者からは LAN に直接届かない）
JST = timezone(timedelta(hours=9))
DAY = 86400
GB = 1e9

LOW_FREE_GB = 100
FULL_EVERY = 20 * 3600
WAKE_EVERY = 12 * 3600
RELEASE_KEEP_NEWEST = 3
WORKTREE_IDLE = 2 * DAY
VERSION_AGE = 7 * DAY
SCRATCH_AGE = 2 * DAY
ARCHIVE_DELETE_AGE = 14 * DAY
MIN_VERSION_BYTES = 5_000_000

MEDIA = {'.mp4', '.mov', '.mkv', '.webm', '.m4v', '.avi', '.mxf', '.wav', '.m4a', '.aac', '.flac', '.mp3', '.aif', '.aiff'}
SCRATCH_EXT = {'.part', '.partial', '.yuv', '.y4m'}
SCRATCH_NAME = re.compile(r'(^_|_pre_v|_tmp|^tmp_|\.v$|_v_raw|_v_proc|_v_rb|_freeze$|^qa_|speedtest|_16k$|^seg_tmp|_concat$|_noaudio$)', re.I)
SCRATCH_DIR = re.compile(r'^(_tmp.*|tmp|temp|_work|_render.*|_frames.*|_segments?)$', re.I)
VERSION = re.compile(r'(?<![A-Za-z])v(\d{1,3})(?!\d)')
VERSION_DIR = re.compile(r'^v(\d{1,3})[A-Za-z]?$')
DELIVERY_DIR = re.compile(r'^(send|deliver.*|納品.*|送付.*)$', re.I)
DELIVERY_NAME = re.compile(r'(納品|送付)')
CAMERA = [(re.compile(r'^(C\d{4}|MVI_\d+|DSC\d+|A\d{3}C\d+.*)\.(mp4|mov|mxf)$', re.I), 'カメラ'),
          (re.compile(r'^(DJI_\d+.*|DJI\d+.*)\.(mp4|mov)$', re.I), 'DJI'),
          (re.compile(r'^(IMG_\d+|PXL_\d{8}_\d+.*|VID_\d{8}_\d+.*|\d{8}_\d{6}.*)\.(mp4|mov)$', re.I), 'スマホ')]
TEXT_EXT = {'.py', '.json', '.sh', '.txt', '.md', '.ass', '.srt', '.vtt', '.edl', '.fcpxml', '.xml', '.html', '.csv', '.yaml', '.yml', '.js', '.ts', '.ffconcat'}
RAW_DIR = re.compile(r'^(raw|撮影|元素材|元映像|footage)$', re.I)
SKIP_DIRS = {'node_modules', '.git', '.next', '__pycache__', '.venv', 'venv', '.gradle', 'site-packages', '.pytest_cache', 'Pods'}
SKIP_TOP = {'releases', 'mac_mini', 'tools', 'vlf-tools', 'dan-venv'}
IGNORED_OK = re.compile(r'^(frontend/node_modules|frontend/\.next|mobile/node_modules|node_modules|\.venv|venv|\.data|\.env|\.tmp|uploads|'
                        r'frontend/src/app/artifacts|frontend/public/artifacts|frontend/tsconfig\.tsbuildinfo|.*__pycache__/?|\.pytest_cache|'
                        r'.*\.pyc|frontend/next-env\.d\.ts|\.claude/settings\.local\.json|mobile/android/(app/)?build|mobile/\.expo)')

DEFAULT_CLIENTS = {
    '_読み方': 'dan-workspace の中のフォルダ → NAS の personal_folder/案件/<名前>/。ここに無いフォルダの元映像・納品物はNASへ写さず、Macの物も消さない。',
    'fukurou-clients/xenomagic': 'スヤさん',
    'fukurou-clients/nakamura': '中村さん',
    'pornanti_': 'ポルノアンチ',
}


# --- helpers -----------------------------------------------------------------------------------------------------------------

def now() -> float:
    return time.time()


def size_of(p: Path) -> int:
    try:
        if p.is_symlink():
            return 0
        if p.is_file():
            return p.stat().st_size
        total = 0
        for r, ds, fs in os.walk(p):
            ds[:] = [d for d in ds if not os.path.islink(os.path.join(r, d))]
            for f in fs:
                try:
                    total += os.lstat(os.path.join(r, f)).st_size
                except OSError:
                    pass
        return total
    except OSError:
        return 0


def newest_mtime(p: Path, depth: int = 3) -> float:
    """そのフォルダの中で一番新しい更新時刻（深さ depth まで）。"""
    try:
        best = p.lstat().st_mtime
    except OSError:
        return now()
    if not p.is_dir() or p.is_symlink():
        return best
    base = len(p.parts)
    for r, ds, fs in os.walk(p):
        ds[:] = [d for d in ds if d not in SKIP_DIRS and not os.path.islink(os.path.join(r, d))]
        if len(Path(r).parts) - base >= depth:
            ds[:] = []
        for f in fs:
            try:
                best = max(best, os.lstat(os.path.join(r, f)).st_mtime)
            except OSError:
                pass
    return best


def free_gb() -> float:
    st = os.statvfs(str(Path.home()))
    return st.f_bavail * st.f_frsize / GB


def git(where, *args, check=False):
    return subprocess.run(['git', '-C', str(where), *args], capture_output=True, text=True, check=check)


def open_paths() -> set[str]:
    """いま何かの処理が開いているファイルと、その処理の作業フォルダ。"""
    out = set()
    try:
        r = subprocess.run(['lsof', '-nP', '-Fn', '+c0'], capture_output=True, text=True, timeout=120)
        for line in r.stdout.splitlines():
            if line.startswith('n/Users/'):
                out.add(line[1:])
    except Exception:
        pass
    return out


def is_open(p: Path, opened: set[str]) -> bool:
    s = str(p)
    if s in opened:
        return True
    pre = s.rstrip('/') + '/'
    return any(o.startswith(pre) for o in opened)


def protected_paths() -> set[str]:
    """エディターの作品・素材の記録、公開しているページ、成果物の記録に出てくる dan-workspace のパス（Windows の住所も読み替える）。"""
    out = set()
    pat = re.compile('(?:' + re.escape(str(WS)) + r'|D:[\\/]+dan-workspace)[^"\'\n`]*')
    places = [(ASSETS, {'.json'}),
              (LIVE / 'frontend/src/app/artifacts', TEXT_EXT | {'.tsx'}),
              (Path.home() / '.dan/workspace/artifacts', {'.md', '.json'})]
    for base, exts in places:
        for r, ds, fs in os.walk(base):
            ds[:] = [d for d in ds if d not in SKIP_DIRS]
            for f in fs:
                if os.path.splitext(f)[1].lower() not in exts:
                    continue
                try:
                    s = open(os.path.join(r, f), encoding='utf-8', errors='ignore').read()
                except OSError:
                    continue
                s = s.replace('\\\\', '/').replace('\\/', '/')
                for m in pat.findall(s):
                    m = m.replace('\\', '/')
                    m = re.sub(r'^D:/+dan-workspace', str(WS), m)
                    out.add(m.rstrip('/').rstrip(')').rstrip(','))
    return out


def touches_protected(p: Path, prot: set[str]) -> bool:
    s = str(p).rstrip('/')
    if s in prot:
        return True
    pre = s + '/'
    return any(x.startswith(pre) for x in prot)


class Plan:
    def __init__(self):
        self.items: list[dict] = []
        self.kept: list[dict] = []

    def add(self, kind, path, reason, bytes_=None, **extra):
        self.items.append(dict(kind=kind, path=str(path), reason=reason,
                               bytes=size_of(Path(path)) if bytes_ is None else bytes_, **extra))

    def keep(self, kind, path, reason):
        self.kept.append(dict(kind=kind, path=str(path), reason=reason))


# --- releases ----------------------------------------------------------------------------------------------------------------

def plan_releases(plan: Plan, opened: set[str]):
    rel = WS / 'releases'
    if not rel.is_dir():
        return
    keep = set()
    try:
        st = json.loads(subprocess.run([sys.executable, str(LIVE / 'scripts/core_release.py'), 'status'],
                                       capture_output=True, text=True, timeout=60, cwd=str(LIVE)).stdout or '{}')
        for k in ('active', 'previous'):
            if isinstance(st.get(k), dict) and st[k].get('id'):
                keep.add(st[k]['id'])
    except Exception:
        plan.keep('releases', rel, '今使っている版が読めないので、版の控えは今回は消さない')
        return
    if not keep:
        plan.keep('releases', rel, '今使っている版が読めないので、版の控えは今回は消さない')
        return
    try:
        ps = subprocess.run(['ps', '-axww', '-o', 'command='], capture_output=True, text=True, timeout=30).stdout
    except Exception:
        ps = ''
    dirs = sorted([d for d in rel.iterdir() if d.is_dir()], key=lambda d: d.stat().st_mtime, reverse=True)
    for i, d in enumerate(dirs):
        if d.name in keep:
            plan.keep('releases', d, '今使っている版かひとつ前の版'); continue
        if i < RELEASE_KEEP_NEWEST:
            plan.keep('releases', d, '新しい3つ'); continue
        if f'releases/{d.name}' in ps or is_open(d, opened):
            plan.keep('releases', d, '動いている処理が使っている'); continue
        if now() - d.stat().st_mtime < DAY:
            plan.keep('releases', d, '1日以内'); continue
        plan.add('releases', d, 'ダンの古い版の控え')


# --- worktrees ---------------------------------------------------------------------------------------------------------------

def _worktrees() -> list[tuple[str, str]]:
    out, cur = [], {}
    for line in git(LIVE, 'worktree', 'list', '--porcelain').stdout.splitlines():
        if line.startswith('worktree '):
            cur = {'path': line[9:]}
            out.append(cur)
        elif line.startswith('branch '):
            cur['branch'] = line[7:].replace('refs/heads/', '')
    return [(w['path'], w.get('branch', '')) for w in out]


def plan_worktrees(plan: Plan, opened: set[str]):
    for path, branch in _worktrees():
        p = Path(path)
        if p.parent != WS or not p.is_dir() or not branch.startswith(('dan/', 'wip/')):
            continue
        counts = git(LIVE, 'rev-list', '--left-right', '--count', f'origin/main...{branch}').stdout.split()
        if len(counts) != 2 or counts[1] != '0':
            plan.keep('worktrees', p, 'main にまだ入っていない直しがある'); continue
        if is_open(p, opened):
            plan.keep('worktrees', p, '開いている処理がある'); continue
        last = git(p, 'log', '-1', '--format=%ct').stdout.strip()
        if not last.isdigit() or now() - int(last) < WORKTREE_IDLE or now() - newest_mtime(p) < WORKTREE_IDLE:
            plan.keep('worktrees', p, '2日以内に手が入っている'); continue
        status = git(p, 'status', '--porcelain', '--ignored').stdout.splitlines()
        dirty = [l for l in status if not l.startswith('!!')]
        if dirty:
            plan.keep('worktrees', p, '書きかけ（保存していない変更）がある'); continue
        odd = []
        for l in status:
            rel = l[3:].strip().strip('"')
            if IGNORED_OK.match(rel):
                continue
            live_twin = LIVE / rel
            if live_twin.exists() and size_of(live_twin) == size_of(p / rel):
                continue           # 動いているダンにも同じ物がある（台本の references など）
            odd.append(rel)
        if odd:
            plan.keep('worktrees', p, '作業場所にしか無いファイルがある: ' + ', '.join(odd[:3])); continue
        plan.add('worktrees', p, '直し終わった作業場所')




class Refs:
    """案件フォルダの中の台本・編集の記録（文字のファイル）を読み、後から作った物が名前を出している素材を見分ける。

    v3 を書き出した時の記録は v3 と同じ頃にできるので守らない。v14 の編集の記録が broll/v3 を使っていれば、v3 は守る。"""

    def __init__(self, top: Path):
        self.texts: list[tuple[float, str]] = []
        for r, ds, fs in os.walk(top):
            ds[:] = [d for d in ds if d not in SKIP_DIRS and not os.path.islink(os.path.join(r, d))]
            for f in fs:
                fp = os.path.join(r, f)
                if os.path.splitext(f)[1].lower() not in TEXT_EXT:
                    continue
                try:
                    st = os.stat(fp)
                    if st.st_size > 2_000_000:
                        continue
                    self.texts.append((st.st_mtime, open(fp, encoding='utf-8', errors='ignore').read().replace('\\', '/')))
                except OSError:
                    pass

    def used_later(self, p: Path) -> bool:
        try:
            t = p.stat().st_mtime if p.is_file() else newest_mtime(p, 6)
        except OSError:
            return True
        keys = ([f'{p.parent.name}/{p.name}', str(p), f'/{p.name}/', f"'{p.name}/", f'"{p.name}/'] if p.is_dir() else [p.name])
        return any(m > t + 60 and any(k in txt for k in keys) for m, txt in self.texts)


# --- versions / scratch / archive --------------------------------------------------------------------------------------------

def _walk_projects():
    """dan-workspace の中の案件フォルダ（作業場所・版の控え・道具は除く）。"""
    for top in sorted(WS.iterdir()):
        if not top.is_dir() or top.is_symlink() or top.name in SKIP_TOP or top.name.startswith('.'):
            continue
        if (top / '.git').exists():          # 作業場所は plan_worktrees が見る
            continue
        yield top


def _client_for(p: Path, clients: dict) -> str | None:
    rel = str(p.relative_to(WS))
    best = None
    for key, name in clients.items():
        if key.startswith('_'):
            continue
        if rel == key or rel.startswith(key.rstrip('/') + '/') or (key.endswith('_') and rel.split('/')[0].startswith(key)):
            if best is None or len(key) > len(best[0]):
                best = (key, name)
    return best[1] if best else None


def _shot_day(p: Path) -> str:
    m = re.search(r'(20\d{2})[-_]?(\d{2})[-_]?(\d{2})', str(p.relative_to(WS)))
    if m:
        try:
            return datetime(int(m[1]), int(m[2]), int(m[3])).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return datetime.fromtimestamp(p.stat().st_mtime, JST).strftime('%Y-%m-%d')


def classify_media(p: Path) -> tuple[str, str] | None:
    """('original'|'delivery', NAS の中のフォルダ名) か None。"""
    parts = [x for x in p.relative_to(WS).parts[:-1]]
    if any(DELIVERY_DIR.match(x) for x in parts) or DELIVERY_NAME.search(p.name):
        return 'delivery', '納品'
    for pat, sub in CAMERA:
        if pat.match(p.name):
            return 'original', sub
    if any(RAW_DIR.match(x) for x in parts):
        return 'original', 'その他'
    return None


def plan_media(plan: Plan, opened: set[str], prot: set[str], clients: dict, ledger_archived: dict):
    for top in _walk_projects():
        refs = Refs(top)
        for r, ds, fs in os.walk(top):
            rp = Path(r)
            if rp != top and ('.git' in ds or '.git' in fs or 'AGENTS.md' in fs or 'package.json' in fs or 'pyproject.toml' in fs):
                ds[:] = []; continue          # 中にあるリポジトリの写し（コード）は触らない
            ds[:] = sorted(d for d in ds if d not in SKIP_DIRS and not os.path.islink(os.path.join(r, d)))
            # 書き出しの途中のフォルダ
            for d in list(ds):
                dp = rp / d
                if SCRATCH_DIR.match(d):
                    ds.remove(d)
                    if touches_protected(dp, prot) or is_open(dp, opened) or any(
                            classify_media(Path(x)) for x in map(str, dp.rglob('*')) if Path(x).suffix.lower() in MEDIA):
                        plan.keep('scratch', dp, '作品が使う・開いている・元映像か納品物が入っている'); continue
                    if now() - newest_mtime(dp, 6) < SCRATCH_AGE:
                        continue
                    plan.add('scratch', dp, '書き出しの途中のフォルダ')
            # 番号付きの版のフォルダ（v6/ v7/ …）
            vdirs = {}
            for d in ds:
                m = VERSION_DIR.match(d)
                if m:
                    vdirs.setdefault(int(m[1]), []).append(d)
            if len(vdirs) > 1:
                top_v = max(vdirs)
                for v, names in vdirs.items():
                    if v == top_v:
                        continue
                    for d in names:
                        dp = rp / d
                        media = [x for x in dp.rglob('*') if x.is_file() and x.suffix.lower() in MEDIA]
                        if not media or any(x.suffix in {'.py', '.ts', '.tsx', '.js', '.json'} for x in dp.rglob('*')):
                            continue      # 映像・音の版だけ。コードや設定の v1/v2 は触らない
                        if touches_protected(dp, prot) or is_open(dp, opened) or refs.used_later(dp):
                            plan.keep('versions', dp, '作品か後の版が使っている'); continue
                        if any(classify_media(x) for x in dp.rglob('*') if x.is_file() and x.suffix.lower() in MEDIA):
                            plan.keep('versions', dp, '元映像か納品物が入っている'); continue
                        if now() - newest_mtime(dp, 6) < VERSION_AGE:
                            continue
                        plan.add('versions', dp, f'古い版（v{top_v} がある）')
                        ds.remove(d)
            # ファイル
            groups: dict[tuple[str, str], list[tuple[int, Path]]] = {}
            for f in fs:
                fp = rp / f
                ext = fp.suffix.lower()
                if fp.is_symlink() or not (ext in MEDIA or ext in SCRATCH_EXT):
                    continue
                try:
                    st = fp.stat()
                except OSError:
                    continue
                age = now() - st.st_mtime
                kind = classify_media(fp) if ext in MEDIA else None
                if kind:
                    _plan_archive(plan, fp, kind, st, age, opened, prot, clients, ledger_archived)
                    continue
                if ext in SCRATCH_EXT or SCRATCH_NAME.search(fp.stem):
                    if age < SCRATCH_AGE:
                        continue
                    if str(fp) in prot or is_open(fp, opened) or refs.used_later(fp):
                        plan.keep('scratch', fp, '作品が使う・開いている・後の版が使っている'); continue
                    plan.add('scratch', fp, '書き出しの途中のファイル', st.st_size)
                    continue
                m = VERSION.search(fp.stem)
                if m and st.st_size >= MIN_VERSION_BYTES:
                    prefix = fp.stem[:m.start()]
                    cls = 'audio' if ext in {'.wav', '.m4a', '.aac', '.flac', '.mp3', '.aif', '.aiff'} else 'video'
                    groups.setdefault((prefix, cls), []).append((int(m[1]), fp))
            for (prefix, _), items in groups.items():
                top_v = max(v for v, _ in items)
                for v, fp in items:
                    if v == top_v:
                        continue
                    st = fp.stat()
                    if now() - st.st_mtime < VERSION_AGE:
                        continue
                    if str(fp) in prot or is_open(fp, opened) or refs.used_later(fp):
                        plan.keep('versions', fp, '作品か後の版が使っている'); continue
                    plan.add('versions', fp, f'古い版（v{top_v} がある）', st.st_size)


def _plan_archive(plan, fp, kind, st, age, opened, prot, clients, ledger_archived):
    what, sub = kind
    client = _client_for(fp, clients)
    if not client:
        plan.keep('archive', fp, 'お客さんの対応が clients.json に無い'); return
    day = _shot_day(fp)
    dest = f'案件/{client}/{day}_{"納品" if what == "delivery" else "撮影"}/' + ('' if what == 'delivery' else sub + '/') + fp.name
    done_rec = ledger_archived.get(str(fp))
    if done_rec and done_rec.get('bytes') == st.st_size:
        if age >= ARCHIVE_DELETE_AGE and now() - done_rec.get('t', now()) >= ARCHIVE_DELETE_AGE \
                and str(fp) not in prot and not is_open(fp, opened):
            plan.add('archived-local', fp, f'NASに写し済み（{done_rec["dest"]}）で14日たった', st.st_size, dest=done_rec['dest'])
        return
    if age < DAY:
        return       # 撮って1日以内は、まだ書き込み中かもしれない
    plan.add('archive', fp, ('納品物' if what == 'delivery' else '撮影の元映像') + 'をNASへ写す', st.st_size, dest=dest)


# --- NAS -----------------------------------------------------------------------------------------------------------------------

def nas_root() -> Path | None:
    """personal_folder を見られる場所。既にどこかで開いていればそこを使い、無ければ ~/.dan/mnt/nas に開く。"""
    try:
        for line in subprocess.run(['mount'], capture_output=True, text=True).stdout.splitlines():
            if 'smbfs' in line and NAS_SMB.split('/')[0] in line and line.split(' on ')[0].endswith('/personal_folder'):
                mp = Path(line.split(' on ')[1].split(' (')[0])
                if (mp / '案件').is_dir():
                    return mp
    except Exception:
        pass
    sys.path.insert(0, str(LIVE))
    try:
        import asyncio
        from app.services.credentials_service import get_credentials_service
        from app.services.owner import resolve_owner_user_id
        cred = asyncio.run(get_credentials_service().get_credential(resolve_owner_user_id(), 'ugreen_nas'))
    except Exception as exc:
        log(f'NASのログイン情報が読めませんでした: {exc}')
        return None
    if not cred or not cred.get('password'):
        log('NASのログイン情報（ugreen_nas）がありません')
        return None
    NAS_MOUNT.mkdir(parents=True, exist_ok=True)
    user = urllib.parse.quote(cred.get('id') or 'みき', safe='')
    pw = urllib.parse.quote(cred['password'], safe='')
    r = subprocess.run(['mount_smbfs', '-N', f'//{user}:{pw}@{NAS_SMB}', str(NAS_MOUNT)], capture_output=True, text=True, timeout=60)
    if r.returncode != 0 or not (NAS_MOUNT / '案件').is_dir():
        log('NASを開けませんでした: ' + (r.stderr or '').replace(cred['password'], '***').strip()[:200])
        return None
    return NAS_MOUNT


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for chunk in iter(lambda: f.read(8 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def archive_one(src: Path, nas: Path, rel_dest: str) -> dict:
    dest = nas / rel_dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    size = src.stat().st_size
    if dest.exists() and dest.stat().st_size == size:
        h = sha256(src)
        if sha256(dest) == h:
            return dict(dest=rel_dest, bytes=size, sha256=h, already=True)
        dest = dest.with_name(dest.stem + f'_{datetime.now(JST):%Y%m%d%H%M%S}' + dest.suffix)
        rel_dest = str(dest.relative_to(nas))
    tmp = dest.with_name(dest.name + '.partial')
    h = hashlib.sha256()
    with open(src, 'rb') as fi, open(tmp, 'wb') as fo:
        for chunk in iter(lambda: fi.read(8 << 20), b''):
            h.update(chunk)
            fo.write(chunk)
        fo.flush()
        os.fsync(fo.fileno())
    if tmp.stat().st_size != size or sha256(tmp) != h.hexdigest():
        tmp.unlink(missing_ok=True)
        raise RuntimeError('NASに写した物が元と合いません')
    os.replace(tmp, dest)
    return dict(dest=rel_dest, bytes=size, sha256=h.hexdigest(), already=False)


# --- run -----------------------------------------------------------------------------------------------------------------------

def log(msg: str):
    DATA.mkdir(parents=True, exist_ok=True)
    line = f'{datetime.now(JST):%Y-%m-%d %H:%M:%S} {msg}'
    print(line)
    with open(DATA / 'tidy.log', 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def ledger_write(rec: dict):
    with open(DATA / 'ledger.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps(dict(t=now(), **rec), ensure_ascii=False) + '\n')


def ledger_archived() -> dict:
    out = {}
    try:
        for line in open(DATA / 'ledger.jsonl', encoding='utf-8'):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get('kind') == 'archive' and r.get('ok'):
                out[r['path']] = r
    except OSError:
        pass
    return out


def load_clients() -> dict:
    p = DATA / 'clients.json'
    if not p.exists():
        DATA.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(DEFAULT_CLIENTS, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        return json.loads(p.read_text(encoding='utf-8'))
    except ValueError:
        return dict(DEFAULT_CLIENTS)


def make_plan() -> Plan:
    plan = Plan()
    opened = open_paths()
    prot = protected_paths()
    plan_releases(plan, opened)
    plan_worktrees(plan, opened)
    plan_media(plan, opened, prot, load_clients(), ledger_archived())
    return plan


def _remove_worktree(p: Path) -> bool:
    for r, ds, fs in os.walk(p):
        for name in ds + fs:
            q = os.path.join(r, name)
            if os.path.islink(q):
                os.unlink(q)
        ds[:] = [d for d in ds if not os.path.islink(os.path.join(r, d)) and d not in {'.git'}]
    res = git(LIVE, 'worktree', 'remove', '--force', str(p))
    if res.returncode != 0:
        log(f'作業場所を消せませんでした {p}: {res.stderr.strip()[:200]}')
        return False
    return True


def execute(plan: Plan) -> dict:
    freed, done, failed = 0, 0, 0
    nas = None
    for it in plan.items:
        p = Path(it['path'])
        try:
            if it['kind'] == 'archive':
                nas = nas or nas_root()
                if not nas:
                    failed += 1; continue
                res = archive_one(p, nas, it['dest'])
                ledger_write(dict(kind='archive', path=str(p), ok=True, **res))
                done += 1
                continue
            if not p.exists():
                continue
            if it['kind'] in ('releases', 'worktrees'):
                ok = _remove_worktree(p)
            elif it['kind'] == 'archived-local':
                nas = nas or nas_root()
                d = nas / it['dest'] if nas else None
                ok = bool(d and d.exists() and d.stat().st_size == p.stat().st_size)
                if ok:
                    p.unlink()
                else:
                    log(f'NASの写しが見当たらないので消しません {p}')
            elif p.is_dir():
                shutil.rmtree(p); ok = True
            else:
                p.unlink(); ok = True
            if ok:
                freed += it['bytes']; done += 1
                ledger_write(dict(kind=it['kind'], path=str(p), bytes=it['bytes'], reason=it['reason'], ok=True))
            else:
                failed += 1
        except Exception as exc:     # noqa: BLE001 — 1件の失敗で残りを止めない
            failed += 1
            log(f'{it["kind"]} {p}: {exc}')
    if any(it['kind'] in ('releases', 'worktrees') for it in plan.items):
        git(LIVE, 'worktree', 'prune')
    return dict(freed=freed, done=done, failed=failed)


def summary(plan: Plan) -> str:
    by = {}
    for it in plan.items:
        k = it['kind']
        n, b = by.get(k, (0, 0))
        by[k] = (n + 1, b + it['bytes'])
    names = {'releases': '古い版の控え', 'worktrees': '直し終わった作業場所', 'versions': '動画の古い版', 'scratch': '書き出しの途中の物',
             'archive': 'NASへ写す元映像・納品物', 'archived-local': 'NASに写し済みで消すMacの物'}
    return ' / '.join(f'{names.get(k, k)} {n}件 {b / GB:.1f}GB' for k, (n, b) in by.items()) or '片付ける物はありません'


def snapshot_sizes():
    d = DATA / 'sizes'
    d.mkdir(parents=True, exist_ok=True)
    out = {}
    for base in (WS, LIVE / 'uploads', Path.home()):
        for c in base.iterdir():
            if c.is_symlink() or c.name in {'Library'} and base == Path.home():
                continue
            if base == Path.home() and c in (WS, LIVE):
                continue
            out[str(c)] = size_of(c)
    out['_free'] = free_gb() * GB
    (d / f'{datetime.now(JST):%Y-%m-%d}.json').write_text(json.dumps(out, ensure_ascii=False), encoding='utf-8')
    return out


def growth_report(cur: dict) -> str:
    d = DATA / 'sizes'
    olds = sorted(d.glob('*.json'))
    base = {}
    for f in olds:
        if f.stem <= (datetime.now(JST) - timedelta(days=7)).strftime('%Y-%m-%d'):
            base = json.loads(f.read_text(encoding='utf-8'))
    if not base and olds:
        base = json.loads(olds[0].read_text(encoding='utf-8'))
    rows = sorted(((v - base.get(k, 0), k, v) for k, v in cur.items() if not k.startswith('_')), reverse=True)[:8]
    return '\n'.join(f'- {k}: {v / GB:.1f}GB（{"+" if g >= 0 else ""}{g / GB:.1f}GB）' for g, k, v in rows)


def wake_dan(text: str):
    state = _state()
    if now() - state.get('woke', 0) < WAKE_EVERY:
        return
    sys.path.insert(0, str(LIVE))
    try:
        from app.services.followups import schedule_followup
        from app.services.owner import resolve_owner_user_id
        room = load_clients().get('_起こす部屋') or 'dc33f0c1-d8f1-4786-88a9-564efc407fed'
        res = schedule_followup(room, text, 15, resolve_owner_user_id())
        log(f'ダンを起こしました: {res.get("message") or res}')
        state['woke'] = now(); _save_state(state)
    except Exception as exc:
        log(f'ダンを起こせませんでした: {exc}')


def _state() -> dict:
    try:
        return json.loads((DATA / 'state.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _save_state(s: dict):
    (DATA / 'state.json').write_text(json.dumps(s), encoding='utf-8')


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--go', action='store_true')
    ap.add_argument('--scheduled', action='store_true')
    ap.add_argument('--json', action='store_true')
    ap.add_argument('--list', action='store_true', help='候補を1件ずつ出す')
    ap.add_argument('--kept', action='store_true', help='残した理由も出す')
    a = ap.parse_args(argv)
    DATA.mkdir(parents=True, exist_ok=True)
    lock = open(DATA / '.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('別の片付けが動いています'); return 0
    state = _state()
    if a.scheduled:
        low = free_gb() < LOW_FREE_GB
        if not low and now() - state.get('full', 0) < FULL_EVERY:
            return 0
        a.go = True
    before = free_gb()
    plan = make_plan()
    if a.json:
        print(json.dumps(dict(items=plan.items, kept=plan.kept if a.kept else []), ensure_ascii=False, indent=1))
    if not a.go:
        print(f'試運転（消していません）: {summary(plan)}')
        if a.list:
            for it in sorted(plan.items, key=lambda x: -x['bytes']):
                print(f'  [{it["kind"]}] {it["bytes"] / GB:6.2f}GB  {it["path"]}  — {it["reason"]}' + (f' → {it["dest"]}' if it.get('dest') else ''))
        if a.kept:
            for k in plan.kept:
                print(f'  残す [{k["kind"]}] {k["path"]} — {k["reason"]}')
        return 0
    log(f'片付けを始めます（空き {before:.0f}GB）: {summary(plan)}')
    res = execute(plan)
    after = free_gb()
    log(f'片付け終わり: {res["done"]}件 {res["freed"] / GB:.1f}GB を空けました（失敗 {res["failed"]}件）。空き {before:.0f}GB → {after:.0f}GB')
    state = _state(); state['full'] = now(); _save_state(state)
    cur = snapshot_sizes()
    if after < LOW_FREE_GB:
        wake_dan(f'Macの空きが{after:.0f}GBで、決まった片付け（scripts/disk_tidy.py）の後も100GBを切っています。'
                 f'何が増えたかを調べて片付けてください（消してよいか迷う物はみきさんに聞く）。この1週間で増えた所:\n{growth_report(cur)}\n'
                 f'記録: {DATA}/tidy.log と ledger.jsonl')
    return 0


if __name__ == '__main__':
    sys.exit(main())
