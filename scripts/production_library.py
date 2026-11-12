"""制作ライブラリをチャットのダンが扱う道具（エディターの中の「ダンと制作」から使う。2026-11-11）。

みきさんは素材をドラッグしない。素材を集めて並べ、作品を作り始めるのはダンの仕事。
ここで登録した素材と作品は、開いているエディターのライブラリにそのまま出る（数秒ごとに読み直す）。

  python scripts/production_library.py list --room <部屋>
  python scripts/production_library.py register --room <部屋> --path <ファイル> [--path …] [--source nas_path]
  python scripts/production_library.py new-content --room <部屋> --title "題" [--format 16:9] [--asset <素材id> …]
  python scripts/production_library.py rename --room <部屋> --content <作品id> --title "題"

--room は本体の部屋でも制作の部屋（ライブラリ・作品の部屋）でもよい。制作の部屋なら本体の部屋に置く。
作品を作った後のタイムラインの編集は、作品の部屋（エディターでその作品を開いた画面の右の欄）で mcp__timeline__* を使う。
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

API = "http://127.0.0.1:8000/api/v1/production-assets"


def _token() -> str:
    from app.services.auth_service import create_access_token
    from app.services.owner import resolve_owner_user_id
    return create_access_token(resolve_owner_user_id(), "", timedelta(minutes=10))


def _call(method: str, path: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode() or "{}")


def _asset_room(room: str) -> str:
    from app.services.editor_rooms import asset_room
    return asset_room(room)


def cmd_list(room: str) -> None:
    from app.services import timeline_draft as td
    d = td._room_dir(room)
    assets = json.loads((d / "assets.json").read_text(encoding="utf-8")) if (d / "assets.json").exists() else []
    contents = td._read_contents_raw(room)
    print(f"部屋 {room}: 素材 {len(assets)} / 作品 {len(contents)}")
    for c in contents[-20:]:
        print(f"  作品 {c.get('id')}  {c.get('title')}  ({c.get('format')}, 素材{len(c.get('asset_ids') or [])})")
    for a in assets[-40:]:
        dur = (a.get("metadata") or {}).get("duration")
        print(f"  素材 {a.get('id')}  {a.get('kind')}  {a.get('status')}  {a.get('filename')}"
              + (f"  {float(dur):.1f}s" if dur else ""))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--room", required=True)
    p = sub.add_parser("register"); p.add_argument("--room", required=True)
    p.add_argument("--path", action="append", required=True)
    p.add_argument("--source", default="local_path", choices=["local_path", "nas_path", "cloud_url", "generated"])
    p = sub.add_parser("new-content"); p.add_argument("--room", required=True)
    p.add_argument("--title", required=True); p.add_argument("--format", default="16:9")
    p.add_argument("--asset", action="append", default=[])
    p = sub.add_parser("rename"); p.add_argument("--room", required=True)
    p.add_argument("--content", required=True); p.add_argument("--title", required=True)
    a = ap.parse_args()
    room = _asset_room(a.room)
    if a.cmd == "list":
        cmd_list(room)
    elif a.cmd == "register":
        for path in a.path:
            r = _call("POST", "/register", {"room_id": room, "uri": path, "source_type": a.source})
            print(json.dumps({k: r.get(k) for k in ("id", "kind", "status", "filename")}, ensure_ascii=False))
    elif a.cmd == "new-content":
        # 空のタイムラインつきで作る: 作品の画面がすぐ開き、ダンがその上で組み立てられる
        r = _call("POST", "/contents", {"room_id": room, "title": a.title, "format": a.format, "asset_ids": a.asset,
                                        "timeline": {"sequence": {"format": a.format, "frame_rate": 30, "duration": 0, "tracks": []}}})
        print(json.dumps({k: r.get(k) for k in ("id", "title", "format", "asset_ids")}, ensure_ascii=False))
    elif a.cmd == "rename":
        r = _call("PATCH", f"/contents/{a.content}?room_id={urllib.parse.quote(room)}", {"title": a.title})
        print(json.dumps({k: r.get(k) for k in ("id", "title")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
