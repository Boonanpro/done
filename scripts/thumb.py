"""部品で持つサムネを、ダンが直す道具（app/services/thumbnail_doc.py）。保存した瞬間に本人のエディターの画面も変わる。

  python scripts/thumb.py show    <部屋> <作品>                      部品の一覧（奥から手前の順・位置・大きさ・文字）
  python scripts/thumb.py json    <部屋> <作品>                      部品の全部を JSON で
  python scripts/thumb.py set     <部屋> <作品> <部品id> key=値 …     数値・色・文字を直す
        例: x=820 y+=-30 size=300 fill=#ffe400 stroke_width=22 text="先に\\nビジネス" font=hiragino-w9
            hidden=true opacity=0.8 rotation=-4 shadow.blur=12 bg.color=#0a080ed7
            画像は x y w h（scale=1.1 で真ん中を中心に大きさを変える）
  python scripts/thumb.py order   <部屋> <作品> <部品id> front|back|up|down
  python scripts/thumb.py add-text <部屋> <作品> "文字" x y [size] [fill]
  python scripts/thumb.py delete  <部屋> <作品> <部品id>
  python scripts/thumb.py repaint <部屋> <作品> <絵の部品id> --box x,y,w,h --prompt "…" [--quality high]
        その絵の範囲だけを AI で描き直す（範囲の外は1画素も変えない）。座標はサムネの画素
  python scripts/thumb.py finish  <部屋> <作品> [--note "…"] [--apply]
        文字より奥の絵（背景・人物）を、並べた構図のまま光・影・色味・つなぎ目を AI で整えた1枚にする（1〜2分）。
        顔は元の写真の目鼻立ちに合わせ直す。--apply でその絵をサムネに入れる（元の絵は隠すだけ。undo か unfinish で戻る）。
        付けない時は候補を作るだけで、本人がエディターで前後を見比べて採用する
  python scripts/thumb.py unfinish <部屋> <作品>                     仕上げた絵を外して元の絵の部品に戻す
  python scripts/thumb.py render  <部屋> <作品> [--out a.png] [--width 1280]   今の形を PNG に（Read で見る）
  python scripts/thumb.py export  <部屋> <作品>                      1280×720 の書き出し
  python scripts/thumb.py undo    <部屋> <作品>                      1つ前の形へ戻す
  python scripts/thumb.py refs    <部屋> <作品> add <絵のURL> "題" "チャンネル" | clear
        「一覧で見る」で横に並べるほかのサムネ（参考・競合・同じチャンネルの過去の動画）
  python scripts/thumb.py create  <部屋> "題" <doc.json>             新しいサムネの作品を作る
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _value(v: str):
    low = v.lower()
    if low in ('true', 'false'):
        return low == 'true'
    if low in ('null', 'none'):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v.replace('\\n', '\n')


def _set(part: dict, key: str, value) -> None:
    if '.' in key:
        a, b = key.split('.', 1)
        sub = dict(part.get(a) or {})
        _set(sub, b, value)
        part[a] = sub
    else:
        part[key] = value


def _get_part(doc: dict, pid: str) -> dict:
    p = next((p for p in doc.get('parts') or [] if p.get('id') == pid), None)
    if p is None:
        sys.exit(f"部品 {pid} がありません。show で一覧を見る")
    return p


def show(doc: dict) -> str:
    out = [f"大きさ {doc.get('width')}×{doc.get('height')}  rev {doc.get('rev')}  （上から奥→手前）"]
    for p in doc.get('parts') or []:
        flags = ''.join([' 隠す' if p.get('hidden') else '', ' 固定' if p.get('locked') else '',
                         f" 回転{p.get('rotation')}" if p.get('rotation') else '',
                         f" 不透明度{p.get('opacity')}" if p.get('opacity') not in (None, 1) else ''])
        if p.get('type') == 'image':
            out.append(f"- {p['id']} [絵] {p.get('name') or ''}  x={p.get('x')} y={p.get('y')} w={p.get('w')} h={p.get('h')}{flags}")
        else:
            t = str(p.get('text') or '').replace('\n', '\\n')
            out.append(f"- {p['id']} [文字] 「{t}」 {p.get('name') or ''}  x={p.get('x')} y={p.get('y')}(ベースライン) size={p.get('size')} "
                       f"font={p.get('font')} fill={p.get('fill')} 縁={p.get('stroke')}/{p.get('stroke_width')} 字間={p.get('letter_spacing') or 0}{flags}")
    return '\n'.join(out)


def main() -> None:
    from app.services import thumbnail_doc as td
    a = sys.argv[1:]
    if len(a) < 2:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == 'create':
        room, title, path = a[1], a[2], a[3]
        c = td.create(room, title, json.loads(Path(path).read_text(encoding='utf-8')))
        print(c['id'])
        return
    room, cid = a[1], a[2]
    doc = td.get(room, cid)
    if cmd == 'show':
        print(show(doc))
    elif cmd == 'json':
        print(json.dumps(doc, ensure_ascii=False, indent=1))
    elif cmd == 'set':
        part = _get_part(doc, a[3])
        for kv in a[4:]:
            if '+=' in kv:
                k, v = kv.split('+=', 1)
                part[k] = (part.get(k) or 0) + float(v)
            elif '=' in kv:
                k, v = kv.split('=', 1)
                if k == 'scale' and part.get('type') == 'image':
                    s = float(v)
                    cx, cy = part['x'] + part['w'] / 2, part['y'] + part['h'] / 2
                    part['w'], part['h'] = part['w'] * s, part['h'] * s
                    part['x'], part['y'] = cx - part['w'] / 2, cy - part['h'] / 2
                else:
                    _set(part, k, _value(v))
            else:
                sys.exit(f"key=値 の形で: {kv}")
        saved = td.save(room, cid, doc, 'dan')
        print(f"保存しました rev {saved['rev']}")
    elif cmd == 'order':
        parts = doc['parts']
        part = _get_part(doc, a[3])
        i = parts.index(part)
        parts.pop(i)
        j = {'front': len(parts), 'back': 0, 'up': min(len(parts), i + 1), 'down': max(0, i - 1)}[a[4]]
        parts.insert(j, part)
        print(f"保存しました rev {td.save(room, cid, doc, 'dan')['rev']}")
    elif cmd == 'add-text':
        import uuid
        size = float(a[6]) if len(a) > 6 else 120
        doc['parts'].append({'id': f"t_{uuid.uuid4().hex[:6]}", 'type': 'text', 'text': a[3].replace('\\n', '\n'),
                             'x': float(a[4]), 'y': float(a[5]), 'size': size, 'font': 'hiragino-w9',
                             'fill': a[7] if len(a) > 7 else '#ffffff', 'stroke': '#000000', 'stroke_width': round(size * 0.1),
                             'shadow': {'blur': 12, 'opacity': 0.75}})
        print(f"保存しました rev {td.save(room, cid, doc, 'dan')['rev']} 部品 {doc['parts'][-1]['id']}")
    elif cmd == 'delete':
        part = _get_part(doc, a[3])
        doc['parts'].remove(part)
        print(f"保存しました rev {td.save(room, cid, doc, 'dan')['rev']}")
    elif cmd == 'repaint':
        pid = a[3]
        box = prompt = None
        quality = 'high'
        i = 4
        while i < len(a):
            if a[i] == '--box':
                box = tuple(float(v) for v in a[i + 1].split(','))
                i += 2
            elif a[i] == '--prompt':
                prompt = a[i + 1]
                i += 2
            elif a[i] == '--quality':
                quality = a[i + 1]
                i += 2
            else:
                i += 1
        if not box or len(box) != 4 or not prompt:
            sys.exit('--box x,y,w,h と --prompt が要ります')
        print(json.dumps(td.repaint(room, cid, pid, box, prompt, quality=quality, masked='--masked' in a), ensure_ascii=False))
    elif cmd == 'finish':
        import time as _t
        note = a[a.index('--note') + 1] if '--note' in a else ''
        st = td.finish_start(room, cid, note)
        while st and st.get('state') == 'running':
            _t.sleep(3)
            st = td.finish_status(room, cid, st['job_id'])
        if not st or st.get('state') != 'done':
            sys.exit(f"仕上げられませんでした: {(st or {}).get('message')}")
        print(json.dumps({k: st.get(k) for k in ('job_id', 'asset_id', 'src', 'sources', 'faces')}, ensure_ascii=False))
        print(f"仕上げた絵: {td.asset_file(room, st['asset_id'])}")
        if '--apply' in a:
            saved = td.save(room, cid, td.apply_finish(td.get(room, cid), st), 'dan')
            td.finish_decide(room, cid, st['job_id'], True)
            print(f"サムネに入れました rev {saved['rev']}")
    elif cmd == 'unfinish':
        print(f"仕上げを外しました rev {td.save(room, cid, td.remove_finish(doc), 'dan')['rev']}")
    elif cmd == 'render':
        out = Path(a[a.index('--out') + 1]) if '--out' in a else None
        w = int(a[a.index('--width') + 1]) if '--width' in a else 1280
        print(td.render(room, cid, out, out_w=w))
    elif cmd == 'export':
        print(json.dumps(td.export(room, cid), ensure_ascii=False))
    elif cmd == 'refs':
        if a[3] == 'clear':
            doc['references'] = []
        else:
            doc.setdefault('references', []).append({'src': a[4], 'title': a[5] if len(a) > 5 else '', 'channel': a[6] if len(a) > 6 else ''})
        print(f"保存しました rev {td.save(room, cid, doc, 'dan')['rev']} 参考 {len(doc.get('references') or [])}件")
    elif cmd == 'undo':
        print(f"戻しました rev {td.undo(room, cid)['rev']}")
    else:
        sys.exit(__doc__)


if __name__ == '__main__':
    main()
