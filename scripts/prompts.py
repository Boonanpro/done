"""Read and change the instructions that run Dan (the same files and history as the owner's /prompts screen).

    python scripts/prompts.py list                       # every instruction: id, where it works, who last changed it
    python scripts/prompts.py show call/router-routes     # the full text
    python scripts/prompts.py history call/router-routes  # versions, newest first
    python scripts/prompts.py save call/router-routes --note "なぜ直すか（みきさんのどの指摘か）" < new.md

Dan changes these texts only here or on the screen, never inside the Python code: a sentence added in code is one the
owner cannot see (2026-11-17). An edit of the file itself is recorded too (as Dan's, without a reason), so give the
reason with save.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import prompt_store  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('list')
    for name in ('show', 'history'):
        sub.add_parser(name).add_argument('id')
    s = sub.add_parser('save')
    s.add_argument('id')
    s.add_argument('--note', required=True, help='なぜ直すか（みきさんのどの指摘か）')
    args = ap.parse_args()
    if args.cmd == 'list':
        for item in prompt_store.catalog()['prompts']:
            info = prompt_store.summary(item['id'])
            mark = '読むだけ' if item.get('readonly') else prompt_store.WHO.get(info.get('last_by') or '', '')
            print(f"{item['id']:<36} {item['place']:<8} {info['chars']:>6}字  {mark}  {item['title']}")
    elif args.cmd == 'show':
        print(prompt_store.text(args.id))
    elif args.cmd == 'history':
        for r in prompt_store.history(args.id):
            print(f"{r['at']}  {prompt_store.WHO.get(r['by'], r['by'])}  {r['sha']}  {r.get('note', '')}")
    elif args.cmd == 'save':
        out = prompt_store.save(args.id, sys.stdin.read(), by='dan', note=args.note)
        print('保存しました' if out['saved'] else '同じ中身なので変えていません', out['sha'])


if __name__ == '__main__':
    main()
