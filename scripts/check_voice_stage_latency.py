"""A real run of the call's stage listener (voice_stage) on written explanations, to time it and to see what it draws.

Three explanations Dan might give on a call (Supabase's RLS, paying a tax, how Dan works) are fed as Dan's turns, a few
sentences at a time, the way the sideband hears them; each decision's action, time and program are printed, and the
programs are checked with the screen's own validation (frontend checkShapeProgram, through node). Target: 2 s a decision.

    python scripts/check_voice_stage_latency.py [--model deepseek-flash] [--json out.json]
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TALKS = {
    'Supabase の RLS': [
        'Supabase の守りの話ですね。今までは公開鍵を持っていれば誰でも表を読めてしまう状態でした。',
        '10月14日に RLS、行ごとの許可を全部の表で有効にしました。Done 側で59の表、分析側で18の表です。',
        '今はアプリから来た要求は、本人の印が付いた物だけ通って、許可した表だけ読めます。印の無い要求は空が返るか、42501 という拒否の番号が返ります。',
        'まだ確かめていないのは、外から読み出された形跡が過去に無かったかです。これは記録の API が不調で見られていません。',
    ],
    '税金の納付': [
        '法人税の中間申告の件です。流れは、仕訳を締めて、申告書を e-Tax で送って、納付する、の3段です。',
        '金額は3万6千円で、納付は3月30日に終わっています。仕訳も申告も納付も全部済んでいます。',
        '次の期限は来年の決算で、申告は決算日から2か月以内です。',
    ],
    'ダンの仕組み': [
        'ダンの中身を簡単に言うと、みきさんの言葉が本体に届いて、本体が道具を選んで動かし、結果をまた言葉で返しています。',
        '通話の時は少し違って、声のモデルが聞き取りと返事を担当し、調べ物や操作は裏側のモデルに渡して、結果が声に戻ります。',
        '裏側の作業が何分もかかる物は作業係に渡して、終わったら部屋のチャットに結果が届きます。',
    ],
}


class FakeDialogue:
    def __init__(self): self.turns = []
    def add(self, role, text):
        if self.turns and self.turns[-1]['role'] == role: self.turns[-1]['text'] += text
        else: self.turns.append({'role': role, 'text': text})
    def recent(self): return [{'role': t['role'], 'text': t['text'].strip()[:1200]} for t in self.turns[-12:]]


def screen_check(programs):
    """The frontend's checkShapeProgram on each program (node, strip-types), as the screen would run it."""
    script = ("import { checkShapeProgram } from '" + str(ROOT / 'frontend/src/lib/chat-shapes/schema.ts').replace(chr(92), '/') + "';"
              "const programs = JSON.parse(process.argv[1]);"
              "console.log(JSON.stringify(programs.map(p => { const r = checkShapeProgram(p); return r.ok ? {ok: true, root: r.root.name} : {ok: false, reason: r.reason}; })));")
    out = subprocess.run(['node', '--experimental-strip-types', '--input-type=module', '-e', script, json.dumps(programs)],
                         capture_output=True, text=True, cwd=ROOT / 'frontend')
    if out.returncode != 0: return [{'ok': None, 'reason': out.stderr[-300:]}] * len(programs)
    return json.loads(out.stdout.strip().splitlines()[-1])


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--model'); parser.add_argument('--json')
    args = parser.parse_args()
    from app.services import inbox
    inbox._env()   # the model keys from .env
    if not os.environ.get('DEEPSEEK_API_KEY'):   # a worktree without its own .env: the live tree's
        from dotenv import dotenv_values
        for k, v in dotenv_values('/Users/mikihonda/done/.env').items():
            if v and not os.environ.get(k): os.environ[k] = v
    from app.services import voice_stage as S
    if args.model: S.MODEL = args.model
    rows, log = [], []
    for title, sentences in TALKS.items():
        dialogue = FakeDialogue()
        dialogue.add('user', f'{title}について教えて。')
        stage = S.Stage(f'latency-{title}', 'sess', dialogue, lambda phase, **f: log.append((phase, f)))
        for sentence in sentences:
            dialogue.add('assistant', sentence)
            started = time.monotonic()
            result = await stage.decide()
            rows.append({'talk': title, 'said': sentence[:40], 'action': result, 'ms': round((time.monotonic() - started) * 1000),
                         'caption': stage.caption, 'program': stage.program if result == 'replace' else None})
        stage.close()
        S.stage_file(f'latency-{title}').unlink(missing_ok=True)
    programs = [r['program'] for r in rows if r['program']]
    checks = screen_check(programs) if programs else []
    it = iter(checks)
    for r in rows:
        if r['program']: r['screen'] = next(it)
    print(f'model: {S.MODEL}')
    for r in rows:
        print(f"{r['ms']:5d} ms  {r['action']!s:9}  [{r['talk']}] {r['said']}…  札: {r['caption']}" + (f"  画面: {r['screen']}" if r.get('screen') else ''))
    times = [r['ms'] for r in rows]
    print(f"decisions: {len(rows)}  median {sorted(times)[len(times)//2]} ms  max {max(times)} ms  scenes {len(programs)}  drawable {sum(1 for c in checks if c.get('ok'))}")
    for r in rows:
        if r['program']: print('---', r['caption']); print(r['program'])
    failures = [l for l in log if l[0] in ('stage_failed', 'stage_rejected')]
    if failures: print('failures:', failures)
    if args.json: Path(args.json).write_text(json.dumps({'model': S.MODEL, 'rows': rows, 'log': [list(l) for l in log]}, ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    asyncio.run(main())
