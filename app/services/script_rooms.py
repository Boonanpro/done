"""台本の部屋: 台本を聞く画面（/script-listen）の右の「ダンと台本」の会話（2026-11-20 本人「台本エディターにもチャット
いる。コメント機能だけじゃなくて常駐のチャットみたいなやつ」）。

台本（Google ドキュメント）1つにつき1部屋。一覧に出さない部屋（projects.metadata.hidden）で、origin_room_id はその台本の
本体の部屋（コメントが届く部屋＝gdoc_events.room_for_file）。metadata.script = {doc_id, origin_room_id}。
話すダンは同じ一人のダンで、本体の部屋の話と記憶を読める（前置き <place> に本体の部屋の id・台本・本人が今いる所を書く）。
本体の部屋の前置きにも、この部屋の一覧と最後の発言を書く（context_lines）。

本人が画面のどこにいるか（カーソルの文・選んだ文字）は、画面が知らせて ~/.dan/script-listen/state/<doc>.json に置く。
「ここ」「この文」はそれで決まる。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

STATE = Path.home() / '.dan' / 'script-listen' / 'state'
_CACHE_SECONDS = 30.0
_info_cache: dict[str, tuple[float, Optional[dict[str, Any]]]] = {}
_children_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_locks: dict[tuple[str, str], Any] = {}
PY = '/Users/mikihonda/dan-venv/bin/python'
DONE = '/Users/mikihonda/done'


def _sb():
    from app.services.supabase_client import get_supabase_client
    return get_supabase_client().client


def _meta(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    meta = row.get('metadata') or {}
    sc = meta.get('script') if isinstance(meta, dict) else None
    return sc if isinstance(sc, dict) and sc.get('doc_id') else None


async def ensure_room(user_id: str, doc_id: str, sb=None) -> dict[str, Any]:
    """台本の部屋を返す（無ければ作る）。{project_id, room_id, title}"""
    import asyncio
    lock = _locks.setdefault((user_id, doc_id), asyncio.Lock())
    async with lock:
        return await _ensure(user_id, doc_id, sb or _sb())


async def _ensure(user_id: str, doc_id: str, sb) -> dict[str, Any]:
    import asyncio
    from app.services import script_listen_thumbs as T
    from app.services.project_service import ProjectService

    origin = await asyncio.to_thread(T.room_of, doc_id)

    def _find():
        rows = (sb.table('projects').select('id,room_id,title,metadata,created_at')
                .eq('origin_room_id', origin).eq('user_id', user_id).execute()).data or []
        rows.sort(key=lambda r: str(r.get('created_at') or ''))
        for r in rows:
            sc = _meta(r)
            if sc and sc.get('doc_id') == doc_id and r.get('room_id'):
                return {'project_id': r['id'], 'room_id': r['room_id'], 'title': r.get('title') or ''}, None
        parent = (sb.table('projects').select('id,title,metadata').eq('room_id', origin).limit(1).execute()).data or []
        return None, (parent[0] if parent else {})

    found, parent = await asyncio.to_thread(_find)
    if found:
        return found
    title = await asyncio.to_thread(_doc_title, doc_id) or doc_id[:10]
    ptitle = str(parent.get('title') or '')
    metadata: dict[str, Any] = {'hidden': True, 'script': {'doc_id': doc_id, 'origin_room_id': origin}}
    pmeta = parent.get('metadata') or {}
    if isinstance(pmeta, dict) and pmeta.get('model'):
        metadata['model'] = pmeta['model']
    project = await ProjectService().create_project(
        user_id=user_id, title=f'台本: {title}'[:80], origin_room_id=origin, metadata=metadata,
        description=f'台本を聞く画面の右の「ダンと台本」の会話。台本 https://docs.google.com/document/d/{doc_id}/edit 。'
                    f'本体の部屋は「{ptitle}」(room_id={origin})。この台本を一緒に作る・直す。')
    _children_cache.pop(origin, None)
    return {'project_id': project.get('id'), 'room_id': project.get('room_id'), 'title': project.get('title') or title}


def _doc_title(doc_id: str) -> str:
    try:
        from app.services import script_listen as S
        return S.fetch(doc_id).get('title', '')
    except Exception:
        return ''


def room_info(room_id: str, sb=None) -> Optional[dict[str, Any]]:
    """台本の部屋なら {doc_id, origin_room_id, title, parent_title}、それ以外は None。"""
    if not room_id:
        return None
    hit = _info_cache.get(room_id)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    info = None
    try:
        sb = sb or _sb()
        rows = (sb.table('projects').select('title,metadata').eq('room_id', room_id).limit(1).execute()).data or []
        sc = _meta(rows[0]) if rows else None
        if sc:
            parent = (sb.table('projects').select('title').eq('room_id', sc['origin_room_id']).limit(1).execute()).data or []
            info = {'doc_id': sc['doc_id'], 'origin_room_id': sc['origin_room_id'], 'title': rows[0].get('title') or '',
                    'parent_title': (parent[0].get('title') if parent else '') or ''}
    except Exception:
        info = None
    _info_cache[room_id] = (time.time(), info)
    return info


def children(origin_room_id: str, sb=None) -> list[dict[str, Any]]:
    hit = _children_cache.get(origin_room_id)
    if hit and time.time() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    out: list[dict[str, Any]] = []
    try:
        sb = sb or _sb()
        rows = [r for r in (sb.table('projects').select('room_id,title,metadata')
                            .eq('origin_room_id', origin_room_id).execute()).data or [] if _meta(r) and r.get('room_id')]
        if rows:
            rooms = (sb.table('chat_rooms').select('id,last_message_at,last_message_preview')
                     .in_('id', [r['room_id'] for r in rows]).execute()).data or []
            by = {r['id']: r for r in rooms}
            for r in rows:
                room = by.get(r['room_id']) or {}
                out.append({'room_id': r['room_id'], 'title': r.get('title') or '', 'doc_id': _meta(r)['doc_id'],
                            'last_message_at': room.get('last_message_at') or '',
                            'preview': (room.get('last_message_preview') or '').replace('\n', ' ')[:80]})
            out.sort(key=lambda x: x['last_message_at'] or '', reverse=True)
    except Exception:
        out = []
    _children_cache[origin_room_id] = (time.time(), out)
    return out


# ── 本人が画面のどこにいるか ──

def put_state(doc_id: str, state: dict[str, Any]) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    keep = {k: state.get(k) for k in ('para', 'sentence', 'selection', 'playing', 'thumb', 'thumb_room', 'thumb_content', 'thumb_part') if state.get(k) not in (None, '')}
    keep['at'] = time.time()
    (STATE / f'{doc_id}.json').write_text(json.dumps(keep, ensure_ascii=False), encoding='utf-8')


def get_state(doc_id: str, max_age: float = 1800) -> Optional[dict[str, Any]]:
    try:
        st = json.loads((STATE / f'{doc_id}.json').read_text(encoding='utf-8'))
    except Exception:
        return None
    return st if time.time() - float(st.get('at') or 0) < max_age else None


def context_lines(room_id: str) -> list[str]:
    """前置き <place> に足す行。台本の部屋ならその台本・本人のいる所・道具、本体の部屋なら台本の部屋の一覧。"""
    info = room_info(room_id)
    if not info:
        kids = children(room_id)
        if not kids:
            return []
        lines = ['この部屋の台本を聞く画面の「ダンと台本」の会話（台本の部屋）。台本の作業の進みはここで話されている。'
                 '読む時は lookup(source=messages, room_id=…)。']
        for c in kids[:6]:
            lines.append(f"- {c['title']} (room_id={c['room_id']}) 最後: {c['last_message_at'][:16]} {c['preview']}")
        return lines
    d, o = info['doc_id'], info['origin_room_id']
    lines = [
        f"この部屋は台本の部屋（台本を聞く画面の右の「ダンと台本」）。台本: https://docs.google.com/document/d/{d}/edit "
        f"（画面 https://dan.paina.info/script-listen?doc={d} ）。本体の部屋は「{info['parent_title']}」(room_id={o})。"
        f"本体の部屋の話（決まったこと・前提・素材）は lookup(source=messages, room_id={o}) で読む。記憶・ルールは本体の部屋と同じ。",
        f"台本の今の中身（画面と同じ並び・段落番号つき）は {PY} -m app.services.script_rooms text {d} で読む（cwd {DONE}）。",
    ]
    st = get_state(d)
    if st:
        age = int(time.time() - float(st['at']))
        bits = []
        if st.get('thumb'):
            # サムネの編集を開いている間は、台本の文ではなくサムネが「これ」（2026-11-21 本人「このサムネとかって言っても通じるのか？」）
            from app.services.thumbnail_doc import cli
            room, cid = st.get('thumb_room') or '', st.get('thumb_content') or ''
            t = f"みきさんの画面の今（{age}秒前）: 台本の上のサムネの{st['thumb']}を、サムネの編集で開いている"
            if cid:
                t += f"（作品 content_id={cid}、部屋 {room}）"
            t += '。「このサムネ」「これ」はこのサムネ。'
            if st.get('thumb_part'):
                t += f"選んでいる部品: {str(st['thumb_part'])[:600]}。「この文字」「この絵」「これ」はこの部品。"
            if cid:
                t += (f"中身は {cli()} show {room} {cid}、今の絵は {cli()} render {room} {cid}（Read で見る）。"
                      f"直すと、みきさんの開いている画面がその場で変わる。")
            lines.append(t)
        else:
            if st.get('selection'): bits.append(f"選んでいる文字「{str(st['selection'])[:200]}」")
            if st.get('sentence'): bits.append(f"カーソルの文「{str(st['sentence'])[:200]}」（段落 {st.get('para')}）")
            if st.get('playing'): bits.append('読み上げを聞いている')
            if bits:
                lines.append(f"みきさんの画面の今（{age}秒前）: " + '／'.join(bits) + '。「ここ」「この文」はこれ。')
    try:
        from app.services import script_listen_thumbs as T
        items = T.status(d)
        if items:
            room = T.load(d).get('room') or o
            from app.services.thumbnail_doc import cli
            ws = '、'.join(f"{i['order'] + 1}枚目 content_id={i['content_id']}" for i in items)
            lines.append(f"台本の上のサムネは部品で持つ作品（部屋 {room}）: {ws}。直すのは {cli()}（show/set/repaint/finish/render/undo、"
                         f"部屋は {room}）。直した形は画面が数秒でドキュメントの絵に入れる（すぐ入れるなら "
                         f"{PY} -m app.services.script_listen_thumbs sync {d}）。"
                         "頼まれた所だけを部品で直す（背景の話なら背景の部品・色だけ、文字の話ならその文字だけ）。"
                         "直す時は今の作品をそのまま直し、新しいサムネの作品を作らない（試しの案も render の PNG で見せる。"
                         "別の案を残すと頼まれた時だけ thumb.py create --video <その動画> で同じ動画に足す）。人物の絵を作り替える時は "
                         ".claude/skills/talk-script/thumbnail.md の7節。会話にサムネの絵や部品が添えてあれば、それが話の対象。")
    except Exception:
        pass
    return lines


def text(doc_id: str) -> str:
    from app.services import script_listen as S
    doc, _, _ = S.view(doc_id)
    out = [f"# {doc.get('title', '')}"]
    for u in S.outline(doc):
        k = u['kind']
        if k == 'image':
            out.append(f"[段落{u.get('para')}] ［画像{'・サムネ' if u.get('section') == 'top' else ''}］")
        elif k in ('blank',):
            continue
        else:
            tag = {'say': '', 'heading': '見出し ', 'note': '注 ', 'title': '題 ', 'gone': '消す提案 '}.get(k, '')
            out.append(f"[段落{u.get('para')}] {tag}{u.get('text', '')}")
    return '\n'.join(out)


if __name__ == '__main__':
    import sys
    a = sys.argv[1:]
    if len(a) >= 2 and a[0] == 'text':
        from app.services.script_listen import doc_id_from
        print(text(doc_id_from(a[1])))
    else:
        sys.exit('python -m app.services.script_rooms text <doc>')
