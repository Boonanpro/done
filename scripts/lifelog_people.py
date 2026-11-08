"""Who is who in the lifelog: look, and correct (app/services/lifelog_speakers.py).

Dan runs this when the owner says a name is wrong (「話者3は中村さん」「スヤさんって出てるの違う人」) or asks who was
there. Every change re-writes the day's text, and a name given here is also kept in the voice book, so the next day
the same voice gets the name by itself.

  python scripts/lifelog_people.py day 2026-11-07            # the day's voices: label, minutes, lines they said
  python scripts/lifelog_people.py name 2026-11-07 3 中村さん   # voice 3 is 中村さん (also: --owner for みきさん)
  python scripts/lifelog_people.py not 2026-11-07 3           # voice 3 is not who it says; take the name off
  python scripts/lifelog_people.py merge 2026-11-07 5 3       # voice 5 is the same person as voice 3
  python scripts/lifelog_people.py people                     # the voice book
  python scripts/lifelog_people.py rename スヤさん 須山さん      # the person's name in the book (every day re-written)
  python scripts/lifelog_people.py names 2026-11-07           # read names out of the day's talk now
  python scripts/lifelog_people.py redo 2026-11-07            # number the day's voices again (then: names)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services import lifelog, lifelog_speakers as sp  # noqa: E402


def show_day(day: str, lines: int = 3) -> None:
    state, book = sp.day_state(day), sp.people()
    said = {}
    for r in lifelog.read_day(day):
        for t in r.get("turns") or []:
            if t.get("voice") and len(t["text"]) >= 8:
                said.setdefault(t["voice"], []).append(f"{r['start'][11:16]} {t['text'][:60]}")
    for key, vo in sorted(state["voices"].items(), key=lambda kv: -kv[1]["s"]):
        if vo["s"] < 3:
            continue
        g = vo.get("guess") or {}
        print(f"話者{key}: {sp.label(day, key, state, book)}  {vo['s'] / 60:.1f}分"
              + (f"  根拠「{g.get('quote', '')[:50]}」" if g.get("quote") and not vo.get("who") else ""))
        for l in said.get(key, [])[:lines]:
            print("   ", l)


def merge(day: str, src: str, dst: str) -> None:
    with sp._lock:
        state = sp.day_state(day)
        a, b = state["voices"][src], state["voices"][dst]
        total = a["s"] + b["s"]
        b["c"] = sp._round(sp._unit(sp._unit(a["c"]) * a["s"] + sp._unit(b["c"]) * b["s"]))
        b["s"] = round(total, 1)
        if a.get("who") and not b.get("who"):
            b["who"] = a["who"]
        state["voices"].pop(src)
        sp.save_day(day, state)
        path = lifelog.index_file(day)
        rows = lifelog.read_day(day)
        for r in rows:
            for t in r.get("turns") or []:
                if t.get("voice") == src:
                    t["voice"] = dst
        lifelog._upsert(day, rows)
        for f in (lifelog.AUDIO_ROOT / day).glob("*.json"):
            e = json.loads(f.read_text(encoding="utf-8"))
            hit = False
            for t in e.get("turns") or []:
                if t.get("voice") == src:
                    t["voice"], hit = dst, True
            for v in (e.get("voices") or {}).values():
                if v.get("day_voice") == src:
                    v["day_voice"], hit = dst, True
            if hit:
                f.write_text(json.dumps(e, ensure_ascii=False), encoding="utf-8")
    sp.rerender_day(day)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("day"); d.add_argument("day"); d.add_argument("--lines", type=int, default=3)
    n = sub.add_parser("name"); n.add_argument("day"); n.add_argument("voice"); n.add_argument("name", nargs="?", default="")
    n.add_argument("--owner", action="store_true")
    x = sub.add_parser("not"); x.add_argument("day"); x.add_argument("voice")
    m = sub.add_parser("merge"); m.add_argument("day"); m.add_argument("src"); m.add_argument("dst")
    sub.add_parser("people")
    r = sub.add_parser("rename"); r.add_argument("old"); r.add_argument("new")
    a = sub.add_parser("names"); a.add_argument("day")
    rd = sub.add_parser("redo"); rd.add_argument("day")
    o = ap.parse_args()
    if o.cmd == "day":
        show_day(o.day, o.lines)
    elif o.cmd == "name":
        name = sp.OWNER_NAME if o.owner else o.name
        if not name:
            sys.exit("name か --owner を")
        sp.remember_voice(o.day, o.voice, name, owner=o.owner or sp.is_owner_name(name), by="owner")
        with sp._lock:
            st = sp.day_state(o.day)
            st["voices"][o.voice]["by_owner"] = True
            sp.save_day(o.day, st)
        show_day(o.day, 1)
    elif o.cmd == "not":
        sp.forget_name(o.day, o.voice)
        show_day(o.day, 1)
    elif o.cmd == "merge":
        merge(o.day, o.src, o.dst)
        show_day(o.day, 1)
    elif o.cmd == "people":
        for pid, p in sp.people()["people"].items():
            print(f"{p['name']}{'（本人）' if p.get('owner') else ''}  声の見本{len(p.get('x', []))}件  {p.get('since', '')}から  {p.get('by', '')}")
    elif o.cmd == "rename":
        with sp._lock:
            book = sp.people()
            pid = sp.person_by_name(book, o.old)
            if not pid:
                sys.exit(f"{o.old} は声の台帳にいません")
            book["people"][pid]["name"] = o.new
            sp.save_people(book)
        for f in sp.SPEAKERS_ROOT.glob("20??-??-??.json"):
            if any(v.get("who") == pid for v in sp.day_state(f.stem)["voices"].values()):
                sp.rerender_day(f.stem)
        print("ok")
    elif o.cmd == "redo":
        print(sp.replace_day(o.day), "recordings")
        show_day(o.day, 1)
    elif o.cmd == "names":
        for g in sp.name_day(o.day, min_seconds=5):
            print(g)
        sp.mark_named(o.day)
        show_day(o.day, 1)


if __name__ == "__main__":
    main()
