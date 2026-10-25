# -*- coding: utf-8 -*-
"""みきさんの指摘の台帳（~/.dan/workspace/lessons/ledger.json）を読み書きする。

2026-10-25 本人:「足す前に、まとめられないか探して汎化させるのは超大事」。それまでダンは、
指摘を受けるたびに記憶の feedback を1件足すだけで、同じ根っこの指摘が別々の記憶に積み上がっていた
（47件。同じ発言が2つの記憶に入っている物もあった）。

台帳は、1つの根っこ（root: 一般則・分け方・今の点検・次にすること）に、同じ根っこの指摘
（item: いつ・どこで・何を見て・元の言葉・出どころ）をまとめる。分け方は
machine=機械で止める / skill=スキルに書いて試験する / owner=みきさんに残す / spec=画面や道具の作りに入れる。

  python scripts/lessons.py find "<指摘の要点>"          同じ根っこを探す（足す前に必ず）
  python scripts/lessons.py add --root <id> --quote … --saw … --where … --src memory/feedback-x.md
  python scripts/lessons.py add --new-root "<一般則>" --kind skill --why-new "<近い根っこに入らない理由>" …
  python scripts/lessons.py touch --src memory/feedback-x.md --why "<指摘ではない直し>"
  python scripts/lessons.py table                        みきさんに見せる表（TABLE.md）を作り直す
  python scripts/lessons.py weekly [--days 7]            週1回のまとめ直しの材料

find・add・touch は最後に「[lessons] …」の行を出す。記憶の feedback を書く時の関所
（hook_lesson_gate.py）は、同じ作業の記録にこの行があるかを見る。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

WORKSPACE = Path(os.environ.get("DAN_WORKSPACE_DIR") or (Path.home() / ".dan" / "workspace"))
LEDGER = Path(os.environ.get("DAN_LESSONS_LEDGER") or (WORKSPACE / "lessons" / "ledger.json"))
KINDS = {"machine": "機械で止める", "skill": "スキルに書いて試験する", "owner": "みきさんに残す", "spec": "作りに入れる"}
STRUCTURAL = {"守れている", "一部"}


def load() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def save(ledger: dict) -> None:
    ledger["updated"] = date.today().isoformat()
    tmp = LEDGER.with_suffix(".tmp")
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, LEDGER)


def norm_src(src: str) -> str:
    """出どころを台帳の書き方（memory/<名前>、dev-lead/PATROL.md、RULES.md など）にそろえる。"""
    p = src.replace("\\", "/")
    ws = WORKSPACE.as_posix().rstrip("/") + "/"
    for prefix in (ws, "~/.dan/workspace/", "C:/Users/Owner/.dan/workspace/"):
        if p.lower().startswith(prefix.lower()):
            return p[len(prefix):]
    for name in ("dan-workspace/CLAUDE.md", ".claude/CLAUDE.md"):
        if p.endswith(name):
            return name
    return p


def _grams(text: str) -> set[str]:
    t = re.sub(r"[\s、。，．・「」『』（）()\[\]:：/／\-—…]+", "", text)
    return {t[i:i + 2] for i in range(len(t) - 1)}


def similarity(a: str, b: str) -> float:
    ga, gb = _grams(a), _grams(b)
    return len(ga & gb) / len(ga | gb) if ga and gb else 0.0


def _root_text(root: dict) -> str:
    return root["rule"] + " " + " ".join(i.get("quote", "") + " " + i.get("saw", "") for i in root["items"])


def _judge(text: str, roots: list[dict]) -> list[str] | None:
    """別の AI（Claude CLI・定額）に同じ根っこの root を選ばせる。使えなければ None。"""
    if os.environ.get("DAN_LESSONS_JUDGE", "on") == "off":
        return None
    import shutil
    import subprocess
    import tempfile

    exe = shutil.which("claude")
    if not exe:
        return None
    lines = "\n".join(f"- {r['id']}: {r['rule']}" for r in roots)
    prompt = (
        "あなたは指摘の台帳の整理役です。新しい指摘が、台帳のどの根っこ（一般則）と同じ原因から来ているかを選びます。\n"
        "言葉が似ているかではなく、守っていれば今回の失敗が起きなかったかで選びます。無ければ空にします。\n\n"
        f"<台帳の根っこ>\n{lines}\n</台帳の根っこ>\n\n<新しい指摘>\n{text}\n</新しい指摘>\n\n"
        '出力は JSON 1つだけ: {"roots": ["近い順の id", …最大3つ]}'
    )
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "CLAUDECODE")}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [exe, "-p", "--model", os.environ.get("DAN_LESSONS_MODEL", "sonnet"), "--output-format", "json",
                 "--tools", "", "--strict-mcp-config", "--no-session-persistence"],
                input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=int(os.environ.get("DAN_LESSONS_TIMEOUT", "90")), cwd=tmp, env=env,
            )
        result = json.loads(proc.stdout).get("result", "")
        picked = json.loads(result[result.find("{"):result.rfind("}") + 1]).get("roots") or []
    except Exception:  # noqa: BLE001
        return None
    ids = {r["id"] for r in roots}
    return [p for p in picked if p in ids]


def find(text: str, ledger: dict, limit: int = 3) -> list[tuple[dict, float, bool]]:
    """(root, 似ている度合い, 判定役が選んだか) を近い順に返す。"""
    roots = ledger["roots"]
    scored = sorted(((r, similarity(text, _root_text(r))) for r in roots), key=lambda x: -x[1])
    picked = _judge(text, roots)
    if picked is None:
        return [(r, s, False) for r, s in scored[:limit] if s > 0]
    by_id = {r["id"]: (r, s) for r, s in scored}
    out = [(by_id[i][0], by_id[i][1], True) for i in picked[:limit]]
    for r, s in scored:
        if len(out) >= limit:
            break
        if r["id"] not in picked and s >= 0.12:
            out.append((r, s, False))
    return out


def _next_item_id(ledger: dict) -> str:
    nums = [int(i["id"][1:]) for r in ledger["roots"] for i in r["items"] if re.fullmatch(r"I\d+", i["id"])]
    return f"I{(max(nums) if nums else 0) + 1:03d}"


def cmd_find(args) -> int:
    ledger = load()
    hits = find(args.text, ledger)
    if not hits:
        print("同じ根っこは見つかりませんでした。新しい根っこにする時は --new-root と --why-new で足してください。")
    for r, s, judged in hits:
        mark = "判定役が選んだ" if judged else f"言葉の重なり {s:.2f}"
        print(f"- {r['id']}（{mark}）: {r['rule']}\n  分け方: {KINDS.get(r['kind'], r['kind'])} / 今の点検: {r['check']['state']}"
              f"（{'、'.join(r['check']['by'])}）\n  例: 「{r['items'][0]['quote']}」")
    print(f"[lessons] find candidates={','.join(r['id'] for r, _, _ in hits) or '-'}")
    return 0


def cmd_add(args) -> int:
    ledger = load()
    src = norm_src(args.src)
    item = {"id": _next_item_id(ledger), "date": args.date or date.today().isoformat(), "where": args.where,
            "saw": args.saw, "quote": args.quote, "src": src, "added": datetime.now().isoformat(timespec="seconds")}
    if args.root:
        root = next((r for r in ledger["roots"] if r["id"] == args.root), None)
        if root is None:
            print(f"根っこ {args.root} がありません。find で探し直してください。", file=sys.stderr)
            return 1
        item["repeat"] = args.repeat or "同じ根っこにまた来た"
    else:
        if not (args.new_root and args.kind and args.why_new):
            print("--root か、--new-root・--kind・--why-new の3つを書いてください。", file=sys.stderr)
            return 1
        if args.kind not in KINDS:
            print(f"--kind は {', '.join(KINDS)} のどれかです。", file=sys.stderr)
            return 1
        rid = args.id or re.sub(r"[^a-z0-9-]", "", args.new_root.lower())[:24] or f"r{len(ledger['roots']) + 1}"
        if any(r["id"] == rid for r in ledger["roots"]):
            print(f"根っこの id {rid} はもうあります。--id で別の id を付けてください。", file=sys.stderr)
            return 1
        root = {"id": rid, "rule": args.new_root, "kind": args.kind, "why_new": args.why_new,
                "check": {"state": "無し", "by": []}, "next": args.next or "", "items": []}
        ledger["roots"].append(root)
    root["items"].append(item)
    save(ledger)
    if args.root and root["kind"] == "machine" and root["check"]["state"] in STRUCTURAL:
        print(f"この根っこは {'、'.join(root['check']['by'])} が止めているはずの所です。記憶に文章を足すより、"
              "その点検がなぜ通したかを調べて点検を広げてください（文章の注意は症状で、直すのは仕組み）。")
    elif args.root and root["check"]["state"] == "文章だけ":
        print(f"この根っこは、まだ文章だけで守っています。次にすること: {root['next']}")
    print(f"[lessons] added id={item['id']} root={root['id']} src={src}")
    return 0


def cmd_touch(args) -> int:
    ledger = load()
    src = norm_src(args.src)
    ledger.setdefault("touches", []).append({"src": src, "why": args.why, "at": datetime.now().isoformat(timespec="seconds")})
    save(ledger)
    print(f"[lessons] touch src={src}")
    return 0


def _cell(text: str) -> str:
    return (text or "").replace("|", "／").replace("\n", " ")


def table(ledger: dict) -> str:
    roots = ledger["roots"]
    n_items = sum(len(r["items"]) for r in roots)
    repeats = sum(1 for r in roots for i in r["items"] if i.get("repeat"))
    order = {"machine": 0, "skill": 1, "owner": 2, "spec": 3}
    lines = [
        "# みきさんの指摘の台帳",
        "",
        f"指摘 {n_items} 件を、同じ根っこごとに {len(roots)} 件にまとめました。そのうち {repeats} 件は、同じ指摘が2回以上来た物です。",
        "",
        "分け方: " + "、".join(f"{label} {sum(1 for r in roots if r['kind'] == k)}件" for k, label in KINDS.items()),
        "",
        "| 決まり（同じ根っこ） | 指摘 | 分け方 | 今の点検 | 例（元の言葉） | 次にすること |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(roots, key=lambda r: (order.get(r["kind"], 9), -len(r["items"]))):
        ex = next((i for i in r["items"] if not i.get("quote", "").startswith("（")), r["items"][0])
        rep = sum(1 for i in r["items"] if i.get("repeat"))
        count = f"{len(r['items'])}件" + (f"（うち2回目以上 {rep}）" if rep else "")
        state = r["check"]["state"]
        lines.append(f"| {_cell(r['rule'])} | {count} | {KINDS.get(r['kind'], r['kind'])} | {_cell(state)} | "
                     f"「{_cell(ex['quote'])}」（{ex.get('date') or '日付なし'}、{_cell(ex['where'])}） | {_cell(r.get('next', ''))} |")
    if ledger.get("unsure"):
        lines += ["", "## 確かめたい（決まりにしていない）", ""]
        lines += [f"- {u['question']}" for u in ledger["unsure"]]
    if ledger.get("subtract"):
        lines += ["", "## まとめられる記憶（まだ触っていない）", ""]
        lines += [f"- {u['why']}" for u in ledger["subtract"]]
    return "\n".join(lines) + "\n"


def cmd_table(args) -> int:
    out = Path(args.out) if args.out else LEDGER.with_name("TABLE.md")
    out.write_text(table(load()), encoding="utf-8")
    print(f"[lessons] table {out}")
    return 0


def weekly(ledger: dict, days: int, today: date | None = None) -> dict:
    today = today or date.today()
    since = today - timedelta(days=days)
    recent, repeats = [], []
    for r in ledger["roots"]:
        for i in r["items"]:
            when = (i.get("added") or i.get("date") or "")[:10]
            if when and when >= since.isoformat():
                recent.append((r, i))
                if i.get("repeat"):
                    repeats.append((r, i))
    text_only = [r for r in ledger["roots"] if r["kind"] == "machine" and r["check"]["state"] in ("文章だけ", "無し")
                 and len(r["items"]) >= 2]
    overlaps = []
    roots = ledger["roots"]
    for a in range(len(roots)):
        for b in range(a + 1, len(roots)):
            s = similarity(roots[a]["rule"], roots[b]["rule"])
            if s >= 0.3:
                overlaps.append((roots[a]["id"], roots[b]["id"], round(s, 2)))
    known = {s for r in roots for i in r["items"] for s in (i["src"], i.get("dup"))} \
        | {u["src"] for u in ledger.get("unsure", [])} | {u["src"] for u in ledger.get("not_owner", [])} \
        | {t["src"] for t in ledger.get("touches", [])} | {f for u in ledger.get("subtract", []) for f in u["files"]}
    mem = WORKSPACE / "memory"
    loose = sorted(f"memory/{p.name}" for p in mem.glob("feedback*.md") if f"memory/{p.name}" not in known) if mem.is_dir() else []
    return {"since": since.isoformat(), "recent": recent, "repeats": repeats, "text_only": text_only,
            "overlaps": overlaps, "loose": loose}


def cmd_weekly(args) -> int:
    w = weekly(load(), args.days)
    print(f"{w['since']} から: 新しい指摘 {len(w['recent'])} 件、そのうち同じ根っこに2回目以上 {len(w['repeats'])} 件")
    for r, i in w["repeats"]:
        print(f"- 効いていない: {r['id']}（今の点検: {r['check']['state']}）「{i['quote']}」 {i.get('date')}")
    for r in w["text_only"]:
        print(f"- 機械で止めるはずなのに文章だけ: {r['id']}（{len(r['items'])}件）次: {r.get('next', '')}")
    for a, b, s in w["overlaps"]:
        print(f"- 重なっているかもしれない根っこ: {a} と {b}（{s}）")
    for f in w["loose"]:
        print(f"- 台帳を通らずにある記憶: {f}")
    print(f"[lessons] weekly recent={len(w['recent'])} repeats={len(w['repeats'])} loose={len(w['loose'])}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("find")
    p.add_argument("text")
    p = sub.add_parser("add")
    p.add_argument("--root")
    p.add_argument("--new-root")
    p.add_argument("--kind")
    p.add_argument("--why-new")
    p.add_argument("--id")
    p.add_argument("--next")
    p.add_argument("--quote", required=True)
    p.add_argument("--saw", required=True)
    p.add_argument("--where", required=True)
    p.add_argument("--src", required=True)
    p.add_argument("--date")
    p.add_argument("--repeat")
    p = sub.add_parser("touch")
    p.add_argument("--src", required=True)
    p.add_argument("--why", required=True)
    p = sub.add_parser("table")
    p.add_argument("--out")
    p = sub.add_parser("weekly")
    p.add_argument("--days", type=int, default=7)
    args = ap.parse_args(argv)
    return {"find": cmd_find, "add": cmd_add, "touch": cmd_touch, "table": cmd_table, "weekly": cmd_weekly}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
