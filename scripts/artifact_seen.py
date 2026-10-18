"""本人が開いている成果物の画面が、今のファイルの版で動いているかを見る。

ダンが成果物を直した後、完了と言う前に使う。ダンのブラウザ（テスト用アカウント）で
見えたことは、本人の画面の証拠にならない（2026-10-18: ダンの確認では出ていたボタンが、
本人の画面では古い部品のせいで出なかった）。

画面（/preview/<slug>、開発サーバー 3001）は自分の部品の版を知らせてくる
（frontend/src/lib/live-version/guard.ts → .tmp/live-views.json）。古ければ画面が
自分で読み直すので、--wait で新しい版に替わるまで待てる。

  python scripts/artifact_seen.py --slug x-operation --wait 90
  python scripts/artifact_seen.py               # 本人が開いている成果物の画面を全部

成果物に裏側（<slug>/_server）があれば、本番の裏側（8000）が今のファイルの版で動いているかも
見る（app/services/artifact_backends.py が .tmp/artifact-backends.json に書く）。裏側が古い間は、
画面が新しくても「直った」とは言えないので NG にする。

公開版（専用の Vercel の写し）も見る。スマホのアプリは成果物をこの写しで開く。写しは
ファイルが1分静かになってから作り直される（app/services/artifact_freshness.py が
.tmp/artifact-releases.json に何から作ったかを書く）。古い間は NG。

終了コード: 0=本人の開いている画面と裏側が全部今の版 / 1=古い版の画面か裏側がある / 2=本人は開いていない
最後の行に「[artifact_seen] slug=<slug> result=OK|NG|UNCHECKED」を出す（ターンの終わりの関所 hook_artifact_verify_gate.py が読む）。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 版の数え方は裏側と同じ関数を使う。app パッケージを読むと設定の読み込みが走るので、ファイルだけ読む。
_spec = importlib.util.spec_from_file_location("dan_artifact_backends_tool", ROOT / "app" / "services" / "artifact_backends.py")
artifact_backends = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(artifact_backends)

_fspec = importlib.util.spec_from_file_location("dan_artifact_freshness_tool", ROOT / "app" / "services" / "artifact_freshness.py")
artifact_freshness = importlib.util.module_from_spec(_fspec)
_fspec.loader.exec_module(artifact_freshness)
RELEASE_STALE_S = 300   # ダン本体が60秒おきに書く
BACKEND_STALE_S = 120   # 裏側は30秒おきに状態を書く。これより古ければ止まっているか、仕組みより前の本体
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


def backend_line(slug: str) -> tuple[bool, str] | None:
    """本番の裏側（8000）がこの成果物の今のファイルで動いているか。裏側の無い成果物は None。"""
    if not (artifact_backends.ARTIFACTS / slug / "_server" / "routes.py").is_file():
        return None
    files = artifact_backends.fingerprint(slug)
    head = f"{slug} の裏側（_server・本番 8000）"
    try:
        data = json.loads(artifact_backends.STATE_FILE.read_text(encoding="utf-8"))
        beat = datetime.fromisoformat(data["heartbeat"])
        age = (datetime.now(timezone.utc) - beat).total_seconds()
    except (OSError, ValueError, KeyError):
        data, age = None, 1e9
    if data is None or age > BACKEND_STALE_S:
        return False, (f"NG  {head}: 動いている裏側の版が分からない。本体がこの仕組みより前の版で動いている"
                       "（_server の直しは本体の再起動まで入らない）か、裏側が止まっている")
    row = (data.get("sites") or {}).get(slug) or {}
    if row.get("loaded") == files:
        return True, f"OK  {head}: 今のファイル {files} で動いている"
    state = row.get("state") or ""
    why = row.get("error") or ""
    if state == "reloading" or (not state and not why):
        text = "読み直しの途中（数秒で替わる）"
    elif state == "needs-restart":
        text = f"本体の再起動が要る。{why}"
    elif state == "failed":
        text = f"新しいコードを読み込めず、古い版のまま動いている。{why}"
    else:
        text = f"古い版 {row.get('loaded') or '（不明）'} で動いている。{why}"
    return False, f"NG  {head}: {text}（今のファイルは {files}）"


def release_line(slug: str) -> tuple[bool, str] | None:
    """公開版（スマホのアプリが開く Vercel の写し）が今のファイルから作られたか。公開していなければ None。"""
    head = f"{slug} の公開版（スマホのアプリが開く写し）"
    try:
        data = json.loads(artifact_freshness.SNAPSHOT.read_text(encoding="utf-8"))
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(data["at"])).total_seconds()
    except (OSError, ValueError, KeyError):
        return False, (f"NG  {head}: 何から作られたか分からない（ダン本体がこの仕組みより前の版で動いている"
                       "＝再起動待ち、または止まっている）")
    row = (data.get("sites") or {}).get(slug)
    if row is None:
        return None if age <= RELEASE_STALE_S else (False, f"NG  {head}: 何から作られたか分からない（記録が {int(age)} 秒前で止まっている）")
    state = artifact_freshness.release_state(slug, row, deploying=bool(row.get("deploying")))
    if state in ("current", "none"):
        return True, f"OK  {head}: 今のファイルから作られている"
    if age > RELEASE_STALE_S:
        return False, f"NG  {head}: 古い写しのまま（記録が {int(age)} 秒前で止まっている）"
    if state == "updating":
        return False, (f"NG  {head}: 作り直しを待っている／作り直している（ファイルが1分静かになってから数分）。"
                       "それまでスマホでは古い版が出る")
    return False, f"NG  {head}: 作り直しに失敗して古い写しのまま（status={row.get('status')}）。スマホでは古い版が出る"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slug", help="成果物の slug（省略で全部）")
    parser.add_argument("--wait", type=float, default=0, help="本人の画面が今の版になるまで最大この秒数待つ")
    parser.add_argument("--all-users", action="store_true", help="本人以外（テスト用アカウント等）の画面も出す")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

    deadline = time.time() + args.wait
    while True:
        version = current_version()
        tabs = open_tabs(args.slug, args.all_users)
        results = [describe(row, version) for row in tabs]
        targets = [args.slug] if args.slug else sorted({row.get("slug") for row in tabs if row.get("slug")})
        backends = [b for b in (backend_line(s) for s in targets) if b]
        backends += [b for b in (release_line(s) for s in targets) if b]
        backend_ok = all(ok for ok, _ in backends)
        all_ok = bool(results) and all(ok for ok, _ in results) and backend_ok
        if all_ok or (not results and backend_ok) or time.time() >= deadline:
            break
        time.sleep(2)

    code = 0 if all_ok else (1 if results or not backend_ok else 2)
    verdict = {0: "OK", 1: "NG", 2: "UNCHECKED"}[code]
    if args.json:
        print(json.dumps({"version": version, "tabs": tabs, "backends": [line for _, line in backends],
                          "all_current": all_ok, "result": verdict}, ensure_ascii=False, indent=1))
        return code
    target = f"「{args.slug}」" if args.slug else "成果物"
    if not version:
        print("今のファイルの版が分からない（成果物プレビュー用の開発サーバー 3001 が止まっている可能性）")
    for _, line in backends:
        print(line)
    if not results:
        print(f"本人は{target}の画面を開いていない（開いている画面からの知らせが無い）。"
              "本人の画面では確かめられていない、と報告すること。")
    for _, line in results:
        print(line)
    if code == 1:
        print("→ まだ直ったとは言えない。上の NG の理由をそのまま本人に伝える。")
    meaning = {"OK": "本人の画面と裏側が今の版", "NG": "まだ古い所がある", "UNCHECKED": "本人の画面では未確認"}[verdict]
    print(f"[artifact_seen] slug={args.slug or '*'} result={verdict}（{meaning}）")
    return code


if __name__ == "__main__":
    sys.exit(main())
