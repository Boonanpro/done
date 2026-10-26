# -*- coding: utf-8 -*-
"""みきさんの指摘の台帳（~/.dan/workspace/lessons/ledger.json）を読み書きする。

2026-10-25 本人:「足す前に、まとめられないか探して汎化させるのは超大事」。それまでダンは、
指摘を受けるたびに記憶の feedback を1件足すだけで、同じ根っこの指摘が別々の記憶に積み上がり、
同じ発言が2つの記憶に入っている物もあった。

台帳は2つに分ける。
  statements: 発言。1つの発言は1件（いつ・どこで・何を見て・元の言葉・出どころ・案件のタグ）。
              status は rule（根っこに入れた）/ unsure（確かめたい。決まりにしない）/ spec（作りの希望）。
              origin=dan はダン自身の観察で、本人の指摘の件数に入れない。
  roots:      同じ対策で防げる根っこ（一般則・分け方・今の点検・点検を入れた日 since・次にすること）。
              発言の id を並べる。1つの発言を複数の根っこに付けてよい。
分け方は machine=機械で止める / skill=スキルに書いて試験する / owner=みきさんに残す。
「効いていない」は、点検を入れた日（since）より後に、同じ根っこにまた来た発言だけ。

  python scripts/lessons.py find "<指摘の要点>"          同じ根っこを探す（足す前に必ず）
  python scripts/lessons.py add --root <id> --quote … --saw … --where … --src memory/feedback-x.md
  python scripts/lessons.py add --new-root "<一般則>" --kind skill --why-new "<近い根っこに入らない理由>" …
  python scripts/lessons.py add --unsure "<みきさんに確かめたいこと>" --quote … （決まりにしない）
  python scripts/lessons.py touch --src memory/feedback-x.md --why "<指摘ではない直し>"   1回の書き込みだけ通す
  python scripts/lessons.py table                        みきさんに見せる表（TABLE.md）を作り直す
  python scripts/lessons.py weekly [--days 7]            週1回のまとめ直しの材料

add は発言の id（例 S110）を返す。記憶や決まりの文書には、その発言を書く所に「(lessons:S110)」を
入れる。書く時の関所（hook_lesson_gate.py）は、今回書き足す中身にある発言の id と台帳を照合する。
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import fcntl
except ImportError:  # Windows の控え
    fcntl = None
    import msvcrt

WORKSPACE = Path(os.environ.get("DAN_WORKSPACE_DIR") or (Path.home() / ".dan" / "workspace"))
LEDGER = Path(os.environ.get("DAN_LESSONS_LEDGER") or (WORKSPACE / "lessons" / "ledger.json"))
KINDS = {"machine": "機械で止める", "skill": "スキルに書いて試験する", "owner": "みきさんに残す"}
STRUCTURAL = {"守れている", "一部"}
REF = re.compile(r"lessons:(S\d+)")


def load() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _save(ledger: dict) -> None:
    ledger["updated"] = date.today().isoformat()
    fd, tmp = tempfile.mkstemp(prefix=".ledger.", suffix=".tmp", dir=LEDGER.parent)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(ledger, ensure_ascii=False, indent=1) + "\n")
    os.replace(tmp, LEDGER)


@contextlib.contextmanager
def editing():
    """読み込み・採番・保存を1つの排他の中でする（何部屋も同時に add しても1件も消えない）。"""
    with open(LEDGER.with_name(".ledger.lock"), "a+") as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        else:
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        try:
            ledger = load()
            yield ledger
            _save(ledger)
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)
            else:
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)


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


def statements(ledger: dict) -> dict[str, dict]:
    return {s["id"]: s for s in ledger["statements"]}


def _root_text(root: dict, st: dict) -> str:
    return root["rule"] + " " + " ".join(st[i]["quote"] + " " + st[i]["saw"] for i in root["statements"] if i in st)


def _judge(text: str, roots: list[dict]) -> list[str] | None:
    """別の AI（Claude CLI・定額）に同じ根っこの root を選ばせる。使えなければ None。"""
    if os.environ.get("DAN_LESSONS_JUDGE", "on") == "off":
        return None
    import shutil
    import subprocess

    exe = shutil.which("claude")
    if not exe:
        return None
    lines = "\n".join(f"- {r['id']}: {r['rule']}" for r in roots)
    prompt = (
        "あなたは指摘の台帳の整理役です。新しい指摘が、台帳のどの根っこ（一般則）と同じ対策で防げるかを選びます。\n"
        "言葉が似ているかではなく、その根っこを守っていれば今回の失敗が起きなかったかで選びます。無ければ空にします。\n\n"
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
    st = statements(ledger)
    roots = ledger["roots"]
    scored = sorted(((r, similarity(text, _root_text(r, st))) for r in roots), key=lambda x: -x[1])
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


def find_unsure(text: str, ledger: dict) -> list[dict]:
    return [s for s in ledger["statements"] if s["status"] == "unsure"
            and similarity(text, s["quote"] + " " + s["saw"] + " " + s.get("question", "")) >= 0.08]


def cmd_find(args) -> int:
    ledger = load()
    st = statements(ledger)
    hits = find(args.text, ledger)
    for s in find_unsure(args.text, ledger):
        print(f"- 確かめたい（決まりにしていない）{s['id']}: {s.get('question', '')}\n  同じ話なら決まりにせず、みきさんに確かめてください。")
    if not hits:
        print("同じ根っこは見つかりませんでした。新しい根っこにする時は --new-root と --why-new で足してください。")
    for r, s, judged in hits:
        mark = "判定役が選んだ" if judged else f"言葉の重なり {s:.2f}"
        ex = st[r["statements"][0]]
        print(f"- {r['id']}（{mark}）: {r['rule']}\n  分け方: {KINDS.get(r['kind'], r['kind'])} / 今の点検: {r['check']['state']}"
              f"（{'、'.join(r['check']['by'])}）\n  例: 「{ex['quote']}」")
    print(f"[lessons] find candidates={','.join(r['id'] for r, _, _ in hits) or '-'}")
    return 0


def _same(a: str, b: str) -> bool:
    return re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b)


def cmd_add(args) -> int:
    src = norm_src(args.src)
    with editing() as ledger:
        st = statements(ledger)
        roots = {r["id"]: r for r in ledger["roots"]}
        existing = next((s for s in ledger["statements"] if s["src"] == src and _same(s["quote"], args.quote)), None)
        if existing and existing["status"] == "unsure" and not args.unsure:
            print(f"この発言は確かめたい物（{existing['id']}）です。決まりにせず、みきさんに確かめてください: "
                  f"{existing.get('question', '')}", file=sys.stderr)
            return 1
        if args.unsure:
            s = existing or _new_statement(ledger, args, src)
            s["status"], s["question"] = "unsure", args.unsure
            for r in ledger["roots"]:
                if s["id"] in r["statements"]:
                    r["statements"].remove(s["id"])
            print(f"[lessons] unsure id={s['id']} src={src}")
            return 0
        if args.root:
            root = roots.get(args.root)
            if root is None:
                print(f"根っこ {args.root} がありません。find で探し直してください。", file=sys.stderr)
                return 1
        else:
            if not (args.new_root and args.kind and args.why_new):
                print("--root か、--new-root・--kind・--why-new の3つを書いてください。", file=sys.stderr)
                return 1
            if args.kind not in KINDS:
                print(f"--kind は {', '.join(KINDS)} のどれかです。", file=sys.stderr)
                return 1
            rid = args.id or re.sub(r"[^a-z0-9-]", "", args.new_root.lower())[:24] or f"r{len(roots) + 1}"
            root = roots.get(rid)
            if root is not None and not _same(root["rule"], args.new_root):
                print(f"根っこの id {rid} はもうあります。--id で別の id を付けてください。", file=sys.stderr)
                return 1
            if root is None:
                root = {"id": rid, "rule": args.new_root, "kind": args.kind, "why_new": args.why_new,
                        "check": {"state": "無し", "by": [], "since": None}, "next": args.next or "", "statements": []}
                ledger["roots"].append(root)
        s = existing or _new_statement(ledger, args, src)
        again = s["id"] in root["statements"]
        if not again:
            root["statements"].append(s["id"])
        since = root["check"].get("since")
        if since and (s.get("date") or "") > since:
            print(f"この根っこには {since} に点検を入れています（{'、'.join(root['check']['by'])}）。その後に来たので、"
                  "点検が効いていません。記憶に文章を足すより、点検がなぜ通したかを調べて点検を直してください。")
        elif root["check"]["state"] in ("文章だけ", "無し"):
            print(f"この根っこは、まだ点検がありません。次にすること: {root['next']}")
        print(f"記憶や決まりの文書には、この発言を書く所に (lessons:{s['id']}) を入れてください。")
        print(f"[lessons] added id={s['id']} root={root['id']} src={src}" + (" again" if again or existing else ""))
    return 0


def _new_statement(ledger: dict, args, src: str) -> dict:
    nums = [int(s["id"][1:]) for s in ledger["statements"] if re.fullmatch(r"S\d+", s["id"])]
    s = {"id": f"S{(max(nums) if nums else 0) + 1:03d}", "date": args.date or date.today().isoformat(),
         "where": args.where, "saw": args.saw, "quote": args.quote, "src": src, "origin": args.origin,
         "status": "rule", "tags": [t for t in (args.tags or "").split(",") if t],
         "added": datetime.now().isoformat(timespec="seconds")}
    if args.said_before:
        s["said_before"] = args.said_before
    ledger["statements"].append(s)
    return s


def cmd_touch(args) -> int:
    src = norm_src(args.src)
    with editing() as ledger:
        touches = ledger.setdefault("touches", [])
        tid = f"T{len(touches) + 1}"
        touches.append({"id": tid, "src": src, "why": args.why, "at": datetime.now().isoformat(timespec="seconds"), "used": False})
    print(f"[lessons] touch id={tid} src={src}")
    return 0


def use_touch(tid: str, src: str) -> bool:
    """関所が1回の書き込みに1つの touch を使う。使えたら True。"""
    with editing() as ledger:
        t = next((t for t in ledger.get("touches", []) if t["id"] == tid and t["src"] == src), None)
        if not t or t.get("used"):
            return False
        t["used"] = datetime.now().isoformat(timespec="seconds")
        return True


def counts(ledger: dict) -> dict:
    st = ledger["statements"]
    linked = {i for r in ledger["roots"] for i in r["statements"]}
    owner = [s for s in st if s["status"] == "rule" and s["origin"] == "owner"]
    return {
        "owner": len(owner), "dan": sum(1 for s in st if s["status"] == "rule" and s["origin"] == "dan"),
        "unsure": sum(1 for s in st if s["status"] == "unsure"), "spec": sum(1 for s in st if s["status"] == "spec"),
        "roots": len(ledger["roots"]), "said_before": sum(1 for s in owner if s.get("said_before")),
        "links": sum(len(r["statements"]) for r in ledger["roots"]),
        "unlinked": sorted(s["id"] for s in st if s["status"] == "rule" and s["id"] not in linked),
    }


def not_working(ledger: dict, since_day: str = "") -> list[tuple[dict, dict]]:
    """点検を入れた日より後に、同じ根っこにまた来た本人の発言。"""
    st = statements(ledger)
    out = []
    for r in ledger["roots"]:
        since = r["check"].get("since")
        if not since:
            continue
        for i in r["statements"]:
            s = st.get(i)
            if s and s["origin"] == "owner" and (s.get("date") or "") > since and (s.get("date") or "") >= since_day:
                out.append((r, s))
    return out


def _cell(text: str) -> str:
    return (text or "").replace("|", "／").replace("\n", " ")


def table(ledger: dict) -> str:
    c = counts(ledger)
    st = statements(ledger)
    roots = ledger["roots"]
    nw = not_working(ledger)
    order = {"machine": 0, "skill": 1, "owner": 2}
    lines = [
        "# みきさんの指摘の台帳",
        "",
        f"みきさんの指摘 {c['owner']} 件を、同じ対策で防げる根っこごとに {c['roots']} 件にまとめました。"
        f"1つの発言が2つの根っこに効く物もあるので、根っこへの付け方は {c['links']} 本です。",
        f"そのうち {c['said_before']} 件は、みきさんが「前も言った」と言った物です。"
        f"点検を入れた後にまた来た物は {len(nw)} 件です。",
        f"ほかに、ダン自身の観察 {c['dan']} 件、確かめたい物 {c['unsure']} 件、作りの希望 {c['spec']} 件は、指摘の数に入れていません。",
        "",
        "分け方: " + "、".join(f"{label} {sum(1 for r in roots if r['kind'] == k)}件" for k, label in KINDS.items()),
        "",
        "| 決まり（同じ根っこ） | 指摘 | 分け方 | 今の点検 | 例（元の言葉） | 次にすること |",
        "|---|---|---|---|---|---|",
    ]
    for r in sorted(roots, key=lambda r: (order.get(r["kind"], 9), -len(r["statements"]))):
        mine = [st[i] for i in r["statements"] if i in st]
        owner = [s for s in mine if s["origin"] == "owner"]
        ex = next((s for s in owner if not s["quote"].startswith("（")), (owner or mine)[0])
        said = sum(1 for s in owner if s.get("said_before"))
        count = f"{len(owner)}件" + (f"（うち「前も言った」{said}）" if said else "") + \
            (f"＋ダンの観察{len(mine) - len(owner)}" if len(mine) > len(owner) else "")
        tags = sorted({t for s in mine for t in s.get("tags", [])})
        rule = _cell(r["rule"]) + (f"<br>案件: {'、'.join(tags)}" if tags else "")
        lines.append(f"| {rule} | {count} | {KINDS.get(r['kind'], r['kind'])} | {r['check']['state']} | "
                     f"「{_cell(ex['quote'])}」（{ex.get('date') or '日付なし'}、{_cell(ex['where'])}） | {_cell(r.get('next', ''))} |")
    unsure = [s for s in ledger["statements"] if s["status"] == "unsure"]
    if unsure:
        lines += ["", "## 確かめたい（決まりにしていない）", ""]
        lines += [f"- {s.get('question', '')}" for s in unsure]
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
    since = (today - timedelta(days=days)).isoformat()
    st = statements(ledger)
    recent = [s for s in ledger["statements"] if s["origin"] == "owner" and (s.get("added") or s.get("date") or "")[:10] >= since]
    nw = not_working(ledger, since)
    text_only = [r for r in ledger["roots"] if r["kind"] == "machine" and r["check"]["state"] in ("文章だけ", "無し")
                 and sum(1 for i in r["statements"] if st.get(i, {}).get("origin") == "owner") >= 2]
    overlaps = []
    roots = ledger["roots"]
    for a in range(len(roots)):
        for b in range(a + 1, len(roots)):
            s = similarity(roots[a]["rule"], roots[b]["rule"])
            if s >= 0.3:
                overlaps.append((roots[a]["id"], roots[b]["id"], round(s, 2)))
    known = {x for s in ledger["statements"] for x in (s["src"], s.get("dup"))} \
        | {u["src"] for u in ledger.get("not_owner", [])} | {t["src"] for t in ledger.get("touches", [])} \
        | {f for u in ledger.get("subtract", []) for f in u["files"]}
    mem = WORKSPACE / "memory"
    loose = sorted(f"memory/{p.name}" for p in mem.glob("feedback*.md") if f"memory/{p.name}" not in known) if mem.is_dir() else []
    return {"since": since, "recent": recent, "not_working": nw, "text_only": text_only, "overlaps": overlaps,
            "loose": loose, "unlinked": counts(ledger)["unlinked"]}


def cmd_weekly(args) -> int:
    w = weekly(load(), args.days)
    print(f"{w['since']} から: みきさんの新しい指摘 {len(w['recent'])} 件、点検を入れた後にまた来た物 {len(w['not_working'])} 件")
    for r, s in w["not_working"]:
        print(f"- 効いていない: {r['id']}（{r['check']['since']} に点検）「{s['quote']}」 {s.get('date')}")
    for r in w["text_only"]:
        print(f"- 機械で止めるはずなのに点検が無い: {r['id']} 次: {r.get('next', '')}")
    for a, b, s in w["overlaps"]:
        print(f"- 重なっているかもしれない根っこ: {a} と {b}（{s}）")
    for f in w["loose"]:
        print(f"- 台帳を通らずにある記憶: {f}")
    for i in w["unlinked"]:
        print(f"- どの根っこにも付いていない発言: {i}")
    print(f"[lessons] weekly recent={len(w['recent'])} not_working={len(w['not_working'])} loose={len(w['loose'])}")
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
    p.add_argument("--unsure")
    p.add_argument("--quote", required=True)
    p.add_argument("--saw", required=True)
    p.add_argument("--where", required=True)
    p.add_argument("--src", required=True)
    p.add_argument("--date")
    p.add_argument("--said-before")
    p.add_argument("--tags")
    p.add_argument("--origin", choices=("owner", "dan"), default="owner")
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
