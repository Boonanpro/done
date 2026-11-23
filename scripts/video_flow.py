"""動画を編集する作業の図（指示文の画面の「動画の編集」）に、ダンが過去の作業と直しの案を載せる（app/services/video_flow.py）。

  python scripts/video_flow.py show [--case suya-youtube]     段・読む文（見つからない見出し）・作業・案の一覧
  python scripts/video_flow.py run      < run.json            過去の1つの作業を段ごとに載せる
  python scripts/video_flow.py propose  < proposal.json       直しの案を載せる（本人が図の上で承認・却下する）

run.json:      {"title": "...", "case": "suya-youtube", "work": {"url": "...", "thumb": "..."}, "result": "...", "owner": "本人の評価",
                "stages": {"pick": {"state": "ok|bad|skipped|na", "did": "したこと", "should": "本来は", "frames": [{"src": "<png>", "time": "4.9秒", "label": ""}]}}}
proposal.json: {"title": "...", "stage": "learn", "kind": "text", "prompt_id": "skill/...", "find": "今の文（1回だけある）", "replace": "新しい文（消すなら空）",
                "why": "なぜ", "effect": "直すと何が変わるか", "run": "<作業のid>", "before": {"label": "今", "frames": [...]}, "after": {"label": "直した後", "frames": [...]}}
                kind=work は文でなく作業（プログラムを足す等）の案。承認されると画面がダンに伝える。
絵の src は手元の png の場所でよい（画面で開ける所に写す）。手順書の文を本人に「直していい？」と聞く時は、チャットの文だけで聞かずにここへ載せる。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import video_flow as V  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['show', 'run', 'propose'])
    ap.add_argument('--case', default='')
    a = ap.parse_args()
    if a.cmd == 'show':
        o = V.overview(a.case)
        for s in o['stages']:
            missing = [r['title'] + ' ' + r['heading'] for r in s['reads'] if not r['found']]
            print(f"{s['id']}: {s['name']}  読む文{len(s['reads'])}" + (f"  見つからない: {missing}" if missing else ''))
        for r in o['runs']:
            print(f"作業 {r['id']}: {r['title']}")
        for p in o['proposals']:
            print(f"案 {p['id']} [{p['state']}] {p['stage']}: {p['title']}")
        return
    data = json.load(sys.stdin)
    out = V.add_run(data) if a.cmd == 'run' else V.propose(data)
    print(json.dumps({'id': out['id'], 'title': out['title']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
