"""場所の地図を作る・確かめる（地図の形と使い道は app/agent/place_map.py と docs/places/README.md）。

  python scripts/place_map.py list                 共通の場所と成果物の地図の状態の一覧
  python scripts/place_map.py check <slug>         成果物の地図が今の画面と合っているか（終わりに [place_map] の行）
  python scripts/place_map.py draft <slug> [名前]   地図が無い成果物に、コードから下書きを作る（書く所は「（ここを書く）」）
  python scripts/place_map.py stamp <slug>         地図を直し終えた後、指紋と「コードから」の節を書き直して check する
  python scripts/place_map.py speak --room <id>    その部屋の話すダンに渡る <place> の前置きを見る

終了コード（check / stamp）: 0=FRESH / 1=STALE か DRAFT / 2=MISSING。
ターンの終わりの関所（scripts/hook_artifact_verify_gate.py）は、成果物の画面を書き換えた後に
「[place_map] slug=<slug> result=FRESH」が出ているかを見る。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import place_map as pm  # noqa: E402

EXIT = {"FRESH": 0, "STALE": 1, "DRAFT": 1, "MISSING": 2}


def report(slug: str) -> int:
    state, why = pm.map_state(slug)
    print(f"{slug}: {why}")
    print(f"[place_map] slug={slug} result={state}")
    return EXIT[state]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    for name in ("check", "stamp"):
        sub.add_parser(name).add_argument("slug")
    d = sub.add_parser("draft")
    d.add_argument("slug")
    d.add_argument("name", nargs="?", default="")
    s = sub.add_parser("speak")
    s.add_argument("--room", required=True)
    s.add_argument("--project")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for pid in pm.common_places():
            m = pm.place_map(pid)
            print(f"場所 {pid}: {m['meta'].get('name') if m else '読めない'}")
        for d in sorted(p for p in pm.ARTIFACTS_DIR.iterdir() if p.is_dir() and not p.name.startswith(("_", "[")) and p.name != "publish"):
            print(f"成果物 {d.name}: {pm.map_state(d.name)[0]}")
        return 0
    if a.cmd == "check":
        return report(a.slug)
    if a.cmd == "draft":
        path = pm.ARTIFACTS_DIR / a.slug / pm.MAP_NAME
        if not (pm.ARTIFACTS_DIR / a.slug).is_dir():
            print(f"成果物のフォルダがありません: {path.parent}")
            return 2
        if path.exists():
            print(f"地図はもうあります: {path}（直したら stamp）")
            return report(a.slug)
        path.write_text(pm.draft_text(a.slug, a.name), encoding="utf-8")
        print(f"下書きを作りました: {path}")
        return report(a.slug)
    if a.cmd == "stamp":
        path = pm.ARTIFACTS_DIR / a.slug / pm.MAP_NAME
        if not path.exists():
            print(f"地図がありません。先に draft: python scripts/place_map.py draft {a.slug}")
            print(f"[place_map] slug={a.slug} result=MISSING")
            return 2
        old = path.read_text(encoding="utf-8")
        new = pm.stamp_text(a.slug)
        path.write_text(new, encoding="utf-8")
        gone, added = pm.inventory_changes(old, new)
        if gone or added:
            print("「コードから」の節で変わった手がかり。上の4つの節がこれに合っているかを見る:")
            for x in added:
                print(f"  + {x}")
            for x in gone:
                print(f"  - {x}")
        return report(a.slug)
    if a.cmd == "speak":
        print(pm.place_context(a.room, a.project) or "（この部屋の場所の地図はありません）")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
