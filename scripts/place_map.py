"""場所の地図を作る・確かめる（地図の形と使い道は app/agent/place_map.py と docs/places/README.md）。

  python scripts/place_map.py list                         共通の場所と成果物の地図の状態の一覧
  python scripts/place_map.py check <場所>                 地図が今の画面と合っているか（終わりに [place_map] の行）
  python scripts/place_map.py draft <slug> [名前]          地図が無い成果物に、コードから下書きを作る（書く所は「（ここを書く）」）
  python scripts/place_map.py stamp <場所> [--unchanged 理由]  地図を直し終えた後、指紋と「コードから」の節を書き直して check する
  python scripts/place_map.py speak --room <id>            その部屋の話すダンに渡る <place> の前置きを見る

<場所> は artifact:<slug>、slug だけ、または共通の場所の id（chat / artifact-tab / dev-lead-room / mobile）。
stamp は、画面が前の stamp から変わったのに説明が1字も変わっていなければ断る（--unchanged で理由を残せば通る）。
終了コード（check / stamp）: 0=FRESH / 1=STALE か DRAFT か断った / 2=MISSING。
最後の行「[place_map] place=<場所> result=… root=<木>」を、ターンの終わりの関所（scripts/hook_artifact_verify_gate.py）が読む。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.agent import place_map as pm  # noqa: E402

EXIT = {"FRESH": 0, "STALE": 1, "DRAFT": 1, "MISSING": 2}


def line(pid: str, state: str) -> str:
    return f"[place_map] place={pid} result={state} root={pm.tree_of(pid).as_posix()}"


def report(pid: str) -> int:
    state, why = pm.map_state(pid)
    print(f"{pid}: {why}")
    print(line(pid, state))
    return EXIT[state]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("check").add_argument("place")
    st = sub.add_parser("stamp")
    st.add_argument("place")
    st.add_argument("--unchanged", default="", help="画面は変わったが説明を変えなくてよい理由（地図に残る）")
    d = sub.add_parser("draft")
    d.add_argument("slug")
    d.add_argument("name", nargs="?", default="")
    s = sub.add_parser("speak")
    s.add_argument("--room", required=True)
    s.add_argument("--project")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for pid in pm.common_places():
            print(f"場所 {pid}: {pm.map_state(pid)[0]}")
        if pm.ARTIFACTS_DIR.is_dir():
            for d in sorted(p for p in pm.ARTIFACTS_DIR.iterdir() if p.is_dir() and not p.name.startswith(("_", "[")) and p.name != "publish"):
                print(f"成果物 {d.name}: {pm.map_state('artifact:' + d.name)[0]}")
        return 0
    if a.cmd == "check":
        return report(pm.place_id(a.place))
    if a.cmd == "draft":
        pid = f"artifact:{a.slug}"
        path = pm.map_path(pid)
        if not path.parent.is_dir():
            print(f"成果物のフォルダがありません: {path.parent}")
            return 2
        if path.exists():
            print(f"地図はもうあります: {path}（直したら stamp）")
            return report(pid)
        path.write_text(pm.draft_text(a.slug, a.name), encoding="utf-8")
        print(f"下書きを作りました: {path}")
        return report(pid)
    if a.cmd == "stamp":
        pid = pm.place_id(a.place)
        path = pm.map_path(pid)
        if not path.exists():
            print(f"地図がありません。成果物なら先に draft: python scripts/place_map.py draft {pid.split(':', 1)[-1]}")
            print(line(pid, "MISSING"))
            return 2
        if pm.TODO in path.read_text(encoding="utf-8"):
            return report(pid)
        old = path.read_text(encoding="utf-8")
        try:
            new = pm.stamp_text(pid, a.unchanged)
        except pm.StampRefused as e:
            print(f"stamp しませんでした: {e}")
            print(line(pid, "STALE"))
            return 1
        path.write_text(new, encoding="utf-8")
        gone, added = pm.inventory_changes(old, new)
        if gone or added:
            print("「コードから」の節で変わった手がかり。上の4つの節がこれに合っているかを見る:")
            for x in added:
                print(f"  + {x}")
            for x in gone:
                print(f"  - {x}")
        return report(pid)
    if a.cmd == "speak":
        print(pm.place_context(a.room, a.project) or "（この部屋の場所の地図はありません）")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
