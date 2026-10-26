"""場所の地図: ダンが話す場所と成果物ごとに、みきさんに何が見えていて、どう開き、何が表示できないかを書いた地図を読む。

2026-10-25 ローレン・タンさんの講演（機能の地図、pstack の create-verification-skill）から。ダンは自分の返事が
画面でどう見えるかを知らず、ボードの話し合いで番号の並びが消えているのに気づけなかった。地図は2つに使う。
- 話すダン: 部屋がどの画面に出ているかを見分け、その場所の地図の speak を前置きに入れる（place_context）。
  どの端末から書いたか（room-clients.json）と、みきさんの画面が今どの成果物を出しているか（live-views.json）を材料にし、
  分からない時は断定しない。
- 直すダン: scripts/place_shot.py が地図の open・ready・probe で画面を開いて撮り、表示できるはずの物を測る。

共通の場所の地図は docs/places/<id>.md、成果物の地図は frontend/src/app/artifacts/<slug>/MAP.md。
どちらも先頭に YAML の前書き（place, name, open, speak, probe, shows, …）、本文はローレンさんの地図と同じ4つの節。
地図は自分が説明する画面のファイルを持つ（成果物は _server と MAP.md 以外の画面のファイル、共通の場所は前書きの
watches）。stamp した時のファイルごとの指紋を「コードから」の節に残し、ファイルが変わると check が STALE を返す。
stamp は、画面が変わったのに説明（前書きと4つの節）が1字も変わっていなければ断る。説明を変えなくてよい直し
（見た目の崩れを直しただけ等）は --unchanged "理由" で理由を地図に残して通す。
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLACES_DIR = Path(os.environ.get("DAN_PLACES_DIR") or (ROOT / "docs" / "places"))
ARTIFACTS_DIR = Path(os.environ.get("DAN_ARTIFACTS_DIR") or (ROOT / "frontend" / "src" / "app" / "artifacts"))
RUNTIME_DIR = Path(os.environ.get("DAN_PLACE_RUNTIME_DIR") or (ROOT / ".tmp"))
MAP_NAME = "MAP.md"
AUTO_START, AUTO_END = "<!-- place_map:auto:start -->", "<!-- place_map:auto:end -->"
FILES_RE = re.compile(r"<!-- place_map:files (\{.*?\}) -->", re.S)
TODO = "（ここを書く）"
SCREEN_EXT = {".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".mdx"}
NOT_SCREEN = re.compile(r"(^|/)(_server|node_modules|\.next[^/]*)(/|$)|\.gen\.json$|(^|/)MAP\.md$")
FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)
STAMP_KEYS = ("fingerprint", "described", "last_review")


# --- 地図を読む ---------------------------------------------------------------------------------------------

def read_map(path: Path) -> Optional[dict[str, Any]]:
    """地図1枚 → {meta, body, path, text}。無い・読めない時は None。"""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    m = FRONT.match(text)
    meta: dict[str, Any] = {}
    if m:
        try:
            meta = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            meta = {}
    return {"meta": meta if isinstance(meta, dict) else {}, "body": text[m.end():] if m else text, "path": path, "text": text}


def place_id(arg: str) -> str:
    """slug だけなら artifact:<slug>。共通の場所の id はそのまま。"""
    return arg if arg.startswith("artifact:") or arg in common_places() else f"artifact:{arg}"


def map_path(pid: str) -> Path:
    if pid.startswith("artifact:"):
        return ARTIFACTS_DIR / pid.split(":", 1)[1] / MAP_NAME
    return PLACES_DIR / f"{pid}.md"


def place_map(pid: str) -> Optional[dict[str, Any]]:
    """共通の場所（chat / dev-lead-room / artifact-tab / mobile）か artifact:<slug> の地図。"""
    return read_map(map_path(pid))


def common_places() -> list[str]:
    return sorted(p.stem for p in PLACES_DIR.glob("*.md") if p.stem != "README")


def tree_of(pid: str) -> Path:
    """その地図のある木（動いているダンか作業場所）。関所が、どこで確かめたかを見分けるのに使う。"""
    return ARTIFACTS_DIR.parents[3] if pid.startswith("artifact:") else PLACES_DIR.parents[1]


# --- 地図が説明する画面のファイルと指紋 ------------------------------------------------------------------------

def screen_files(pid: str) -> dict[str, Path]:
    """地図が説明する画面のファイル（木か成果物のフォルダからの相対パス → 実物）。無い所は含めない。"""
    out: dict[str, Path] = {}
    if pid.startswith("artifact:"):
        base = ARTIFACTS_DIR / pid.split(":", 1)[1]
        for p in base.rglob("*"):
            rel = p.relative_to(base).as_posix()
            if p.is_file() and p.suffix in SCREEN_EXT and not NOT_SCREEN.search(rel):
                out[rel] = p
        return dict(sorted(out.items()))
    m = place_map(pid)
    tree = tree_of(pid)
    for pattern in (m["meta"].get("watches") or []) if m else []:
        for p in tree.glob(pattern):
            if p.is_file():
                out[p.relative_to(tree).as_posix()] = p
    return dict(sorted(out.items()))


def file_hashes(pid: str) -> dict[str, str]:
    return {rel: hashlib.sha1(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()[:10] for rel, p in screen_files(pid).items()}


def fingerprint_of(hashes: dict[str, str]) -> str:
    return hashlib.sha1(json.dumps(hashes, sort_keys=True).encode()).hexdigest()[:16]


def stamped_files(text: str) -> dict[str, str]:
    m = FILES_RE.search(text)
    try:
        return json.loads(m.group(1)) if m else {}
    except ValueError:
        return {}


def described_hash(text: str) -> str:
    """説明の部分（前書きから指紋と記録の欄を除いた物と、「コードから」の節より前の本文）の指紋。"""
    m = FRONT.match(text)
    front = m.group(1) if m else ""
    front = "\n".join(line for line in front.splitlines() if not line.startswith(STAMP_KEYS))
    body = text[m.end():] if m else text
    if AUTO_START in body:
        body = body[: body.index(AUTO_START)]
    return hashlib.sha1((front.strip() + "\n" + body.strip()).encode()).hexdigest()[:16]


def map_state(pid: str) -> tuple[str, str]:
    """地図の状態: (FRESH|STALE|MISSING|DRAFT, 理由)。"""
    m = place_map(pid)
    if m is None:
        return "MISSING", f"{map_path(pid)} がありません"
    if TODO in m["text"]:
        return "DRAFT", f"「{TODO}」が残っています。みきさんから見た中身・行き方・動かし方・落とし穴を書いてください"
    now = file_hashes(pid)
    if str(m["meta"].get("fingerprint") or "") != fingerprint_of(now):
        old = stamped_files(m["text"])
        absent = absent_artifacts(pid, old)
        if absent and old and {f: h for f, h in old.items() if not _in(f, absent)} == {f: h for f, h in now.items() if not _in(f, absent)}:
            # 成果物は done-artifacts にあり、作業場所には写さない限り無い。無い成果物のファイルは見ずに比べる
            return "FRESH", "画面のファイルと地図が合っています（この木に無い成果物 " + "、".join(sorted(absent)) + " は見ていない）"
        return "STALE", "画面のファイルが地図を書いた後に変わっています: " + changed_summary(old, now)
    return "FRESH", "画面のファイルと地図が合っています"


def absent_artifacts(pid: str, files: dict[str, str]) -> set[str]:
    """共通の場所の地図が見張る成果物のファイルのうち、この木に成果物のフォルダごと無いもの（slug の集まり）。"""
    if pid.startswith("artifact:"):
        return set()
    tree = tree_of(pid)
    slugs = {f.split("/")[4] for f in files if f.startswith("frontend/src/app/artifacts/") and f.count("/") >= 5}
    return {s for s in slugs if not (tree / "frontend/src/app/artifacts" / s).is_dir()}


def _in(f: str, slugs: set[str]) -> bool:
    return any(f.startswith(f"frontend/src/app/artifacts/{s}/") for s in slugs)


def changed_summary(old: dict[str, str], new: dict[str, str]) -> str:
    changed = [f for f in new if f in old and old[f] != new[f]]
    added = [f for f in new if f not in old]
    gone = [f for f in old if f not in new]
    parts = ([f"変わった {', '.join(changed)}"] if changed else []) + ([f"増えた {', '.join(added)}"] if added else []) \
        + ([f"消えた {', '.join(gone)}"] if gone else [])
    return "、".join(parts) or "（前の記録が無い）"


# --- コードから書き出す部分（地図の「コードから」の節） ------------------------------------------------------------

HANDLE_RES = [
    ("ラベル", re.compile(r"aria-label=\{?['\"`]([^'\"`{}]{1,40})['\"`]")),
    ("試験の印", re.compile(r"data-testid=\{?['\"`]([^'\"`{}]{1,40})['\"`]")),
    ("ボタンの字", re.compile(r"<button\b[^>]*>\s*([^<>{}\n]{1,24}?)\s*</button>")),
    ("見出し", re.compile(r"<h[1-3]\b[^>]*>\s*([^<>{}\n]{1,30}?)\s*</h[1-3]>")),
]


def code_inventory(pid: str, hashes: Optional[dict[str, str]] = None) -> str:
    """地図が説明するコードから、行き先（ページ）と押せる物の手がかり、ファイルごとの指紋を書き出す。"""
    files = screen_files(pid)
    lines = ["## コードから（自動）", "", f"`python scripts/place_map.py stamp {pid}` が書き直す。手で直さない。", ""]
    if pid.startswith("artifact:"):
        slug = pid.split(":", 1)[1]
        base = ARTIFACTS_DIR / slug
        routes = [f"/preview/{slug}" + ("" if rel == "." else "/" + rel)
                  for rel in sorted(p.parent.relative_to(base).as_posix() for p in base.rglob("page.[tj]sx"))
                  if not NOT_SCREEN.search(rel + "/")]
        server = sorted({p.parent.relative_to(base).as_posix() for p in base.rglob("routes.py") if "_server" in p.parts})
        lines.append("- ページ: " + (", ".join(f"`{r}`" for r in routes) or "無し"))
        if server:
            lines.append("- 裏側: " + ", ".join(f"`{s}`" for s in server))
    else:
        lines.append("- 見張るファイル: " + (", ".join(f"`{f}`" for f in files) or "無し"))
    found: dict[str, list[str]] = {}
    for p in files.values():
        if p.suffix not in {".tsx", ".jsx"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for label, rx in HANDLE_RES:
            for hit in rx.findall(text):
                hit = hit.strip()
                if hit and hit not in found.setdefault(label, []):
                    found[label].append(hit)
    for label, _ in HANDLE_RES:
        items = found.get(label) or []
        if items:
            more = f" ほか{len(items) - 30}件" if len(items) > 30 else ""
            lines.append(f"- {label}: " + "、".join(f"「{x}」" for x in items[:30]) + more)
    lines.append("")
    lines.append("<!-- place_map:files " + json.dumps(hashes if hashes is not None else file_hashes(pid), ensure_ascii=False, sort_keys=True) + " -->")
    return "\n".join(lines)


def draft_text(slug: str, name: str = "") -> str:
    pid = f"artifact:{slug}"
    meta = {
        "place": pid,
        "name": name or slug,
        "open": f"/preview/{slug}",
        "ready": f"{TODO}（開けたと分かる CSS の印。本物の画面の部品）",
        "speak": f"- {TODO}（この画面を開いているみきさんに何が見えているか。2〜4行）",
        "shows": [],
    }
    body = (
        f"# {name or slug}\n\n{TODO}（この画面でみきさんができること。1段落）\n\n"
        f"## 中にある物\n\n- {TODO}\n\n"
        f"## 行き方（みきさんから見て）\n\n- {TODO}\n\n"
        f"## 道具で動かす\n\n前提:\n\n- `python scripts/place_shot.py {pid} --tag after` で開けること\n\n- {TODO}\n\n"
        f"## 落とし穴\n\n- {TODO}\n\n"
    )
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body + AUTO_START + "\n" + code_inventory(pid) + "\n" + AUTO_END + "\n"


class StampRefused(Exception):
    pass


def _set_front(front: str, key: str, value: str) -> str:
    line = f"{key}: {json.dumps(value, ensure_ascii=False) if key == 'last_review' else value}"
    if re.search(rf"^{key}:.*$", front, re.M):
        return re.sub(rf"^{key}:.*$", lambda _: line, front, flags=re.M)
    return front.rstrip("\n") + "\n" + line


def stamp_text(pid: str, unchanged: str = "") -> str:
    """地図の指紋・説明の指紋・「コードから」の節を書き直した全文。

    画面が前の stamp から変わったのに説明が1字も変わっていない時は StampRefused（--unchanged の理由があれば通し、
    理由を last_review に残す）。初めての stamp と、画面が変わっていない時の stamp は説明を問わない。
    """
    path = map_path(pid)
    text = path.read_text(encoding="utf-8")
    m = FRONT.match(text)
    if not m:
        raise ValueError(f"{path} の先頭に --- で囲んだ前書きがありません")
    meta = place_map(pid)["meta"]
    old_fp, old_desc = str(meta.get("fingerprint") or ""), str(meta.get("described") or "")
    now = file_hashes(pid)
    fp, desc = fingerprint_of(now), described_hash(text)
    front = m.group(1)
    if old_fp and old_fp != fp and old_desc and old_desc == desc:
        if not unchanged.strip():
            raise StampRefused("画面のファイルが変わったのに、地図の説明が前の stamp から1字も変わっていません（"
                               + changed_summary(stamped_files(text), now) + "）。変わった画面に合わせて説明を直してから stamp する。"
                               "説明を変えなくてよい直し（見た目の崩れを直しただけ等）なら --unchanged \"理由\" を付ける")
        front = _set_front(front, "last_review", f"{datetime.now().strftime('%Y-%m-%d')} 説明は変えない: {unchanged.strip()}")
    front = _set_front(_set_front(front, "fingerprint", fp), "described", desc)
    body = text[m.end():]
    auto = AUTO_START + "\n" + code_inventory(pid, now) + "\n" + AUTO_END
    if AUTO_START in body and AUTO_END in body:
        body = body[: body.index(AUTO_START)] + auto + body[body.index(AUTO_END) + len(AUTO_END):]
    else:
        body = body.rstrip("\n") + "\n\n" + auto + "\n"
    return "---\n" + front + "\n---\n" + body


def inventory_changes(old: str, new: str) -> tuple[list[str], list[str]]:
    """2つの地図の全文の「コードから」の節を比べ、(消えた手がかり, 増えた手がかり) を返す。"""
    def items(text: str) -> set[str]:
        if AUTO_START not in text:
            return set()
        part = text[text.index(AUTO_START):text.find(AUTO_END) if AUTO_END in text else None]
        out = set()
        for line in part.splitlines():
            if line.startswith("- "):
                head, _, rest = line[2:].partition(": ")
                out |= {f"{head}: {x}" for x in re.findall(r"「([^」]+)」|`([^`]+)`", rest) for x in [x[0] or x[1]]}
        return out
    a, b = items(old), items(new)
    return sorted(a - b), sorted(b - a)


# --- 部屋がどの場所に出ているか ------------------------------------------------------------------------------

_place_cache: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_SECONDS = 600
PHONE_UA = re.compile(r"Android|iPhone|iPad|okhttp|Expo|ReactNative|Dalvik|CFNetwork", re.I)
PC_UA = re.compile(r"Windows NT|Macintosh|X11|CrOS", re.I)
CLIENT_FRESH = 30 * 60
SCREEN_FRESH = 3 * 60


def device_of(ua: str) -> str:
    return "phone" if PHONE_UA.search(ua or "") else "pc" if PC_UA.search(ua or "") else ""


DEVICE_NAME = {"phone": "スマホ", "pc": "PC"}


def note_client(room_id: str, user_agent: str) -> None:
    """本人がこの部屋に書いた時の端末を残す（チャットの受け口が呼ぶ）。話すダンが「今どこで読んでいるか」に使う。"""
    if not room_id:
        return
    path = RUNTIME_DIR / "room-clients.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    cutoff = time.time() - 7 * 86400
    data = {k: v for k, v in data.items() if isinstance(v, dict) and v.get("at", 0) > cutoff}
    data[room_id] = {"device": device_of(user_agent), "ua": (user_agent or "")[:160], "at": time.time()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def last_client(room_id: str) -> dict[str, Any]:
    try:
        v = json.loads((RUNTIME_DIR / "room-clients.json").read_text(encoding="utf-8")).get(room_id) or {}
    except (OSError, ValueError):
        return {}
    return v if v and time.time() - float(v.get("at") or 0) < CLIENT_FRESH and v.get("device") else {}


def open_screens(user_id: str, slugs: list[str]) -> list[dict[str, Any]]:
    """本人の画面が今出している成果物（成果物の画面が数秒ごとに知らせる .tmp/live-views.json）。新しい順。"""
    try:
        tabs = json.loads((RUNTIME_DIR / "live-views.json").read_text(encoding="utf-8")).get("tabs") or {}
    except (OSError, ValueError):
        return []
    out = []
    for v in tabs.values():
        try:
            age = time.time() - datetime.fromisoformat(str(v.get("seen_at")).replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        if (not user_id or v.get("user_id") == user_id) and v.get("slug") in slugs and v.get("visible") and age < SCREEN_FRESH:
            out.append({"slug": v["slug"], "in_tab": v.get("frame") == "frame", "device": device_of(v.get("ua") or ""), "age": age})
    return sorted(out, key=lambda x: x["age"])


def identify_place(room_id: str, project_id: Optional[str] = None, sb=None) -> dict[str, Any]:
    """部屋 → {kind: dev-lead-room|artifact-tab|chat, slugs?, user_id}。

    - 開発室の枝・付箋の部屋: 隠れた部屋（metadata.hidden）で、元の部屋（origin_room_id）に dev-lead の成果物がある
    - 成果物タブ: その部屋に登録された成果物（chat_artifact）がある。PC では左がこの部屋の会話、右がどれか1つの成果物
    - それ以外: チャット（PC のダン本体とスマホのアプリで同じ部屋が見える）
    """
    hit = _place_cache.get(room_id)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    if sb is None:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
    proj = (sb.table("projects").select("id,title,metadata,origin_room_id,user_id").eq("room_id", room_id).limit(1).execute()).data or []
    proj = proj[0] if proj else {}
    meta = proj.get("metadata") or {}
    place: dict[str, Any] = {"kind": "chat", "user_id": proj.get("user_id") or ""}
    origin = proj.get("origin_room_id")
    if origin and isinstance(meta, dict) and meta.get("hidden"):
        rows = (sb.table("chat_artifact").select("slug").eq("room_id", origin).execute()).data or []
        if any(r.get("slug") == "dev-lead" for r in rows):
            place.update(kind="dev-lead-room", slugs=["dev-lead"])
    if place["kind"] == "chat":
        rows = (sb.table("chat_artifact").select("slug,label,updated_at").eq("room_id", room_id)
                .order("updated_at", desc=True).limit(8).execute()).data or []
        if not rows and (project_id or proj.get("id")):
            rows = (sb.table("chat_artifact").select("slug,label,updated_at").eq("project_id", project_id or proj["id"])
                    .order("updated_at", desc=True).limit(8).execute()).data or []
        slugs = list(dict.fromkeys(r["slug"] for r in rows if r.get("slug")))
        if slugs:
            place.update(kind="artifact-tab", slugs=slugs)
    _place_cache[room_id] = (time.time(), place)
    return place


def _speak_lines(m: Optional[dict[str, Any]]) -> str:
    if not m:
        return ""
    speak = str(m["meta"].get("speak") or "").strip()
    return "" if TODO in speak else speak


def place_context(room_id: str, project_id: Optional[str] = None, sb=None) -> str:
    """話すダンへ渡す <place> の前置き。地図が無い・読めない時は空。分からない所は分からないと書く。"""
    try:
        place = identify_place(room_id, project_id, sb)
    except Exception:
        return ""
    common = place_map(place["kind"])
    if not common:
        return ""
    lines = ["<place>", f"この部屋が出る場所: {common['meta'].get('name') or place['kind']}"]
    client = last_client(room_id)
    lines.append(f"みきさんがこの部屋に最後に書いた端末: {DEVICE_NAME[client['device']]}" if client
                 else "みきさんがどの端末で読んでいるかは分からない（PC とスマホのどちらとも言わない）")
    speak = _speak_lines(common)
    if speak:
        lines.append(speak)
    maps = [str(common["path"])]
    slugs = place.get("slugs") or []
    if slugs:
        screens = open_screens(place.get("user_id") or "", slugs)
        shown = screens[0]["slug"] if screens else ""
        if shown:
            where = "成果物タブの中" if screens[0]["in_tab"] else "単独のタブ"
            lines.append(f"みきさんの画面に今出ている成果物: {shown}（{DEVICE_NAME.get(screens[0]['device'], '端末不明')}・{where}）")
        elif len(slugs) > 1:
            lines.append("みきさんが今どの成果物を開いているかは分からない（この部屋の成果物: " + "、".join(slugs)
                         + "）。画面の中身の話は、どの成果物かを名前で言ってからする")
        target = shown or (slugs[0] if len(slugs) == 1 else "")
        if target:
            art = place_map(f"artifact:{target}")
            art_speak = _speak_lines(art)
            if art_speak:
                lines.append(f"成果物 {target}（{art['meta'].get('name') or target}）の画面:")
                lines.append(art_speak)
                maps.append(str(art["path"]))
            else:
                lines.append(f"成果物 {target} の地図はまだ無い（{map_path('artifact:' + target)}）")
    lines.append("地図の全文: " + " / ".join(maps))
    lines.append("</place>")
    return "\n".join(lines)
