"""Real Jev decisions for incomplete intentions and purpose-aware comparisons.

Expected outcomes are evaluation-only and never enter the decision request.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.services.editor_visual_decision import decide

CASES = [
    ('bare', ['動画を作りたいんだけど、相談に乗って。'], 'talk'),
    ('vague', ['いい感じの動画にしたいけど、どうしたらいいか分からない。'], 'talk'),
    ('private', ['誰にも公開しない、自分が将来見返すための家族の記録を作りたい。自然で暖かい映像の参考を見たい。'], 'compare'),
    ('specific_visual', ['用途はまだ未定だけど、細い明朝体で静かに出る字幕を比べたい。'], 'compare'),
    ('known_purpose', ['YouTubeで仕事帰りの生活を記録するVlogを作りたい。視聴者に一息つける感じを伝えたい。',
         {'role': 'assistant', 'text': '派手な広告風にもできます。'},
         '広告みたいなのは違う。日常をそっと見ているような参考を見たい。'], 'compare'),
    ('purpose_changed', ['ゲームの派手な告知を作りたい。', 'やっぱり別の動画にする。亡くなった祖父を家族で偲ぶための映像です。用途の変更は伝わった？'], 'talk'),
    ('not_production', ['あの雰囲気は近いけど、まだ作ってという意味じゃない。'], 'talk'),
    ('structure_advice', ['YouTubeで仕事ばかりの生活を変える記録を作りたい。手元を映す感じが近い。',
         '花の方が気持ちは近いけど花の紹介ではなく自分の生活の記録です。仕事を終えて自分にコーヒーを入れるような小さな楽しみを見せたい。手元の撮り方と合わせるとどういう構成にできますか。まだ制作は始めなくていいです。'], 'talk'),
    ('ready', ['新商品の発売告知で、20代向けのインスタ動画。目的は予約ページへの誘導です。',
         'まず商品の見た目だけ確認したいから、添付した写真から白背景の画像を1枚作って。動画はまだ不要。'], 'execute'),
]

async def main():
    out = ROOT / 'scratch/purpose-intake'
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for name, words, expected in CASES:
        dialogue = [w if isinstance(w, dict) else {'role': 'user', 'text': w} for w in words]
        result = await decide('2582a188-ff24-4a4f-b989-6063034d90b2', dialogue)
        row = {'case': name, 'dialogue': dialogue, 'expected': expected, **result}
        row['passed'] = result['available'] and result['action'] == expected
        if expected == 'talk':
            row['passed'] &= not result['needs_backend'] and not result['selected_library_ids']
        rows.append(row)
        print(json.dumps({k: row[k] for k in ('case', 'passed', 'action', 'elapsed_ms', 'selected_library_ids')}, ensure_ascii=False), flush=True)
    (out / 'decisions.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf8')
    if not all(r['passed'] for r in rows):
        raise SystemExit(1)

if __name__ == '__main__':
    asyncio.run(main())
