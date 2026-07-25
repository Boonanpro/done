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
import shutil
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
CONTENT_ID = os.environ.get("DAN_CONTENT_ID", "")
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


def _frame_b64(path: Path) -> str:
    """Base64 PNG for the model's eyes, downscaled to half resolution — text stays
    readable at 540x960 while image tokens (and per-turn latency) drop ~4x."""
    try:
        from io import BytesIO

        from PIL import Image

        im = Image.open(path)
        if im.width > 600:
            im = im.resize((im.width // 2, im.height // 2), Image.LANCZOS)
            buf = BytesIO()
            im.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        pass
    return base64.b64encode(path.read_bytes()).decode()


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
        _tool("render_frame", "指定タイムライン時刻の合成後フレーム（カット/テロップ/ぼかし/画像すべて反映）を画像として見る。編集後の確認に必ず使う。"
              "1回の呼び出しに約10秒かかるため、複数時刻を見るときは必ず ts で一括指定すること（1回分強の時間でまとめて返る）。",
              {"t": _NUM, "ts": {"type": "array", "items": _NUM, "maxItems": 8,
                                 "description": "複数時刻を一括レンダ（推奨）。tより優先"}}),
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
        _tool("generate_video", "Generate a short Higgsfield video and register it as an editable video asset. Use the returned asset_id with append_clip, insert_clip, or add_overlay.",
              {"prompt": _STR, "aspect_ratio": _STR, "duration": _NUM, "model": _STR,
               "reference_path": _STR, "resolution": _STR}, ["prompt"]),
        _tool("import_image", "実在の画像を部屋の素材として取り込み asset_id を返す。url にはWeb上の画像URL"
              "（WebSearch/WebFetchで見つけた本物のロゴ等）またはローカルファイルパスを指定。生成ではなく本物が必要な時はこちらを使う。",
              {"url": _STR, "name": _STR}, ["url"]),
        _tool("import_media", "Danが検索・生成・Bash処理などで得たローカル動画または音声を、この部屋の素材として取り込む。返るasset_idをappend_clipまたはadd_audioへ渡す。",
              {"path": _STR, "name": _STR}, ["path"]),
        _tool("add_audio", "登録済みの任意音声を音声レーンへ置く。BGM、効果音、ナレーションは同じ操作で扱う。",
              {"asset_id": _STR, "source_start": _NUM, "duration": _NUM, "at": _NUM,
               "volume": _NUM, "role": _STR}, ["asset_id", "duration"]),
        _tool("export_timeline", "現在のドラフトを最終動画として書き出し、通常Danが投稿・共有などに使える成果物アセットを返す。タイムラインを変更しない。", {}),
        _tool("validate_draft", "ドラフト全体を検証して問題リストを返す。作業の締めに必ず実行し、空になるまで直すこと。", {}),
        _tool("watch_video", "指定範囲の映像を『動画として』視聴する（動き・テンポ・話し方・音声込み。静止画のrender_frameでは分からないもの用）。"
              "questionに知りたいことを書くと視聴結果を答える。1回1〜2分かかるので範囲は要点に絞る（最大120秒）。",
              {"t0": _NUM, "t1": _NUM, "question": _STR}, ["t0", "t1"]),
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
        ts = [float(v) for v in a.get("ts") or [] if isinstance(v, (int, float))][:8]
        if not ts and a.get("t") is not None:
            ts = [float(a["t"])]
        if not ts:
            return _ok({"ok": False, "error": "t or ts required"})
        res = tcx.render_timeline_frames(seq, str(_room_dir()), ts,
                                         out_dir=str(_room_dir() / "drafts"))
        if not res.get("ok"):
            return _ok(res)
        out: list = []
        for t, p in zip(ts, res["paths"]):
            out.append(types.TextContent(type="text", text=f"composited frame at t={t:.2f}s"))
            out.append(types.ImageContent(type="image", data=_frame_b64(Path(p)), mimeType="image/png"))
        return out

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

    if name == "generate_video":
        if _generations >= MAX_GENERATIONS:
            return _ok({"ok": False, "error": f"generation limit ({MAX_GENERATIONS}) reached"})
        _generations += 1
        return _ok(_generate_video(
            draft,
            prompt=str(a.get("prompt") or ""),
            aspect=str(a.get("aspect_ratio") or "9:16"),
            duration=float(a.get("duration") or 5),
            model=str(a.get("model") or "seedance_2_0"),
            reference_path=str(a.get("reference_path") or ""),
            resolution=str(a.get("resolution") or "720p"),
        ))

    if name == "import_image":
        return _ok(_import_image(draft, str(a.get("url") or ""), str(a.get("name") or "")))

    if name == "import_media":
        return _ok(_import_media(draft, str(a.get("path") or ""), str(a.get("name") or "")))

    if name == "export_timeline":
        return _ok(_export_timeline(draft))

    if name == "watch_video":
        return _ok(_watch_video(seq, assets, float(a["t0"]), float(a["t1"]),
                                str(a.get("question") or "")))

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
        "add_audio": lambda: tc.add_audio(seq, assets, asset_id=str(a["asset_id"]),
                                            source_start=float(a.get("source_start") or 0),
                                            duration=float(a["duration"]), at=float(a.get("at") or 0),
                                            volume=float(a.get("volume") or 0.22),
                                            role=str(a.get("role") or "music")),
    }.get(name)
    if cmd is None:
        return _ok({"ok": False, "error": f"unknown tool: {name}"})
    result = cmd()
    if result.get("ok"):
        draft.setdefault("log", []).append({"t": time.time(), "tool": name, "args": a})
        td.save_draft(draft)
        if name in ("add_caption", "set_clip"):
            # rasterize the designed caption PNG NOW so export (and the transparency
            # check) always has the CURRENT text+style. set_clip args are partial —
            # bake from the clip's post-command state, not the args (a style-only
            # set_clip left the final-style PNG unbaked → invisible caption shipped)
            bk_text, bk_style = str(a.get("text") or ""), a.get("style")
            if name == "set_clip":
                for tr in seq.get("tracks") or []:
                    for cl in tr.get("clips") or []:
                        if str(cl.get("id")) == str(a.get("clip_id")):
                            bk_text = str(cl.get("text") or "")
                            bk_style = cl.get("style")
            note = _ensure_caption_png(bk_text,
                                       bk_style if isinstance(bk_style, dict) else None)
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
    bake_err = ""
    dbg_log = cache_dir / f"_bake_dbg_{key}.log"
    dbg_log.unlink(missing_ok=True)
    try:
        script = Path(__file__).resolve().parents[1] / "scripts" / "render_caption_pngs.py"
        r = subprocess.run([sys.executable, str(script), str(spec)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL,
                           env={**os.environ, "RENDER_CAPTION_DEBUG_LOG": str(dbg_log)},
                           timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if not (png.exists() and png.stat().st_size > 0):
            bake_err = f"rc={r.returncode} stdout={(r.stdout or '')[-400:]} stderr={(r.stderr or '')[-800:]}"
    except Exception as exc:  # noqa: BLE001
        bake_err = f"spawn failed: {type(exc).__name__}: {exc}"
    finally:
        try:
            spec.unlink()
        except OSError:
            pass
    if bake_err:
        try:
            bake_err += "\nstages:\n" + (dbg_log.read_text(encoding="utf-8")
                                         if dbg_log.exists() else "(no stage log)")
        except OSError:
            pass
    dbg_log.unlink(missing_ok=True)
    if not (png.exists() and png.stat().st_size > 0):
        # 4連続失敗→原因不明タイムアウトの実ジョブ事故があった。失敗理由は
        # 揉み消さずログに残し、エージェントには「リトライで直らない」ことを伝える
        try:
            (cache_dir / "bake_error.log").write_text(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} key={key} text={text[:40]}\n{bake_err}\n",
                encoding="utf-8")
        except OSError:
            pass
        return ("テロップは追加済みだがデザインPNGの生成に失敗（この環境の不調で、リトライや"
                "スタイル変更では直らない。原因調査も不要——クリップはこのまま残してよく、"
                "プレビューを開いた時に自動生成される。他の作業を続けて完了させること）")
    try:
        # numpyは使わない: このMCPプロセスでは import numpy がDLL初期化で
        # 無期限ハングする（py-spy実証: create_module内で7分停止→ジョブ全損）。
        # PILのヒストグラムで同じ「不透明ピクセル数」を数える
        from PIL import Image
        hist = Image.open(png).convert("RGBA").getchannel("A").histogram()
        if sum(hist[11:]) < 50:
            png.unlink(missing_ok=True)
            return ("警告: このスタイルではテロップが透明にレンダリングされました。"
                    "styleを省略（既定デザイン）にするか、fontSizeは相対値(0.5〜2.0)で指定してください")
    except Exception:  # noqa: BLE001
        pass
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
    _register_image_asset(draft, aid, dest, "generated")
    return {"ok": True, "asset_id": aid, "path": str(dest), "note": "add_overlay / append_clip でタイムラインに配置できます"}


def _find_generated_video_url(payload: object) -> str | None:
    """Find a downloadable video URL without depending on one CLI response shape."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key.lower() in {"url", "video_url", "download_url"} and isinstance(value, str):
                if value.startswith(("https://", "http://")):
                    return value
            found = _find_generated_video_url(value)
            if found:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _find_generated_video_url(value)
            if found:
                return found
    return None


def _generate_video(draft: dict, prompt: str, aspect: str, duration: float,
                    model: str, reference_path: str, resolution: str) -> dict:
    """Generate an editable video asset through Higgsfield.

    It intentionally returns only an asset. Placement, trimming, cropping, and
    approval remain normal timeline operations instead of provider side-effects.
    """
    if not prompt.strip():
        return {"ok": False, "error": "empty prompt"}
    supported_models = {"seedance_2_0", "kling3_0"}
    if model not in supported_models:
        return {"ok": False, "error": f"unsupported Higgsfield video model: {model}"}
    if aspect not in {"16:9", "9:16", "4:3", "3:4", "1:1", "21:9", "auto"}:
        return {"ok": False, "error": f"unsupported aspect ratio: {aspect}"}
    if resolution not in {"480p", "720p", "1080p", "4k"}:
        return {"ok": False, "error": f"unsupported resolution: {resolution}"}

    clip_duration = max(1, min(15, int(round(duration))))
    cmd = ["higgsfield", "generate", "create", model, "--prompt", prompt,
           "--aspect_ratio", aspect, "--duration", str(clip_duration),
           "--wait", "--wait-timeout", "20m", "--json"]
    if model == "seedance_2_0":
        cmd += ["--resolution", resolution]
    elif aspect not in {"16:9", "9:16", "1:1"}:
        return {"ok": False, "error": "kling3_0 supports only 16:9, 9:16, or 1:1"}
    if reference_path:
        ref = Path(reference_path).expanduser()
        if not ref.is_file():
            return {"ok": False, "error": f"reference file not found: {reference_path}"}
        is_video = ref.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
        if model == "kling3_0":
            if is_video:
                return {"ok": False, "error": "kling3_0 reference video is not supported here; use seedance_2_0"}
            cmd += ["--start-image", str(ref)]
        else:
            cmd += ["--video" if is_video else "--image", str(ref)]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1260,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Higgsfield video generation timed out (21m)"}
    if result.returncode != 0:
        detail = ((result.stderr or result.stdout or "generation failed").strip())[-500:]
        return {"ok": False, "error": f"Higgsfield generation failed: {detail}"}
    try:
        url = _find_generated_video_url(json.loads(result.stdout))
    except json.JSONDecodeError:
        url = None
    if not url:
        candidates = re.findall(r"https?://[^\s\"']+", (result.stdout or "") + "\n" + (result.stderr or ""))
        url = next((candidate for candidate in candidates if ".mp4" in candidate.lower()), None)
    if not url:
        return {"ok": False, "error": "Higgsfield returned no downloadable video URL"}

    aid = uuid.uuid4().hex[:12]
    dest = _room_dir() / f"higgs_{aid}.mp4"
    try:
        urllib.request.urlretrieve(url, dest)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"generated video download failed: {exc}"}
    if not dest.exists() or dest.stat().st_size == 0:
        return {"ok": False, "error": "generated video download was empty"}
    meta: dict = {"generator": "higgsfield", "model": model, "prompt": prompt,
                  "requested_duration": clip_duration, "source_url": url}
    try:
        probe = subprocess.run(
            [_ffprobe(), "-v", "error", "-show_entries", "format=duration", "-of", "json", str(dest)],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        meta["duration"] = float((json.loads(probe.stdout).get("format") or {}).get("duration") or 0)
    except Exception:
        pass
    _register_media_asset(draft, aid, dest, "video", filename_hint=f"Higgsfield {model} clip", metadata=meta)
    return {"ok": True, "asset_id": aid, "kind": "video", "path": str(dest), "metadata": meta,
            "note": "Generated clip is ready. Place it with append_clip, insert_clip, or add_overlay."}


def _import_image(draft: dict, url: str, name: str) -> dict:
    """Bring a REAL image into the room (web URL or local path) — the general
    entry gate for authentic material (logos, product shots) as opposed to
    generated imitations. Converted to PNG (alpha preserved) and registered
    exactly like generated assets so failure-GC covers it too."""
    if not url.strip():
        return {"ok": False, "error": "url required"}
    aid = uuid.uuid4().hex[:12]
    raw = _room_dir() / f"imp_{aid}.bin"
    try:
        if re.match(r"^https?://", url):
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=60) as resp, open(raw, "wb") as f:
                f.write(resp.read(50 * 1024 * 1024))
        else:
            src = Path(url)
            if not src.exists():
                return {"ok": False, "error": f"file not found: {url}"}
            raw.write_bytes(src.read_bytes())
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"fetch failed: {exc}"}
    dest = _room_dir() / f"imp_{aid}.png"
    try:
        from PIL import Image
        im = Image.open(raw)
        im.load()
        if im.mode not in ("RGBA", "RGB"):
            im = im.convert("RGBA")
        im.save(dest, format="PNG")
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"not a usable image (png/jpg/webp等のみ。svgは不可): {exc}"}
    finally:
        try:
            raw.unlink()
        except OSError:
            pass
    _register_image_asset(draft, aid, dest, "local_path", filename_hint=name)
    return {"ok": True, "asset_id": aid, "path": str(dest),
            "size": f"{im.width}x{im.height}",
            "note": "add_overlay / append_clip でタイムラインに配置できます"}


def _import_media(draft: dict, path: str, name: str) -> dict:
    """Promote a media file produced or obtained by the general Dan toolset into
    a room asset.  This is intentionally media-generic rather than a BGM feature."""
    src = Path(path).expanduser()
    if not src.is_file():
        return {"ok": False, "error": f"media file not found: {path}"}
    suffix = src.suffix.lower()
    audio_exts = {".mp3", ".m4a", ".aac", ".wav", ".flac", ".ogg", ".opus"}
    video_exts = {".mp4", ".mov", ".mkv", ".webm", ".m4v"}
    kind = "audio" if suffix in audio_exts else "video" if suffix in video_exts else ""
    if not kind:
        return {"ok": False, "error": f"unsupported media extension: {suffix or '(none)'}"}
    aid = uuid.uuid4().hex[:12]
    dest = _room_dir() / f"agent_{aid}{suffix}"
    try:
        shutil.copy2(src, dest)
    except OSError as exc:
        return {"ok": False, "error": f"copy failed: {exc}"}
    meta: dict = {}
    try:
        probe = subprocess.run(
            [_ffprobe(), "-v", "error", "-show_entries",
             "format=duration", "-of", "json", str(dest)],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        meta["duration"] = float((json.loads(probe.stdout).get("format") or {}).get("duration") or 0)
    except Exception:
        pass
    _register_media_asset(draft, aid, dest, kind, filename_hint=name, metadata=meta)
    return {"ok": True, "asset_id": aid, "kind": kind, "path": str(dest), "metadata": meta,
            "note": "use add_audio for audio, or append_clip/insert_clip for video"}


def _ffmpeg() -> str:
    import shutil as _sh
    for c in (_sh.which("ffmpeg"), r"C:\Users\Owner\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if c and Path(c).exists():
            return c
    raise RuntimeError("ffmpeg not found")


def _ffprobe() -> str:
    """Find ffprobe next to the selected ffmpeg binary when possible."""
    ffmpeg = _ffmpeg()
    candidates = (
        str(Path(ffmpeg).with_name("ffprobe.exe")),
        shutil.which("ffprobe"),
        r"C:\Users\Owner\ffmpeg\bin\ffprobe.exe",
        r"C:\ffmpeg\bin\ffprobe.exe",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    raise RuntimeError("ffprobe not found")


def _export_timeline(draft: dict) -> dict:
    """Render the isolated draft and publish its output as a room artifact."""
    if not CONTENT_ID:
        return {"ok": False, "error": "timeline export has no content context"}
    from app.api.production_asset_routes import _render_sequence_job

    export_id = f"{JOB_ID}_export"
    export_dir = _room_dir() / "jobs" / export_id
    export_dir.mkdir(parents=True, exist_ok=True)
    instruction = {"timeline": {"sequence": json.loads(json.dumps(draft["sequence"]))}}
    result = _render_sequence_job(ROOM_ID, export_id, CONTENT_ID, instruction, export_dir)
    if not result:
        return {"ok": False, "error": "timeline has no renderable base video clips"}
    return {"ok": True, **result, "note": "export is a reusable room asset"}


def _watch_video(seq: dict, assets: dict, t0: float, t1: float, question: str) -> dict:
    """Gemini's eyes on the timeline: cut the base-lane footage for [t0,t1] into a
    small 640p mp4 (original audio included) and have Gemini watch it. This is the
    agent's only way to perceive MOTION and SOUND — render_frame only shows stills."""
    if t1 <= t0:
        return {"ok": False, "error": "t1 must be > t0"}
    if t1 - t0 > 120:
        return {"ok": False, "error": "範囲が長すぎます（最大120秒）。要点に絞って複数回に分けてください"}
    base = next((tr for tr in seq.get("tracks") or [] if tr.get("type") == "video"), None)
    if not base:
        return {"ok": False, "error": "no video track"}
    parts: list[Path] = []
    tmp_dir = _room_dir() / "drafts"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        for c in sorted(base.get("clips") or [], key=lambda x: float(x.get("timeline_start") or 0)):
            ts, te = float(c.get("timeline_start") or 0), float(c.get("timeline_end") or 0)
            if te <= t0 or ts >= t1 or c.get("freeze"):
                continue
            asset = assets.get(str(c.get("asset_id") or "")) or {}
            src = asset.get("local_path") or asset.get("original_uri") or ""
            if not src or not Path(src).exists():
                continue
            ss = float(c.get("source_start") or 0) + (max(t0, ts) - ts)
            dur = min(t1, te) - max(t0, ts)
            if dur <= 0.05:
                continue
            part = tmp_dir / f"watch_{uuid.uuid4().hex[:8]}.mp4"
            r = subprocess.run(
                [_ffmpeg(), "-nostdin", "-y", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", src,
                 "-vf", "scale=-2:640", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28",
                 "-c:a", "aac", "-b:a", "96k", str(part)],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=180,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if r.returncode == 0 and part.exists() and part.stat().st_size > 0:
                parts.append(part)
        if not parts:
            return {"ok": False, "error": "この範囲に切り出せる映像クリップがありません"}
        if len(parts) == 1:
            clip_path = parts[0]
        else:
            lst = tmp_dir / f"watch_{uuid.uuid4().hex[:8]}.txt"
            lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
            clip_path = tmp_dir / f"watch_{uuid.uuid4().hex[:8]}.mp4"
            r = subprocess.run(
                [_ffmpeg(), "-nostdin", "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(clip_path)],
                capture_output=True, stdin=subprocess.DEVNULL, timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            lst.unlink(missing_ok=True)
            if r.returncode != 0:
                return {"ok": False, "error": "segment concat failed"}
            parts.append(clip_path)
        from app.services.video_analyzer import _analyze_file_sync
        prompt = (
            f"これは動画タイムラインの {t0:.1f}秒〜{t1:.1f}秒 の切り出しです。"
            f"時刻に言及する時はこの切り出し内の相対秒で述べてください。\n\n"
            + (question or "この映像の内容（動き・話し方・音声・テンポ）を簡潔に説明してください。")
        )
        text = _analyze_file_sync(str(clip_path), prompt)
        if not text:
            return {"ok": False, "error": "Gemini returned empty response"}
        return {"ok": True, "t0": t0, "t1": t1, "answer": text,
                "note": "answer内の時刻は範囲先頭からの相対秒"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "video cut timeout"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"watch failed: {exc}"}
    finally:
        for p in parts:
            try:
                p.unlink()
            except OSError:
                pass


def _register_image_asset(draft: dict, aid: str, dest: Path, source_type: str,
                          filename_hint: str = "") -> None:
    with td.ContentsLock(ROOM_ID):
        p = _room_dir() / "assets.json"
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        data.append({
            # ProductionAsset APIスキーマ完全準拠（status=readyや欠落フィールドは
            # 一覧APIを500にし部屋ごと開けなくした実績あり — 全フィールド明示）
            "id": aid, "room_id": ROOM_ID, "kind": "image", "source_type": source_type,
            "original_uri": str(dest.resolve()),
            "local_path": str(dest.resolve()), "filename": filename_hint or dest.name,
            "proxy_path": None, "proxy_url": None,
            "thumbnail_path": None, "thumbnail_url": None,
            "status": "proxy_ready", "metadata": {},
            "created_at": now, "updated_at": now,
            "generated_by": f"agent:{JOB_ID}",
        })
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    td.track_generated_asset(draft, aid)


def _register_media_asset(draft: dict, aid: str, dest: Path, kind: str,
                          filename_hint: str = "", metadata: dict | None = None) -> None:
    with td.ContentsLock(ROOM_ID):
        p = _room_dir() / "assets.json"
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else []
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        data.append({
            "id": aid, "room_id": ROOM_ID, "kind": kind, "source_type": "agent_workspace",
            "original_uri": str(dest.resolve()), "local_path": str(dest.resolve()),
            "filename": filename_hint or dest.name, "proxy_path": None, "proxy_url": None,
            "thumbnail_path": None, "thumbnail_url": None, "status": "ready",
            "metadata": metadata or {}, "created_at": now, "updated_at": now,
            "generated_by": f"agent:{JOB_ID}",
        })
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    td.track_generated_asset(draft, aid)


async def main():
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    if not ROOM_ID or not DRAFT_ID:
        print("DAN_ROOM_ID / DAN_DRAFT_ID required", file=sys.stderr)
        sys.exit(2)
    asyncio.run(main())
