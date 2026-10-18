"""本人が開いている成果物の画面が、今のファイルの版で動いているかを見る。

ダンが成果物を直した後、完了と言う前に使う。ダンのブラウザ（テスト用アカウント）で
見えたことは、本人の画面の証拠にならない（2026-10-18: ダンの確認では出ていたボタンが、
本人の画面では古い部品のせいで出なかった）。

画面（/preview/<slug>、開発サーバー 3001）は自分の部品の版を知らせてくる
（frontend/src/lib/live-version/guard.ts → .tmp/live-views.json）。古ければ画面が
自分で読み直すので、--wait で新しい版に替わるまで待てる。

  python scripts/artifact_seen.py --slug x-operation --wait 90
  python scripts/artifact_seen.py               # 本人が開いている成果物の画面を全部

終了コード: 0=本人の開いている画面が全部今の版 / 1=古い版の画面がある / 2=本人は開いていない
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / ".tmp" / "live-views.json"
GEN = ROOT / "frontend" / "src" / "lib" / "live-version" / "current.gen.ts"
OWNER_EMAIL = os.getenv("DAN_OWNER_EMAIL", "0aw325171@gmail.com").strip().lower()
OWNER_ID = os.getenv("DAN_OWNER_USER_ID", "").strip()

REASONS = {
    "typing": "本人が入力中なので読み直しを待っている（「新しい版があります」のボタンを出している）",
    "typed": "本人が入力した後なので読み直しを待っている（ボタンを出している）",
    "saving": "保存の途中なので読み直しを待っている",
    "unsaved": "未保存の内容があるので読み直しを待っている（ボタンを出している）",
    "reload-loop": "読み直しても直らなかったので止まっている（ボタンを出している）。部品の作り直しに失敗している可能性",
}


def current_version() -> str:
    try:
        m = re.search(r"LIVE_VERSION = '([0-9a-f]*)'", GEN.read_text(encoding="utf-8"))
        return m.group(1) if m else ""
    except OSError:
        return ""


def load_rows() -> list[dict]:
    try:
        return list(json.loads(STORE.read_text(encoding="utf-8")).get("tabs", {}).values())
    except (OSError, ValueError):
        return []


def is_owner(row: dict) -> bool:
    if OWNER_ID and row.get("user_id") == OWNER_ID:
        return True
    return (row.get("email") or "").lower() == OWNER_EMAIL


def age_seconds(row: dict) -> float:
    try:
        seen = datetime.fromisoformat(row["seen_at"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return 1e9
    return (datetime.now(timezone.utc) - seen).total_seconds()


# 画面は前に出ている間60秒おき、裏にある間4分おきに知らせてくる。それより長く
# 知らせが無い画面は、閉じた（閉じる知らせが届かなかった）とみなす。
VISIBLE_STALE_S = 150
HIDDEN_STALE_S = 330


def open_tabs(slug: str | None, all_users: bool) -> list[dict]:
    rows = []
    for row in load_rows():
        if not all_users and not is_owner(row):
            continue
        if slug and row.get("slug") != slug:
            continue
        limit = VISIBLE_STALE_S if row.get("visible") else HIDDEN_STALE_S
        if row.get("state") == "closed" or age_seconds(row) > limit:
            continue
        rows.append(row)
    rows.sort(key=lambda r: (r.get("slug") or "", r.get("tab") or ""))
    return rows


def describe(row: dict, version: str) -> tuple[bool, str]:
    where = "成果物タブの中" if row.get("frame") == "frame" else "単独のタブ"
    device = "スマホ" if re.search(r"Mobile|Android|iPhone", row.get("ua") or "") else "PC"
    seen = datetime.fromisoformat(row["seen_at"].replace("Z", "+00:00")).astimezone().strftime("%H:%M:%S")
    who = "" if is_owner(row) else f"［{row.get('email') or row.get('user_id', '')[:8]}］"
    head = f"{who}{row.get('slug')} {row.get('path')}（{device}・{where}・{'前に出ている' if row.get('visible') else '裏にある'}・最後の知らせ {seen}）"
    loaded = row.get("loaded")
    if loaded and loaded == version:
        return True, f"OK  {head}: 今の版 {version} で動いている"
    if row.get("state") == "reloading":
        return False, f"…   {head}: 新しい版に読み直している途中"
    reason = REASONS.get(row.get("reason") or "", "")
    if not loaded:
        state = "この仕組みより前の部品で動いている"
    else:
        state = f"古い版 {loaded} で動いている（今は {version}）"
    if row.get("state") in ("checking", "current") and not reason:
        reason = "HMR で届くのを待っている。届かなければ15秒ほどで画面が自分で読み直す"
    return False, f"NG  {head}: {state}" + (f"。{reason}" if reason else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", help="成果物の slug（省略で全部）")
    parser.add_argument("--wait", type=float, default=0, help="本人の画面が今の版になるまで最大この秒数待つ")
    parser.add_argument("--all-users", action="store_true", help="本人以外（テスト用アカウント等）の画面も出す")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    deadline = time.time() + args.wait
    while True:
        version = current_version()
        tabs = open_tabs(args.slug, args.all_users)
        results = [describe(row, version) for row in tabs]
        all_ok = bool(results) and all(ok for ok, _ in results)
        if all_ok or not results or time.time() >= deadline:
            break
        time.sleep(2)

    if args.json:
        print(json.dumps({"version": version, "tabs": tabs, "all_current": all_ok}, ensure_ascii=False, indent=1))
    else:
        target = f"「{args.slug}」" if args.slug else "成果物"
        if not version:
            print("今のファイルの版が分からない（成果物プレビュー用の開発サーバー 3001 が止まっている可能性）")
        if not results:
            print(f"本人は{target}の画面を開いていない（開いている画面からの知らせが無い）。"
                  "本人の画面では確かめられていない、と報告すること。")
            return 2
        for _, line in results:
            print(line)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
