"""Timeline agent runner — claude code with timeline tools, on a draft, committed once.

Flow: create draft → launch the production CLI with ordinary Dan capabilities
and timeline tools → stream events to the job log →
after the session, validate + commit the draft with compare-and-swap. Failure or
conflict leaves the live timeline untouched. Checkpoints and generated assets
remain available for continuation without repeating completed work.
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
AGENT_TIMEOUT_S = int(os.environ.get("DAN_TIMELINE_AGENT_TIMEOUT", "1800"))
# サービスの準備・調査には通常のDanの道具を使う。
# タイムラインの変更は下書きを検証し、競合確認後に反映する。
# job_id -> subprocess (for cancel); content_id -> job_id (for serialization)
_running_procs: dict[str, subprocess.Popen] = {}
_runtime_jobs: dict[str, tuple[str,str]] = {}
_content_jobs: dict[str, str] = {}
_registry_lock = threading.Lock()


def content_busy(content_id: str) -> str | None:
    with _registry_lock:
        local=_content_jobs.get(str(content_id))
    if local:return local
    from app.services.production_worker import alive
    for path in td.UPLOAD_ROOT.glob('*/jobs.json'):
        try:
            for job in json.loads(path.read_text(encoding='utf-8')):
                if str(job.get('content_id'))==str(content_id) and job.get('status') in ('queued','running') and (job.get('status')=='queued' or alive(job)):
                    return job['id']
        except (OSError,ValueError):pass
    return None


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
    from app.services import editor_runtime
    with _registry_lock:
        runtime=_runtime_jobs.get(job_id)
    if runtime:
        editor_runtime.cancel(*runtime)
        return True
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
    model: str | None = None,
    expected_hash: str | None = None,
    resume_draft_id: str | None = None,
    preparation_only: bool = False,
    presentation_only: bool = False,
) -> dict[str, Any]:
    """Blocking. Returns {ok, committed, conflict, problems, summary, draft_id}."""
    from app.agent.cli_runner import resolve_room_backend, _ALLOWED_CLI_MODELS
    model = model or 'gpt-6-astra'
    if model not in _ALLOWED_CLI_MODELS:
        raise ValueError(f'未対応の編集モデルです: {model}')
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
        if resume_draft_id:
            draft=td.load_draft(room_id,resume_draft_id)
            if draft.get('content_id')!=content_id or draft.get('committed_at'):
                raise ValueError('再開できる未反映の下書きではありません')
            draft['job_id']=job_id
        else:
            draft = td.create_draft(room_id, content_id, job_id)
        draft['editor_guarded'] = expected_hash is not None
        draft['live_updates'] = not (preparation_only or presentation_only)
        draft['presentation_only'] = presentation_only
        if expected_hash and draft['base_hash'] != expected_hash:
            return {'ok': False, 'committed': False, 'conflict': True,
                    'problems': ['依頼後に動画が変更されたため、上書きせず停止しました'], 'summary': ''}
        if selected_clips and not resume_draft_id:
            from app.services.timeline_scope import attach
            attach(draft, selected_clips)
        if preparation_only:
            draft['edit_scope']={'clip_ids':[], 'spans':[]}
            instruction+='\n今回は検索・外部サービス操作・接続等の準備です。必要な道具を使って進め、タイムラインは変更しません。本人の操作が必要になった場合は具体的な操作を報告してください。'
        if presentation_only:
            draft['edit_scope']={'clip_ids':[], 'spans':[]}
            instruction+='\n成果はビジュアル履歴へ提示する別の見本です。必要な制作・検品・表示まで実行してください。元のタイムラインは読み取り専用で、変更・置換しません。'
        # 指示クリップ(style=note)は指示の器: 範囲はannotationsとして渡済みなので
        # draftからは除去する（ネイティブ側の消費保存とのレースでも残らない）
        for tr in draft["sequence"].get("tracks") or []:
            allowed = set((draft.get('edit_scope') or {}).get('clip_ids', []))
            tr["clips"] = [c for c in (tr.get("clips") or [])
                           if preparation_only or presentation_only or c.get("style") != "note" or (selected_clips and c.get('id') not in allowed)]
        # BASELINE: 既存タイムラインが元から抱える問題（過去の分割バグの残骸等）。
        # コミット判定は「新しく増えた問題」だけで行う — 実部屋で、エージェントが
        # 触ってもいない22分割クリップのソース長不整合が無関係な編集を巻き添えに
        # 反映拒否した事故の根治
        room_dir0 = td._room_dir(room_id)
        assets0 = {str(a.get("id")): a for a in _read_assets_file(room_dir0)}
        if not resume_draft_id:
            draft["baseline_problems"] = tc.validate_sequence(
                draft["sequence"], assets0, asset_dir=str(room_dir0)
            )
        td.save_draft(draft)
        from app.services.production_worker import checkpoint
        checkpoint(room_id,job_id,draft["draft_id"])
        emit({"type": "status", "text": "見本を制作して提示します。" if presentation_only else "編集は操作ごとにタイムラインへ反映します。途中でも再生して確認できます。"})
        result = _run_session(room_id, user_id, content_id, job_id, draft, instruction, annotations or [],
                              selected_clips or [], emit, model)
        for attempt in range(2):
            if not result.get('retryable'):break
            draft=td.load_draft(room_id,draft['draft_id'])
            emit({'type':'status','text':'制作セッションを更新し、保存済みの途中成果から続行します。'})
            continuation=instruction+'\n前のセッションから継続が必要です。下書き・追加指示・生成済み素材を確認し、完了済み作業や生成を繰り返さず残りを進めてください。\n'+result.get('summary','')
            result=_run_session(room_id,user_id,content_id,job_id,draft,continuation,annotations or [],selected_clips or [],emit,model)
        return result
    finally:
        with _registry_lock:
            _content_jobs.pop(str(content_id), None)
            _running_procs.pop(job_id, None)
            _runtime_jobs.pop(job_id,None)


def _run_session(room_id, user_id, content_id, job_id, draft, instruction, annotations, selected_clips, emit, model) -> dict[str, Any]:
    draft_id = draft["draft_id"]
    room_dir = td._room_dir(room_id)
    job_dir = room_dir / "drafts" / f"job_{job_id[:12]}"
    job_dir.mkdir(parents=True, exist_ok=True)

    # Start from Dan's normal MCP configuration (browser, connected services and
    # the rest of the user's enabled tools), then ADD the draft-only timeline
    # server.  Timeline safety is provided by the draft/CAS transaction, not by
    # replacing Dan with a restricted read-only persona.
    mcp_cfg = {"mcpServers": {}}
    from app.agent.cli_runner import _build_mcp_config
    common_cfg = Path(_build_mcp_config(room_id, user_id))
    try:
        mcp_cfg = json.loads(common_cfg.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
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
        "\n文字・UI・図形などの凝った映像はproduction_methods('editable-motion')で制作手段を確認できる。"
        "HTML/GSAPの元データをprepare_motion_projectで別版にし、通常のファイル操作で編集し、render_motion_projectで素材化できる。"
        "既存素材に編集元があればそれを読み、依頼部分を変更する。映像の焼き直しだけで編集元を失わない。"
    )
    content = td._find_content(td._read_contents_raw(room_id), content_id) or {}
    if content.get('creative_brief'):
        prompt += '\n\n## この作品で合意した意図とテイスト\n' + json.dumps(content['creative_brief'], ensure_ascii=False)

    from app.services import editor_runtime
    emit({"type":"status","model":model,"text":f"{model}で作業を開始します"})
    with _registry_lock:
        _runtime_jobs[job_id]=(room_id,content_id)
    result=editor_runtime.run(room_id,user_id,content_id,job_id,prompt,cfg_path,emit,model)
    summary_chunks=[str(result.get('text') or result.get('content') or '')]
    if result.get('is_error'):
        return {'ok':False,'committed':False,'conflict':False,
                'problems':[summary_chunks[0] or '制作セッションが終了しました'],
                'summary':summary_chunks[0],'draft_id':draft_id}

    # A timeline edit is optional.  The unified Dan can also export, inspect, or
    # perform an external action, and those successful requests must not be
    # reported as failures merely because the draft itself stayed unchanged.
    latest = td.load_draft(room_id, draft_id)
    outcome=latest.get('outcome') or {'state':'unknown','summary':summary_chunks[-1]}
    from app.services.editor_job_updates import pending
    if pending(room_id,job_id):
        return {'ok':False,'committed':False,'conflict':False,'problems':['未読の追加指示があります'],
                'summary':'追加指示をtimelineツールで受け取って反映してください。','draft_id':draft_id,'retryable':True}
    if latest.get('presentation_only') or not latest.get("log"):
        emit({"type": "status", "text": "タイムラインは変更されませんでした。依頼の実行結果を確認しています。"})
        return {"ok": True, "committed": False, "conflict": False,
                "problems": [],
                "summary": outcome['summary'], "outcome":outcome, "draft_id": draft_id}

    assets_now = {str(a.get("id")): a for a in _read_assets_file(room_dir)}
    baseline = set(latest.get("baseline_problems") or [])

    def _new_problems_only(seq, rid):
        return [p for p in tc.validate_sequence(seq, assets_now, asset_dir=str(room_dir))
                if p not in baseline]

    res = td.commit_draft(room_id, draft_id, _new_problems_only)
    if res["ok"]:
        emit({"type": "status", "text": "タイムラインを保存しました。映像・音声の検品状況は制作結果を確認してください。"})
    elif res.get("conflict"):
        emit({"type": "error", "text": res["problems"][0]})
    else:
        emit({"type": "error", "text": "検証に失敗したため反映しませんでした: " + "; ".join(res["problems"][:5])})
    return {"ok": res["ok"], "committed": res["ok"], "conflict": bool(res.get("conflict")),
            "problems": res["problems"], "summary": outcome['summary'], "outcome":outcome, "draft_id": draft_id}


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
