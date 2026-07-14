"""Timeline MCP server — the production agent's ONLY hands and eyes.

Launched per job by the agent runner with context in env:
  DAN_ROOM_ID / DAN_DRAFT_ID / DAN_JOB_ID
Every mutation goes through app.services.timeline_commands (validated, clamped);
the live timeline is NEVER touched here — the orchestrator commits the draft
with compare-and-swap after the session ends. Frames come back as inline images
so the model literally sees the composited draft.
"""

import base64
import json
import logging
import os
import re
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__ + "/.."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mcp.server import Server  # noqa: E402
from mcp.server.stdio import stdio_server  # noqa: E402
import mcp.types as types  # noqa: E402

from app.services import timeline_draft as td  # noqa: E402
from app.services import timeline_commands as tc  # noqa: E402
from app.services import timeline_context as tcx  # noqa: E402

logger = logging.getLogger(__name__)

ROOM_ID = os.environ.get("DAN_ROOM_ID", "")
DRAFT_ID = os.environ.get("DAN_DRAFT_ID", "")
JOB_ID = os.environ.get("DAN_JOB_ID", "")
MAX_TOOL_CALLS = int(os.environ.get("DAN_MAX_TOOL_CALLS", "120"))
MAX_GENERATIONS = int(os.environ.get("DAN_MAX_GENERATIONS", "6"))

_calls = 0
_generations = 0

app = Server("timeline")


def _room_dir() -> Path:
    return td._room_dir(ROOM_ID)


def _assets() -> dict:
    p = _room_dir() / "assets.json"
    if not p.exists():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    return {str(a.get("id")): a for a in data if isinstance(a, dict)}


def _load():
    return td.load_draft(ROOM_ID, DRAFT_ID)


def _tool(name, description, props, required=None):
    return types.Tool(name=name, description=description,
                      inputSchema={"type": "object", "properties": props, "required": required or []})


_NUM = {"type": "number"}
_STR = {"type": "string"}


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        _tool("timeline_outline", "タイムライン全体の構造（レーン/クリップ/時刻/種類）を読む。作業前に必ず一度読むこと。", {}),
        _tool("list_assets", "部屋のアセット一覧（asset_id/ファイル名/種類/長さ）。配置ツールに渡すasset_idはここで確認する。", {}),
        _tool("timeline_transcript", "動画の発話内容（文字起こし）をタイムライン時刻つきで読む。内容理解はこれを根拠にする。",
              {"t0": _NUM, "t1": _NUM}),
        _tool("render_frame", "指定タイムライン時刻の合成後フレーム（カット/テロップ/ぼかし/画像すべて反映）を画像として見る。編集後の確認に必ず使う。",
              {"t": _NUM}, ["t"]),
        _tool("append_clip", "ベースレーン末尾（またはat秒）に映像/画像クリップを追加。映像は音声も自動リンク。",
              {"asset_id": _STR, "source_start": _NUM, "duration": _NUM, "at": _NUM},
              ["asset_id", "duration"]),
        _tool("insert_clip", "ベースレーンのat秒に挿入。mode=ripple(以降を後ろへずらす)|overwrite(空きが必要)。",
              {"asset_id": _STR, "source_start": _NUM, "duration": _NUM, "at": _NUM, "mode": _STR},
              ["asset_id", "duration", "at"]),
        _tool("remove_clip", "クリップ削除（linked=trueで映像とリンク音声を一緒に）。",
              {"clip_id": _STR, "linked": {"type": "boolean"}}, ["clip_id"]),
        _tool("trim_clip", "クリップの端(left|right)をnew_time秒へ。A/Vリンクは同期して動く。",
              {"clip_id": _STR, "edge": _STR, "new_time": _NUM}, ["clip_id", "edge", "new_time"]),
        _tool("move_clip", "クリップ（とリンク相手）をnew_start秒へ移動。移動先が塞がっていれば失敗する。",
              {"clip_id": _STR, "new_start": _NUM}, ["clip_id", "new_start"]),
        _tool("add_overlay", "PiP映像または画像（ロゴ等）を正規化座標(x,y,width,height 0-1)でオーバーレイ。画像はアスペクト維持で枠内に収まる。",
              {"asset_id": _STR, "timeline_start": _NUM, "timeline_end": _NUM,
               "x": _NUM, "y": _NUM, "width": _NUM, "height": _NUM, "source_start": _NUM},
              ["asset_id", "timeline_start", "timeline_end", "x", "y", "width", "height"]),
        _tool("add_caption", "テロップ追加。styleは省略可（既存テロップと同デザインになる）。",
              {"text": _STR, "timeline_start": _NUM, "timeline_end": _NUM, "style": {"type": "object"}},
              ["text", "timeline_start", "timeline_end"]),
        _tool("insert_freeze", "既存クリップの1フレームを静止画クリップとしてtimeline_startからduration秒間挿入。",
              {"source_clip_id": _STR, "at_source_time": _NUM, "timeline_start": _NUM, "duration": _NUM},
              ["source_clip_id", "timeline_start", "duration"]),
        _tool("set_clip", "テロップの本文やスタイルを変更。",
              {"clip_id": _STR, "text": _STR, "style": {"type": "object"}}, ["clip_id"]),
        _tool("generate_image", "画像を生成して部屋のアセットとして登録し asset_id を返す（CTAアート・ロゴ風カード等）。日本語文字を入れる場合はpromptに正確な文字列を指定。aspect_ratioは 9:16 等。",
              {"prompt": _STR, "aspect_ratio": _STR}, ["prompt"]),
        _tool("validate_draft", "ドラフト全体を検証して問題リストを返す。作業の締めに必ず実行し、空になるまで直すこと。", {}),
    ]


def _ok(payload) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))]


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list:
    global _calls, _generations
    _calls += 1
    if _calls > MAX_TOOL_CALLS:
        return _ok({"ok": False, "error": f"tool call limit ({MAX_TOOL_CALLS}) reached — validate and finish"})
    try:
        return await _dispatch(name, arguments or {})
    except Exception as exc:  # noqa: BLE001 — the model must see the failure, not a dead pipe
        logger.exception("tool %s failed", name)
        return _ok({"ok": False, "error": f"{type(exc).__name__}: {exc}"})


async def _dispatch(name: str, a: dict) -> list:
    global _generations
    draft = _load()
    seq = draft["sequence"]
    assets = _assets()

    if name == "timeline_outline":
        return [types.TextContent(type="text", text=tcx.timeline_outline(seq, assets))]

    if name == "list_assets":
        rows = []
        for aid, a in assets.items():
            meta = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
            dur = meta.get("duration")
            rows.append(f"{aid}: {a.get('filename')} kind={a.get('kind')}"
                        + (f" duration={dur}s" if dur else ""))
        return [types.TextContent(type="text", text="\n".join(rows) or "(no assets)")]

    if name == "timeline_transcript":
        analyses = _load_analyses(assets)
        rows = tcx.timeline_transcript(seq, analyses, a.get("t0"), a.get("t1"))
        if not rows:
            return _ok({"ok": True, "transcript": [], "note": "no speech analysis available"})
        text = "\n".join(f"[{r['t0']:.1f}-{r['t1']:.1f}s] {r['text']}" for r in rows)
        return [types.TextContent(type="text", text=text)]

    if name == "render_frame":
        res = tcx.render_timeline_frame(seq, str(_room_dir()), float(a["t"]),
                                        out_dir=str(_room_dir() / "drafts"))
        if not res.get("ok"):
            return _ok(res)
        data = base64.b64encode(Path(res["path"]).read_bytes()).decode()
        return [
            types.TextContent(type="text", text=f"composited frame at t={float(a['t']):.2f}s"),
            types.ImageContent(type="image", data=data, mimeType="image/png"),
        ]

    if name == "validate_draft":
        problems = tc.validate_sequence(seq, assets, asset_dir=str(_room_dir()))
        baseline = set(draft.get("baseline_problems") or [])
        fresh = [p for p in problems if p not in baseline]
        return _ok({"ok": not fresh, "problems": fresh,
                    **({"note": f"既存タイムライン由来の問題{len(problems) - len(fresh)}件は無視されます"}
                       if len(problems) != len(fresh) else {})})

    if name == "generate_image":
        if _generations >= MAX_GENERATIONS:
            return _ok({"ok": False, "error": f"generation limit ({MAX_GENERATIONS}) reached"})
        _generations += 1
        return _ok(_generate_image(draft, str(a.get("prompt") or ""), str(a.get("aspect_ratio") or "9:16")))

    # ---- mutating commands on the draft ----
    cmd = {
        "append_clip": lambda: tc.append_clip(seq, assets, asset_id=str(a["asset_id"]),
                                              source_start=float(a.get("source_start") or 0),
                                              duration=float(a["duration"]),
                                              at=(float(a["at"]) if a.get("at") is not None else None)),
        "insert_clip": lambda: tc.insert_clip(seq, assets, asset_id=str(a["asset_id"]),
                                              source_start=float(a.get("source_start") or 0),
                                              duration=float(a["duration"]), at=float(a["at"]),
                                              mode=str(a.get("mode") or "ripple")),
        "remove_clip": lambda: tc.remove_clip(seq, clip_id=str(a["clip_id"]),
                                              linked=bool(a.get("linked", True))),
        "trim_clip": lambda: tc.trim_clip(seq, assets, clip_id=str(a["clip_id"]),
                                          edge=str(a["edge"]), new_time=float(a["new_time"])),
        "move_clip": lambda: tc.move_clip(seq, clip_id=str(a["clip_id"]), new_start=float(a["new_start"])),
        "add_overlay": lambda: tc.add_overlay(seq, assets, asset_id=str(a["asset_id"]),
                                              timeline_start=float(a["timeline_start"]),
                                              timeline_end=float(a["timeline_end"]),
                                              x=float(a["x"]), y=float(a["y"]),
                                              width=float(a["width"]), height=float(a["height"]),
                                              source_start=float(a.get("source_start") or 0)),
        "add_caption": lambda: tc.add_caption(seq, text=str(a.get("text") or ""),
                                              timeline_start=float(a["timeline_start"]),
                                              timeline_end=float(a["timeline_end"]),
                                              style=a.get("style") if isinstance(a.get("style"), dict) else None),
        "insert_freeze": lambda: tc.insert_freeze(seq, assets, source_clip_id=str(a["source_clip_id"]),
                                                  at_source_time=(float(a["at_source_time"]) if a.get("at_source_time") is not None else None),
                                                  timeline_start=float(a["timeline_start"]),
                                                  duration=float(a["duration"])),
        "set_clip": lambda: tc.set_clip(seq, clip_id=str(a["clip_id"]),
                                        text=(str(a["text"]) if a.get("text") is not None else None),
                                        style=a.get("style") if isinstance(a.get("style"), dict) else None),
    }.get(name)
    if cmd is None:
        return _ok({"ok": False, "error": f"unknown tool: {name}"})
    result = cmd()
    if result.get("ok"):
        draft.setdefault("log", []).append({"t": time.time(), "tool": name, "args": a})
        td.save_draft(draft)
        if name == "add_caption":
            # rasterize the designed caption PNG NOW so render_frame (and the native
            # preview) can show it — same key derivation the native engine uses
            note = _ensure_caption_png(str(a.get("text") or ""),
                                       a.get("style") if isinstance(a.get("style"), dict) else None)
            if note:
                result["note"] = note
    return _ok(result)


def _ensure_caption_png(text: str, style: dict | None) -> str | None:
    import hashlib
    text = text.strip()
    if not text:
        return None
    design = dict(style or {})
    design.pop("x", None)
    design.pop("y", None)
    key_src = json.dumps({"w": 1080, "h": 1920, "t": text, "d": design, "words": []},
                         ensure_ascii=False, sort_keys=True)
    key = hashlib.sha1(key_src.encode()).hexdigest()[:16]
    cache_dir = _room_dir() / "caption-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    png = cache_dir / f"{key}.png"
    if png.exists() and png.stat().st_size > 0:
        return None
    spec = cache_dir / f"_spec_agent_{key}.json"
    spec.write_text(json.dumps({
        "outW": 1080, "outH": 1920,
        "web_base": os.environ.get("DAN_CAPTION_RENDER_BASE", "http://127.0.0.1:3000"),
        "items": [{"png": str(png), "text": text, "time": 0.0, "design": design, "words": []}],
    }, ensure_ascii=False), encoding="utf-8")
    try:
        script = Path(__file__).resolve().parents[1] / "scripts" / "render_caption_pngs.py"
        subprocess.run([sys.executable, str(script), str(spec)], capture_output=True,
                       timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception:  # noqa: BLE001
        pass
    finally:
        try:
            spec.unlink()
        except OSError:
            pass
    if not (png.exists() and png.stat().st_size > 0):
        return "テロップは追加済みですが、デザインPNGのレンダリングが未完了です（プレビューを開くと自動生成されます）"
    return None


def _load_analyses(assets: dict) -> dict:
    """Per-asset Whisper analysis cached on assets.json metadata.audio_analysis."""
    out: dict = {}
    for aid, a in assets.items():
        meta = a.get("metadata") if isinstance(a.get("metadata"), dict) else {}
        ana = meta.get("audio_analysis")
        if isinstance(ana, dict):
            out[aid] = ana
    return out


def _generate_image(draft: dict, prompt: str, aspect: str) -> dict:
    if not prompt.strip():
        return {"ok": False, "error": "empty prompt"}
    try:
        r = subprocess.run(
            ["higgsfield", "generate", "create", "gpt_image_2",
             "--prompt", prompt, "--aspect_ratio", aspect,
             "--wait", "--wait-timeout", "10m", "--json"],
            capture_output=True, text=True, timeout=660, shell=True,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "image generation timeout (11m)"}
    out = (r.stdout or "") + (r.stderr or "")
    urls = re.findall(r"https?://[^\s\"']+\.(?:png|jpg|jpeg|webp)[^\s\"']*", out)
    if not urls:
        return {"ok": False, "error": f"no result url in generator output: {out[-400:]}"}
    aid = uuid.uuid4().hex[:12]
    dest = _room_dir() / f"gen_{aid}.png"
    try:
        urllib.request.urlretrieve(urls[0], dest)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"download failed: {exc}"}
    with td.ContentsLock(ROOM_ID):
        p = _room_dir() / "assets.json"
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        data.append({
            # ProductionAsset APIスキーマ完全準拠（status=readyや欠落フィールドは
            # 一覧APIを500にし部屋ごと開けなくした実績あり — 全フィールド明示）
            "id": aid, "room_id": ROOM_ID, "kind": "image", "source_type": "generated",
            "original_uri": str(dest.resolve()),
            "local_path": str(dest.resolve()), "filename": dest.name,
            "proxy_path": None, "proxy_url": None,
            "thumbnail_path": None, "thumbnail_url": None,
            "status": "proxy_ready", "metadata": {},
            "created_at": now, "updated_at": now,
            "generated_by": f"agent:{JOB_ID}",
        })
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    td.track_generated_asset(draft, aid)
    return {"ok": True, "asset_id": aid, "path": str(dest), "note": "add_overlay / append_clip でタイムラインに配置できます"}


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    if not ROOM_ID or not DRAFT_ID:
        print("DAN_ROOM_ID / DAN_DRAFT_ID required", file=sys.stderr)
        sys.exit(2)
    asyncio.run(main())
