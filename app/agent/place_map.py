"""場所の地図: ダンが話す場所と成果物ごとに、みきさんに何が見えていて、どう開き、何が表示できないかを書いた地図を読む。

2026-10-25 ローレン・タンさんの講演（機能の地図、pstack の create-verification-skill）から。ダンは自分の返事が
画面でどう見えるかを知らず、ボードの話し合いで番号の並びが消えているのに気づけなかった。地図は2つに使う。
- 話すダン: 部屋がどの画面に出ているかを見分け、その場所の地図の「話す時に」を前置きに入れる（place_context）。
- 直すダン: scripts/place_shot.py が地図の open と probe で画面を開いて撮り、表示できるはずの物を測る。

共通の場所の地図は docs/places/<id>.md、成果物の地図は frontend/src/app/artifacts/<slug>/MAP.md。
どちらも先頭に YAML の前書き（place, name, open, speak, probe, shows）、本文はローレンさんの地図と同じ4つの節。
成果物の地図の前書きの fingerprint は、画面のファイルから作った指紋。画面を書き換えると合わなくなり、
scripts/place_map.py check が STALE を返す（scripts/hook_artifact_verify_gate.py がそれを見て止める）。
"""
from __future__ import annotations

import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any, Optional

import yaml

ROOT = Path(__file__).resolve().parents[2]
PLACES_DIR = ROOT / "docs" / "places"
ARTIFACTS_DIR = Path(os.environ.get("DAN_ARTIFACTS_DIR") or (ROOT / "frontend" / "src" / "app" / "artifacts"))
MAP_NAME = "MAP.md"
AUTO_START, AUTO_END = "<!-- place_map:auto:start -->", "<!-- place_map:auto:end -->"
TODO = "（ここを書く）"
SCREEN_EXT = {".tsx", ".ts", ".jsx", ".js", ".css", ".scss", ".mdx"}
NOT_SCREEN = re.compile(r"(^|/)(_server|node_modules|\.next[^/]*)(/|$)|\.gen\.json$|(^|/)MAP\.md$")
FRONT = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


# --- 地図を読む ---------------------------------------------------------------------------------------------

def read_map(path: Path) -> Optional[dict[str, Any]]:
    """地図1枚 → {meta, body, path}。無い・読めない時は None。"""
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
    return {"meta": meta if isinstance(meta, dict) else {}, "body": text[m.end():] if m else text, "path": path}


def place_map(place_id: str) -> Optional[dict[str, Any]]:
    """共通の場所（chat / dev-lead-room / artifact-tab / mobile）か artifact:<slug> の地図。"""
    if place_id.startswith("artifact:"):
        return read_map(ARTIFACTS_DIR / place_id.split(":", 1)[1] / MAP_NAME)
    return read_map(PLACES_DIR / f"{place_id}.md")


def common_places() -> list[str]:
    return sorted(p.stem for p in PLACES_DIR.glob("*.md") if p.stem != "README")


# --- 成果物の地図の指紋 ----------------------------------------------------------------------------------------

def screen_files(slug: str) -> list[Path]:
    base = ARTIFACTS_DIR / slug
    out = []
    for p in base.rglob("*"):
        rel = p.relative_to(base).as_posix()
        if p.is_file() and p.suffix in SCREEN_EXT and not NOT_SCREEN.search(rel):
            out.append(p)
    return sorted(out)


def fingerprint(slug: str) -> str:
    h = hashlib.sha1()
    base = ARTIFACTS_DIR / slug
    for p in screen_files(slug):
        h.update(p.relative_to(base).as_posix().encode())
        h.update(b"\0")
        h.update(p.read_bytes().replace(b"\r\n", b"\n"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def map_state(slug: str) -> tuple[str, str]:
    """成果物の地図の状態: (FRESH|STALE|MISSING|DRAFT, 理由)。"""
    m = place_map(f"artifact:{slug}")
    if m is None:
        return "MISSING", f"{ARTIFACTS_DIR / slug / MAP_NAME} がありません"
    if TODO in m["body"] or TODO in str(m["meta"].get("speak") or ""):
        return "DRAFT", f"「{TODO}」が残っています。みきさんから見た中身・行き方・動かし方・落とし穴を書いてください"
    want = fingerprint(slug)
    if str(m["meta"].get("fingerprint") or "") != want:
        return "STALE", "画面のファイルが地図を書いた後に変わっています。変わった所の地図を直してから stamp してください"
    return "FRESH", "画面のファイルと地図が合っています"


# --- コードから書き出す部分（地図の「コードから」の節） ------------------------------------------------------------

HANDLE_RES = [
    ("ラベル", re.compile(r"aria-label=\{?['\"`]([^'\"`{}]{1,40})['\"`]")),
    ("試験の印", re.compile(r"data-testid=\{?['\"`]([^'\"`{}]{1,40})['\"`]")),
    ("ボタンの字", re.compile(r"<button\b[^>]*>\s*([^<>{}\n]{1,24}?)\s*</button>")),
    ("見出し", re.compile(r"<h[1-3]\b[^>]*>\s*([^<>{}\n]{1,30}?)\s*</h[1-3]>")),
]


def code_inventory(slug: str) -> str:
    """成果物のコードから、行き先（ページ）と押せる物の手がかりを書き出す。"""
    base = ARTIFACTS_DIR / slug
    routes = []
    for p in sorted(base.rglob("page.tsx")) + sorted(base.rglob("page.jsx")):
        rel = p.parent.relative_to(base).as_posix()
        if NOT_SCREEN.search(rel + "/"):
            continue
        routes.append(f"/preview/{slug}" + ("" if rel == "." else "/" + rel))
    server = sorted({p.parent.relative_to(base).as_posix() for p in base.rglob("routes.py") if "_server" in p.parts})
    found: dict[str, list[str]] = {}
    for p in screen_files(slug):
        if p.suffix not in {".tsx", ".jsx"}:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for label, rx in HANDLE_RES:
            for hit in rx.findall(text):
                hit = hit.strip()
                if hit and hit not in found.setdefault(label, []):
                    found[label].append(hit)
    lines = ["## コードから（自動）", "", "`python scripts/place_map.py stamp " + slug + "` が書き直す。手で直さない。", ""]
    lines.append("- ページ: " + (", ".join(f"`{r}`" for r in routes) or "無し"))
    if server:
        lines.append("- 裏側: " + ", ".join(f"`{s}`" for s in server))
    for label, _ in HANDLE_RES:
        items = found.get(label) or []
        if items:
            more = f" ほか{len(items) - 30}件" if len(items) > 30 else ""
            lines.append(f"- {label}: " + "、".join(f"「{x}」" for x in items[:30]) + more)
    return "\n".join(lines)


def draft_text(slug: str, name: str = "") -> str:
    meta = {
        "place": f"artifact:{slug}",
        "name": name or slug,
        "open": f"/preview/{slug}",
        "speak": f"- {TODO}（この画面を開いているみきさんに何が見えているか。2〜4行）",
        "shows": [],
        "fingerprint": "",
    }
    body = (
        f"# {name or slug}\n\n{TODO}（この画面でみきさんができること。1段落）\n\n"
        f"## 中にある物\n\n- {TODO}\n\n"
        f"## 行き方（みきさんから見て）\n\n- {TODO}\n\n"
        f"## 道具で動かす\n\n前提:\n\n- `python scripts/place_shot.py artifact:{slug} --tag now` で開けること\n\n- {TODO}\n\n"
        f"## 落とし穴\n\n- {TODO}\n\n"
    )
    return "---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + "---\n" + body + AUTO_START + "\n" + code_inventory(slug) + "\n" + AUTO_END + "\n"


def stamp_text(slug: str) -> str:
    """今の地図の前書きの指紋と「コードから」の節を書き直した全文。"""
    path = ARTIFACTS_DIR / slug / MAP_NAME
    text = path.read_text(encoding="utf-8")
    m = FRONT.match(text)
    if not m:
        raise ValueError(f"{path} の先頭に --- で囲んだ前書きがありません")
    front = m.group(1)
    fp = fingerprint(slug)
    if re.search(r"^fingerprint:.*$", front, re.M):
        front = re.sub(r"^fingerprint:.*$", f"fingerprint: {fp}", front, flags=re.M)
    else:
        front += f"\nfingerprint: {fp}"
    body = text[m.end():]
    auto = AUTO_START + "\n" + code_inventory(slug) + "\n" + AUTO_END
    if AUTO_START in body and AUTO_END in body:
        body = body[: body.index(AUTO_START)] + auto + body[body.index(AUTO_END) + len(AUTO_END):]
    else:
        body = body.rstrip("\n") + "\n\n" + auto + "\n"
    return "---\n" + front + "\n---\n" + body


def inventory_changes(old: str, new: str) -> tuple[list[str], list[str]]:
    """2つの地図の全文の「コードから」の節を比べ、(消えた行, 増えた手がかり) を返す。"""
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


def identify_place(room_id: str, project_id: Optional[str] = None, sb=None) -> dict[str, Any]:
    """部屋 → {kind: dev-lead-room|artifact-tab|chat, slug?, board_slug?}。

    - 開発室の枝・付箋の部屋: 隠れた部屋（metadata.hidden）で、元の部屋（origin_room_id）に dev-lead の成果物がある
    - 成果物タブ: その部屋に登録された成果物（chat_artifact）がある。左がこの部屋の会話、右がその成果物
    - それ以外: チャット（PC のダン本体とスマホのアプリで同じ部屋が見える）
    """
    hit = _place_cache.get(room_id)
    if hit and time.time() - hit[0] < CACHE_SECONDS:
        return hit[1]
    if sb is None:
        from app.services.supabase_client import get_supabase_client
        sb = get_supabase_client().client
    proj = (sb.table("projects").select("id,title,metadata,origin_room_id").eq("room_id", room_id).limit(1).execute()).data or []
    proj = proj[0] if proj else {}
    meta = proj.get("metadata") or {}
    place: dict[str, Any] = {"kind": "chat"}
    origin = proj.get("origin_room_id")
    if origin and isinstance(meta, dict) and meta.get("hidden"):
        rows = (sb.table("chat_artifact").select("slug").eq("room_id", origin).execute()).data or []
        if any(r.get("slug") == "dev-lead" for r in rows):
            place = {"kind": "dev-lead-room", "board_slug": "dev-lead"}
    if place["kind"] == "chat":
        rows = (sb.table("chat_artifact").select("slug,label,updated_at").eq("room_id", room_id)
                .order("updated_at", desc=True).limit(5).execute()).data or []
        if not rows and (project_id or proj.get("id")):
            rows = (sb.table("chat_artifact").select("slug,label,updated_at").eq("project_id", project_id or proj["id"])
                    .order("updated_at", desc=True).limit(5).execute()).data or []
        slugs = [r["slug"] for r in rows if r.get("slug")]
        if slugs:
            place = {"kind": "artifact-tab", "slug": slugs[0], "others": slugs[1:]}
    _place_cache[room_id] = (time.time(), place)
    return place


def _speak_lines(m: Optional[dict[str, Any]]) -> str:
    if not m:
        return ""
    speak = str(m["meta"].get("speak") or "").strip()
    return "" if TODO in speak else speak


def place_context(room_id: str, project_id: Optional[str] = None, sb=None) -> str:
    """話すダンへ渡す <place> の前置き。地図が無い・読めない時は空。"""
    try:
        place = identify_place(room_id, project_id, sb)
    except Exception:
        return ""
    common = place_map(place["kind"])
    if not common:
        return ""
    name = common["meta"].get("name") or place["kind"]
    lines = ["<place>", f"みきさんがこの部屋を見ている場所: {name}"]
    speak = _speak_lines(common)
    if speak:
        lines.append(speak)
    maps = [str(common["path"])]
    slug = place.get("slug") or place.get("board_slug")
    if slug:
        art = place_map(f"artifact:{slug}")
        art_speak = _speak_lines(art)
        if art_speak:
            lines.append(f"画面の中身（{art['meta'].get('name') or slug}）:")
            lines.append(art_speak)
            maps.append(str(art["path"]))
        elif place["kind"] == "artifact-tab":
            lines.append(f"右の画面は成果物 {slug}。地図はまだ無い（{ARTIFACTS_DIR / slug / MAP_NAME}）")
    if place.get("others"):
        lines.append("この部屋の成果物タブで切り替えられるほかの成果物: " + "、".join(place["others"]))
    lines.append("地図の全文: " + " / ".join(maps))
    lines.append("</place>")
    return "\n".join(lines)
