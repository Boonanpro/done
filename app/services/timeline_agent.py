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
ALLOWED_TOOLS = "mcp__timeline__*,Read,Glob,Grep,WebSearch,WebFetch"

# job_id -> subprocess (for cancel); content_id -> job_id (for serialization)
_running_procs: dict[str, subprocess.Popen] = {}
_content_jobs: dict[str, str] = {}
_registry_lock = threading.Lock()


def content_busy(content_id: str) -> str | None:
    with _registry_lock:
        return _content_jobs.get(str(content_id))


def cancel_job(job_id: str) -> bool:
    with _registry_lock:
        proc = _running_procs.get(job_id)
    if proc and proc.poll() is None:
        try:
            proc.kill()
            return True
        except OSError:
            return False
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
    parts.append(
        "## 今の状況: 動画タイムラインの編集ジョブ\n"
        "あなたは今チャットではなく、ユーザーが開いている動画エディタのタイムラインを直接編集している。\n"
        "ユーザーと会話はできない。最後に、行った編集の要約を日本語で簡潔に書いて終える。\n"
        "\n"
        "不変条件（これ以外は自由。必要だと思う調査・確認を自分の判断でせよ）:\n"
        "- タイムラインへの書き込みは timeline_* ツールのみ。下書き上で作業し、検証合格後に自動で本番反映される。\n"
        "- 指示された範囲以外のクリップは触らない。\n"
        "- 反映される絵は render_frame で自分の目で確認してから終える。仕上げに validate_draft で problems 空を確認。\n"
        "\n"
        "使える能力:\n"
        "- WebSearch / WebFetch: 実在のブランド・ロゴ・事実の調査。本物が必要なら探すこと（想像で似せない）。\n"
        "- import_image: Webや手元の実画像を素材として取り込む。generate_image は実在しないアートの生成用。\n"
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
        result = _run_session(room_id, content_id, job_id, draft, instruction, annotations or [],
                              selected_clips or [], emit, model)
        return result
    finally:
        with _registry_lock:
            _content_jobs.pop(str(content_id), None)
            _running_procs.pop(job_id, None)


def _run_session(room_id, content_id, job_id, draft, instruction, annotations, selected_clips, emit, model) -> dict[str, Any]:
    draft_id = draft["draft_id"]
    room_dir = td._room_dir(room_id)
    job_dir = room_dir / "drafts" / f"job_{job_id[:12]}"
    job_dir.mkdir(parents=True, exist_ok=True)

    # MCP config: ONLY the timeline server
    mcp_cfg = {
        "mcpServers": {
            "timeline": {
                "command": "python",
                "args": [str(PROJECT_ROOT / "app" / "timeline_mcp_server.py")],
                "env": {
                    "DAN_ROOM_ID": room_id,
                    "DAN_DRAFT_ID": draft_id,
                    "DAN_JOB_ID": job_id,
                    "PYTHONIOENCODING": "utf-8",
                },
            }
        }
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
        "--allowedTools", ALLOWED_TOOLS,
        "--disallowedTools", "Bash,Write,Edit,NotebookEdit,Task,ExitPlanMode,AskUserQuestion",
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
    killer = threading.Timer(AGENT_TIMEOUT_S, lambda: proc.poll() is None and proc.kill())
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
                              "text": json.dumps(blk.get("input") or {}, ensure_ascii=False)[:500]})
            elif et == "result":
                if ev.get("result"):
                    summary_chunks.append(str(ev.get("result")))
        proc.wait(timeout=30)
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent stream ended: %s", exc)
    finally:
        killer.cancel()
        if proc.poll() is None:
            proc.kill()
    timed_out = time.time() >= deadline
    canceled = proc.returncode not in (0, None) and not timed_out

    if timed_out:
        emit({"type": "error", "text": f"エージェントがタイムアウトしました（{AGENT_TIMEOUT_S}s）。本番タイムラインは無変更です"})
        _gc(room_id, draft_id)
        return {"ok": False, "committed": False, "conflict": False,
                "problems": ["timeout"], "summary": "", "draft_id": draft_id}

    # did the agent actually change anything?
    latest = td.load_draft(room_id, draft_id)
    if not latest.get("log"):
        emit({"type": "status", "text": "エージェントは編集を行いませんでした（本番は無変更）"})
        _gc(room_id, draft_id)
        return {"ok": False, "committed": False, "conflict": False,
                "problems": ["エージェントが編集コマンドを1つも実行しませんでした"],
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
