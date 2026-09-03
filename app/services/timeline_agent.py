"""Timeline agent runner — claude code with timeline tools, on a draft, committed once.

Flow: create draft → launch claude CLI (isolated job cwd, tools RESTRICTED to the
timeline MCP server + read-only built-ins) → stream events to the job log →
after the session, validate + commit the draft with compare-and-swap. Failure or
conflict leaves the live timeline untouched; generated-but-uncommitted assets are
garbage-collected on failure.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from app.services import timeline_draft as td
from app.services import timeline_commands as tc
from app.services import timeline_context as tcx

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENT_TIMEOUT_S = int(os.environ.get("DAN_TIMELINE_AGENT_TIMEOUT", "1200"))  # 20 min
# 知識・調査系は自由（Web検索/ページ取得/ファイル読み）。書き込みだけが一本線:
# タイムラインへの変更は timeline_* コマンド経由のみ（Bash/Write/Editは不許可のまま）
# job_id -> subprocess (for cancel); content_id -> job_id (for serialization)
_running_procs: dict[str, subprocess.Popen] = {}
_content_jobs: dict[str, str] = {}
_registry_lock = threading.Lock()


def content_busy(content_id: str) -> str | None:
    with _registry_lock:
        return _content_jobs.get(str(content_id))


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the CLI and ALL descendants (MCP server, its bake children). A hung
    grandchild that inherited the stdout pipe keeps the reader loop alive after
    proc.kill(), which left the content_busy registry locked after a cancel —
    the room then rejected every new job until sandbox restart."""
    try:
        import psutil
        try:
            children = psutil.Process(proc.pid).children(recursive=True)
        except psutil.NoSuchProcess:
            children = []
        for c in children:
            try:
                c.kill()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        pass
    try:
        proc.kill()
    except OSError:
        pass


def cancel_job(job_id: str) -> bool:
    with _registry_lock:
        proc = _running_procs.get(job_id)
    if proc and proc.poll() is None:
        _kill_tree(proc)
        return True
    return False


def _find_claude_cmd() -> list[str]:
    """Resolve the claude CLI the same way cli_runner does (npm global on Windows,
    node+cli.js when the .CMD shim must be avoided)."""
    from app.agent.cli_runner import _resolve_claude_cli  # type: ignore[attr-defined]
    claude_cmd, cli_js = _resolve_claude_cli()
    if not claude_cmd:
        raise RuntimeError("claude CLI not found")
    return [claude_cmd, cli_js] if cli_js else [claude_cmd]


def _system_prompt() -> str:
    """チャットのダンと同一人格（コア人格 + USER/SOUL/RULES の記憶）に、
    タイムライン編集ジョブの不変条件だけを足す。手順の指図はしない —
    賢さは自由と良い道具から出る。書き込み経路だけが一本線。"""
    parts: list[str] = []
    try:
        from app.agent.bootstrap_context import get_core_prompt, load_all_bootstrap_files
        parts.append(get_core_prompt())
        bs = load_all_bootstrap_files()
        if bs:
            parts.append(bs)
    except Exception:  # noqa: BLE001
        logger.exception("bootstrap persona load failed — falling back to bare prompt")
    try:
        from app.agent.v2.tools import SkillRegistry
        hidden = {"self-dev"}
        entries = sorted(
            f"- {s.name}: {s.description}"
            for s in SkillRegistry.list_all()
            if s.name not in hidden
        )
        if entries:
            parts.append(
                "## 使えるスキル（作業の手順書）\n"
                "ジャンルに合うスキルが下にある場合、作業を始める前に check_skill ツールで本文を読み、"
                "その手順・様式（テロップ様式・カット密度・構成の型など）に従うこと。"
                "例: 解説動画/ドキュメンタリー調の組み立ては explainer-video、"
                "動画の仕上げ・ぼかしは post-production。\n" + "\n".join(entries)
            )
    except Exception:  # noqa: BLE001
        logger.exception("skill catalog load failed — continuing without it")
    parts.append(
        "## 今の状況: 動画タイムラインの編集ジョブ\n"
        "あなたは今チャットではなく、ユーザーが開いている動画エディタのタイムラインを直接編集している。\n"
        "ユーザーと会話はできない。最後に、行った編集の要約を日本語で簡潔に書いて終える。\n"
        "\n"
        "不変条件（これ以外は自由。必要だと思う調査・確認を自分の判断でせよ）:\n"
        "- タイムラインへの書き込みは timeline_* ツールのみ。下書き上で作業し、検証合格後に自動で本番反映される。\n"
        "- 指示された範囲以外のクリップは触らない。\n"
        "- 反映される絵は render_frame で自分の目で確認してから終える。仕上げに validate_draft で problems 空を確認。\n"
        "- ツールがインフラ起因の不調を返しても、システムのコードを読んでのデバッグ・原因調査はしない"
        "（あなたの仕事は編集。過去にこれで時間切れになり全作業が消えた）。エラー文の指示に従い、"
        "できる範囲で編集を完了して、残った不調は最後の要約に一言書く。\n"
        "\n"
        "使える能力:\n"
        "- WebSearch / WebFetch: 実在のブランド・ロゴ・事実の調査。本物が必要なら探すこと（想像で似せない）。\n"
        "- import_image: Webや手元の実画像を素材として取り込む。generate_image は実在しないアートの生成用。\n"
        "- watch_video: 範囲を指定して映像を動画として視聴（動き・テンポ・話し方・音）。静止画で判断できない時に使う。\n"
        "- Read / Glob / Grep: ~/.dan/workspace/MEMORY.md（あなたの長期記憶の索引）、"
        "D:\\done\\frontend\\src\\app\\artifacts\\（制作した成果物）などを自由に読める。\n"
        "\n"
        "速度（ユーザーが結果を待っている）:\n"
        "- render_frame は1呼び出し約10秒。複数時刻は ts=[...] で一括取得。独立したツール呼び出しは同一メッセージで並列に。\n"
        "- 最初の ToolSearch で timeline_* が出ないことがある（MCP接続中）。その場合は '+timeline' で再検索。"
    )
    return "\n\n".join(parts)


def run_timeline_agent(
    *,
    room_id: str,
    user_id: str,
    content_id: str,
    job_id: str,
    instruction: str,
    annotations: list[dict[str, Any]] | None = None,
    selected_clips: list[dict[str, Any]] | None = None,
    on_event: Callable[[dict[str, Any]], None] | None = None,
    model: str = "opus",
) -> dict[str, Any]:
    """Blocking. Returns {ok, committed, conflict, problems, summary, draft_id}."""
    _cb = on_event or (lambda e: None)

    def emit(e: dict[str, Any]) -> None:
        # a broken consumer (e.g. cp932 console) must never kill the agent stream
        try:
            _cb(e)
        except Exception:  # noqa: BLE001
            pass
    with _registry_lock:
        if _content_jobs.get(str(content_id)):
            return {"ok": False, "committed": False, "conflict": False,
                    "problems": [f"別のエージェントジョブが実行中です: {_content_jobs[str(content_id)]}"],
                    "summary": "", "draft_id": ""}
        _content_jobs[str(content_id)] = job_id
    draft = None
    try:
        draft = td.create_draft(room_id, content_id, job_id)
        # 指示クリップ(style=note)は指示の器: 範囲はannotationsとして渡済みなので
        # draftからは除去する（ネイティブ側の消費保存とのレースでも残らない）
        for tr in draft["sequence"].get("tracks") or []:
            tr["clips"] = [c for c in (tr.get("clips") or []) if c.get("style") != "note"]
        # BASELINE: 既存タイムラインが元から抱える問題（過去の分割バグの残骸等）。
        # コミット判定は「新しく増えた問題」だけで行う — 実部屋で、エージェントが
        # 触ってもいない22分割クリップのソース長不整合が無関係な編集を巻き添えに
        # 反映拒否した事故の根治
        room_dir0 = td._room_dir(room_id)
        assets0 = {str(a.get("id")): a for a in _read_assets_file(room_dir0)}
        draft["baseline_problems"] = tc.validate_sequence(
            draft["sequence"], assets0, asset_dir=str(room_dir0)
        )
        td.save_draft(draft)
        emit({"type": "status", "text": f"draft {draft['draft_id']} を作成（本番は無変更のまま作業します）"})
        result = _run_session(room_id, user_id, content_id, job_id, draft, instruction, annotations or [],
                              selected_clips or [], emit, model)
        return result
    finally:
        with _registry_lock:
            _content_jobs.pop(str(content_id), None)
            _running_procs.pop(job_id, None)


def _run_session(room_id, user_id, content_id, job_id, draft, instruction, annotations, selected_clips, emit, model) -> dict[str, Any]:
    draft_id = draft["draft_id"]
    room_dir = td._room_dir(room_id)
    job_dir = room_dir / "drafts" / f"job_{job_id[:12]}"
    job_dir.mkdir(parents=True, exist_ok=True)

    # Start from Dan's normal MCP configuration (browser, connected services and
    # the rest of the user's enabled tools), then ADD the draft-only timeline
    # server.  Timeline safety is provided by the draft/CAS transaction, not by
    # replacing Dan with a restricted read-only persona.
    from app.agent.cli_runner import _build_mcp_config
    common_cfg = Path(_build_mcp_config(room_id, user_id))
    try:
        mcp_cfg = json.loads(common_cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        mcp_cfg = {"mcpServers": {}}
    mcp_cfg.setdefault("mcpServers", {})["timeline"] = {
        "command": "python",
        "args": [str(PROJECT_ROOT / "app" / "timeline_mcp_server.py")],
        "env": {
            "DAN_ROOM_ID": room_id,
            "DAN_DRAFT_ID": draft_id,
            "DAN_JOB_ID": job_id,
            "DAN_CONTENT_ID": content_id,
            "PYTHONIOENCODING": "utf-8",
        },
    }
    cfg_path = job_dir / "mcp.json"
    cfg_path.write_text(json.dumps(mcp_cfg), encoding="utf-8")

    assets = {str(a.get("id")): a for a in _read_assets_file(room_dir)}
    outline = tcx.timeline_outline(draft["sequence"], assets)
    note_lines = []
    for i, ann in enumerate(annotations, 1):
        note_lines.append(
            f"注釈{i}: 時刻 {ann.get('t0')}〜{ann.get('t1')}s / 画面座標(正規化) "
            f"x={ann.get('x')}, y={ann.get('y')}, w={ann.get('width')}, h={ann.get('height')} / メモ: {ann.get('note') or ''}"
        )
    sel_lines = []
    for c in selected_clips:
        desc = c.get("text") or c.get("asset") or c.get("lane") or ""
        sel_lines.append(
            f"- {c.get('id')} ({c.get('lane')}) {c.get('timeline_start')}〜{c.get('timeline_end')}s: {str(desc)[:60]}"
        )
    prompt = (
        f"## 編集指示\n{instruction}\n\n"
        + (("## ユーザーが選択したクリップ（この指示の対象。ここを中心に解釈すること）\n"
            + "\n".join(sel_lines) + "\n\n") if sel_lines else "")
        + (("## 画面上の注釈（ユーザーが囲った場所）\n" + "\n".join(note_lines) + "\n\n") if note_lines else "")
        + f"## 現在のタイムライン構造\n{outline}\n\n"
        "上記の指示を実行してください。"
    )

    cmd = _find_claude_cmd()
    cmd += [
        "-p",
        "--output-format", "stream-json",
        "--verbose",
        "--model", model,
        "--max-turns", "80",
        "--mcp-config", str(cfg_path),
        "--dangerously-skip-permissions",
        "--disallowedTools", "ExitPlanMode,AskUserQuestion",
        "--append-system-prompt", _system_prompt(),
    ]
    emit({"type": "status", "text": "編集エージェントを起動しました（動画の内容を読んでから編集します）"})
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    proc = subprocess.Popen(
        cmd, cwd=str(job_dir), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
        env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    with _registry_lock:
        _running_procs[job_id] = proc
    try:
        proc.stdin.write(prompt)
        proc.stdin.close()
    except OSError:
        pass

    summary_chunks: list[str] = []
    deadline = time.time() + AGENT_TIMEOUT_S
    killer = threading.Timer(AGENT_TIMEOUT_S, lambda: proc.poll() is None and _kill_tree(proc))
    killer.daemon = True
    killer.start()
    try:
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            et = ev.get("type")
            if et == "assistant":
                for blk in (ev.get("message") or {}).get("content") or []:
                    if blk.get("type") == "text" and blk.get("text"):
                        summary_chunks.append(blk["text"])
                        emit({"type": "text", "text": blk["text"][:2000]})
                    elif blk.get("type") == "tool_use":
                        emit({"type": "tool_use", "name": blk.get("name"),
                              "text": _describe_tool(str(blk.get("name") or ""), blk.get("input") or {})})
            elif et == "result":
                if ev.get("result"):
                    summary_chunks.append(str(ev.get("result")))
        proc.wait(timeout=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent stream ended: %s", exc)
    finally:
        killer.cancel()
        if proc.poll() is None:
            _kill_tree(proc)
    timed_out = time.time() >= deadline
    canceled = proc.returncode not in (0, None) and not timed_out

    if timed_out:
        emit({"type": "error", "text": f"エージェントがタイムアウトしました（{AGENT_TIMEOUT_S}s）。本番タイムラインは無変更です"})
        _gc(room_id, draft_id)
        return {"ok": False, "committed": False, "conflict": False,
                "problems": ["timeout"], "summary": "", "draft_id": draft_id}

    # A timeline edit is optional.  The unified Dan can also export, inspect, or
    # perform an external action, and those successful requests must not be
    # reported as failures merely because the draft itself stayed unchanged.
    latest = td.load_draft(room_id, draft_id)
    if not latest.get("log"):
        emit({"type": "status", "text": "タイムラインは変更されませんでした。依頼の実行結果を確認しています。"})
        return {"ok": True, "committed": False, "conflict": False,
                "problems": [],
                "summary": "\n".join(summary_chunks[-3:]), "draft_id": draft_id}

    assets_now = {str(a.get("id")): a for a in _read_assets_file(room_dir)}
    baseline = set(latest.get("baseline_problems") or [])

    def _new_problems_only(seq, rid):
        return [p for p in tc.validate_sequence(seq, assets_now, asset_dir=str(room_dir))
                if p not in baseline]

    res = td.commit_draft(room_id, draft_id, _new_problems_only)
    if res["ok"]:
        emit({"type": "status", "text": "検証に合格。タイムラインへ反映しました（1回のUndoで戻せます）"})
    elif res.get("conflict"):
        emit({"type": "error", "text": res["problems"][0]})
        _gc(room_id, draft_id)
    else:
        emit({"type": "error", "text": "検証に失敗したため反映しませんでした: " + "; ".join(res["problems"][:5])})
        _gc(room_id, draft_id)
    return {"ok": res["ok"], "committed": res["ok"], "conflict": bool(res.get("conflict")),
            "problems": res["problems"], "summary": "\n".join(summary_chunks[-3:]), "draft_id": draft_id}


def _describe_tool(name: str, a: dict[str, Any]) -> str:
    """Progress-log line for a tool call, in the user's language — the raw JSON
    args were unreadable and hid whether the agent was doing sensible work."""
    n = name.removeprefix("mcp__timeline__")

    def _t(v: Any) -> str:
        try:
            return f"{float(v):.1f}"
        except (TypeError, ValueError):
            return "?"

    def _span() -> str:
        return f"{_t(a.get('timeline_start'))}〜{_t(a.get('timeline_end'))}秒"

    try:
        if n == "timeline_outline":
            return "📋 タイムライン構造を確認"
        if n == "timeline_transcript":
            if a.get("t0") is not None or a.get("t1") is not None:
                return f"🗣 発話内容を読む（{_t(a.get('t0'))}〜{_t(a.get('t1'))}秒）"
            return "🗣 発話内容を読む（全体）"
        if n == "render_frame":
            ts = a.get("ts") or ([a.get("t")] if a.get("t") is not None else [])
            return "🖼 フレーム確認 t=" + ", ".join(_t(v) for v in ts) + "秒"
        if n == "list_assets":
            return "🗂 素材一覧を確認"
        if n == "generate_image":
            return f"🎨 画像を生成:「{str(a.get('prompt') or '')[:60]}…」"
        if n == "import_image":
            src = str(a.get("url") or "")
            src = src if len(src) <= 80 else src[:77] + "..."
            return f"📥 実画像を取り込み: {a.get('name') or src}"
        if n == "append_clip":
            return f"➕ クリップ追加 素材={a.get('asset_id')} {_t(a.get('duration'))}秒"
        if n == "insert_clip":
            return f"➕ クリップ挿入 素材={a.get('asset_id')} at {_t(a.get('at'))}秒"
        if n == "remove_clip":
            return f"🗑 クリップ削除 {a.get('clip_id')}"
        if n == "trim_clip":
            return f"✂ トリム {a.get('clip_id')}"
        if n == "move_clip":
            return f"↔ クリップ移動 {a.get('clip_id')}"
        if n == "add_overlay":
            return f"🖼 オーバーレイ配置 素材={a.get('asset_id')} {_span()}"
        if n == "add_caption":
            return f"📝 テロップ追加 {_span()}「{str(a.get('text') or '')[:40]}」"
        if n == "insert_freeze":
            return f"⏸ フリーズ挿入 {_t(a.get('timeline_start'))}秒から{_t(a.get('duration'))}秒"
        if n == "set_clip":
            body = f"「{str(a.get('text'))[:40]}」" if a.get("text") else "スタイル変更"
            return f"✏ クリップ変更 {a.get('clip_id')} {body}"
        if n == "validate_draft":
            return "✅ 検証を実行"
        if n == "watch_video":
            return f"🎬 映像を視聴 {_t(a.get('t0'))}〜{_t(a.get('t1'))}秒（動き・音声込み）"
        if n == "ToolSearch":
            return "🔧 ツールを読み込み"
        if n == "WebSearch":
            return f"🌐 Web検索:「{str(a.get('query') or '')[:60]}」"
        if n == "WebFetch":
            return f"🌐 ページを読む: {str(a.get('url') or '')[:80]}"
        if n == "Read":
            return f"📖 ファイルを読む: {str(a.get('file_path') or '')[-60:]}"
        if n in ("Glob", "Grep"):
            return f"🔎 検索: {str(a.get('pattern') or '')[:60]}"
    except Exception:  # noqa: BLE001
        pass
    return f"{n} {json.dumps(a, ensure_ascii=False)[:200]}"


def _read_assets_file(room_dir: Path) -> list[dict[str, Any]]:
    p = room_dir / "assets.json"
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _gc(room_id: str, draft_id: str) -> None:
    td.discard_draft(room_id, draft_id, _delete_generated_assets)


def _delete_generated_assets(room_id: str, asset_ids: list[str]) -> None:
    room_dir = td._room_dir(room_id)
    with td.ContentsLock(room_id):
        p = room_dir / "assets.json"
        data = _read_assets_file(room_dir)
        keep = []
        for a in data:
            if str(a.get("id")) in asset_ids and a.get("source_type") == "generated":
                lp = a.get("local_path")
                if lp:
                    try:
                        Path(lp).unlink(missing_ok=True)
                    except OSError:
                        pass
                continue
            keep.append(a)
        p.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
