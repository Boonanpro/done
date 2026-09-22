"""Shared cross-project capabilities for text Dan and the voice command center."""
from __future__ import annotations

import asyncio
import time
from typing import Any
from uuid import uuid4, uuid5, NAMESPACE_URL

from app.services.chat_service import ChatService
from app.services.project_service import ProjectService
import logging

logger = logging.getLogger(__name__)


async def _wake_job(job_id):
    """Retry only the idempotent durable-queue claim, never the job's actions."""
    import httpx
    from app.services.browser_lifecycle import _token_path
    async with httpx.AsyncClient(timeout=5,trust_env=False) as client:
        for delay in (0,.3,1,2):
            if delay:await asyncio.sleep(delay)
            try:
                response=await client.post('http://127.0.0.1:9000/internal/command-jobs/wake',
                    json={'job_id':job_id},headers={'x-dan-browser-token':_token_path().read_text().strip()})
                response.raise_for_status()
                if not response.json().get('accepted'):
                    raise RuntimeError('作業担当が依頼を受け付けられませんでした')
                return
            except (OSError,httpx.HTTPError) as exc:
                logger.warning('command_job_wake_retry job=%s cause=%s',job_id,type(exc).__name__)
    raise RuntimeError('作業担当への接続を確認できませんでした')


CONFIRMATION_RULE = """購入・予約の確定、決済、他人へのメッセージ送信、公開、復元できない削除などの不可逆操作は、実行前に具体的な対象・内容・金額（該当する場合）を本人に示し、その内容を確定してよいという返事を得るまで止まる。相談、候補の選択、条件の指定だけを確定の承認と解釈しない。閲覧、検索、入力、本人の登録先へのログイン認証コード送付・入力など、依頼を進める通常操作には確認を求めない。
委譲時もこの確認を省略しない。実行担当は確定前の内容と確認待ちであることを報告し、窓口が本人の返事を取り次ぐ。提示した具体内容への承認が既に得られていれば重複確認は不要だが、その後の条件変更・待機指示・未回答の確認質問がある間は確定しない。"""

INSTRUCTIONS = """ここはDone。音声とテキストで共用する全体の窓口として、各プロジェクトの確認、相談、雑用を扱う。
継続的なプロジェクトに育った話は、専用の部屋で進めることを提案し、合意したら背景を引き継ぐ。
command_centerで各部屋の履歴を自分で読み、話の内容から部屋を探せる。overviewは最近使った部屋の会話、searchは古い部屋も含む会話検索、readは詳しい履歴とエディタ状態。
各部屋の実作業はdelegateでその部屋のダンへ依頼でき、結果はここに届く。この部屋の雑用や深い作業も自分で実行できる。"""

TOOL = {
    "name": "command_center",
    "description": "各プロジェクトを横断して調べる・操作する。overview=最近30日以内にユーザーが発言した部屋と実行中の部屋の直近4件、list=一覧、search=話の内容で履歴を検索（古い部屋も対象）、status=process monitor, read=履歴とエディタ状態、delegate=その部屋で実作業、report=別室へ報告。読むだけなら他の部屋に投稿も起動もしない。delegateは受付を返し、完了報告は後で届く。",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["overview", "list", "search", "read", "status", "requests", "delegate", "report"]},
            "query": {"type": "string", "description": "一覧の絞り込み、または会話の検索語。"},
            "keywords": {"type": "array", "items": {"type": "string"}, "maxItems": 6, "description": "search用。説明された話の内容から検索語や言い換えを選ぶ。部屋名は不要。一致した会話を読んで対象を判断できる。"},
            "days": {"type": "integer", "minimum": 1, "maximum": 3650, "description": "overviewの対象期間。既定30日。"},
            "offset": {"type": "integer", "minimum": 0, "description": "overview/searchの続き。next_offsetを指定。"},
            "project_id": {"type": "string", "description": "search/list/overviewの対象プロジェクトのid（room_idではない）。read/status/delegate/reportに必要。searchではそのプロジェクト内だけを検索する任意の絞り込み。"},
            "task": {"type": "string", "description": "delegateの作業指示、またはreportの報告本文。"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            "before": {"type": "string", "description": "readの続き。返されたnext_beforeを指定する。"},
        },
        "required": ["action"],
    },
}


def summary(project: dict) -> dict:
    return {k: project.get(k) for k in (
        "id", "title", "room_id", "status", "summary", "updated_at", "has_active_run",
    )}


_hub_rooms: dict[str, tuple[float, set[str]]] = {}


def room_instructions(room_id: str, user_id: str) -> str:
    """Hub-only role; ordinary project prompts retain their existing capabilities."""
    if not room_id or not user_id:
        return ''
    cached = _hub_rooms.get(user_id)
    if not cached or time.monotonic() - cached[0] > 60:
        rows = ProjectService().supabase.table('projects').select('room_id').eq(
            'user_id', user_id).contains('metadata', {'role': 'command_center'}).execute().data or []
        cached = (time.monotonic(), {row['room_id'] for row in rows})
        _hub_rooms[user_id] = cached
    return INSTRUCTIONS if room_id in cached[1] else ''


def report_id(watch_id: str) -> str:
    return str(uuid5(NAMESPACE_URL, 'dan-command-center:' + watch_id))


async def execute(params: dict[str, Any], room_id: str, user_id: str, *, report_message_id: str | None = None) -> dict:
    """Never accept user identity from model arguments; validate both room ends."""
    if not user_id or not room_id:
        raise ValueError("利用者と会話の部屋が必要です")
    chat, projects = ChatService(), ProjectService()
    if not await chat.get_room(room_id, user_id):
        raise ValueError("この部屋へのアクセス権がありません")
    action = params.get("action")
    if action == 'requests':
        from app.services.command_job_state import list_owned, public
        live_jobs = [public(s) for s in await asyncio.to_thread(list_owned,user_id,room_id)]
        from app.services.followups import decode_watch_row
        from app.services.command_handoff import lineage
        rows = await asyncio.to_thread(lambda: chat.supabase.table('pending_followups').select('*')
            .eq('user_id', user_id).order('created_at', desc=True).limit(200).execute())
        jobs = []
        for raw in rows.data or []:
            row = decode_watch_row(raw)
            spec = row['spec']
            if spec.get('engine') == 'steerable_cli':
                continue
            if not spec.get('command_center') or spec.get('origin_room_id') != room_id:
                continue
            if not await chat.get_room(row['room_id'], user_id):
                continue
            runs = await lineage(spec['run_id']) if spec.get('run_id') else []
            recent = max(runs, key=lambda r: r['created_at']) if runs else None
            activity = await projects.get_execution_events(recent['project_id'], run_id=recent['id'], limit=8) if recent else []
            jobs.append({'id': row['id'], 'task': row['plain_note'], 'status': row['status'],
                'room_id': row['room_id'], 'runs': runs, 'activity': activity, 'report': spec.get('report'),
                'outcome': spec.get('outcome'),
                'report_message_id': report_id(row['id'])})
            if len(jobs) >= 10:
                break
        return {'requests': jobs, 'live_jobs': live_jobs}
    if action == 'jobs':
        from app.services.command_job_state import list_owned, public
        return {'jobs':[public(s) for s in await asyncio.to_thread(list_owned,user_id,room_id)]}
    if action == 'control_job':
        from app.services.command_job_state import control, public
        operation = str(params.get('operation') or '')
        voice_approved = False
        if operation == 'confirm' and params.get('voice_approval'):
            from app.services.voice_approval import valid
            voice_approved = valid(params['voice_approval'],user_id,room_id,str(params.get('job_id') or ''),
                params.get('confirmation_id'),str(params.get('task') or ''))
            if not voice_approved:
                raise ValueError('今回の音声での承認を確認できませんでした。確定操作は行っていません。')
        if operation == 'confirm' and not voice_approved:
            import re
            spoken = str(params.get('approval_text') or '').strip()
            if (not re.search(r'はい|うん|それで|お願い|確定して|購入して|買って|送って|進めて|いいよ|OK',spoken,re.I)
                or re.search(r'何|どこ|いくら|待って|やめ|まだ|先に|ない|ません|違う|ダメ|だめ|変更|[?？]',spoken)):
                raise ValueError('提示した内容への本人の明確な返事が必要です。質問や条件指定では確定しません。')
            recent = await chat.get_messages(room_id,user_id,limit=8)
            humans = sorted((m for m in recent if m.get('sender_type') in {'human','user'}),key=lambda m:m.get('created_at') or '',reverse=True)
            if not humans or spoken not in humans[0].get('content',''):
                raise ValueError('本人の最新の返事を確認できません。会話の記録を待って再度確認してください。')
            from datetime import datetime
            from app.services.command_job_state import owned
            proposal = (owned(str(params.get('job_id') or ''),user_id,room_id).get('confirmation') or {})
            if (not proposal.get('created_at') or not humans[0].get('created_at') or
                datetime.fromisoformat(humans[0]['created_at'].replace('Z','+00:00')) <=
                datetime.fromisoformat(proposal['created_at'])):
                raise ValueError('今回の確認内容を提示した後の返事が必要です。以前の返事では確定しません。')
        result = await asyncio.to_thread(control, str(params.get('job_id') or ''),user_id,room_id,
            operation,str(params.get('task') or ''),params.get('confirmation_id'))
        return {'job':public(result)}
    if action == "overview":
        from app.services.command_center_overview import recent_conversations
        return await recent_conversations(user_id, days=min(3650, max(1, int(params.get('days') or 30))),
            limit=min(50, max(1, int(params.get('limit') or 20))), offset=max(0, int(params.get('offset') or 0)))
    if action == "search":
        from app.services.command_center_overview import search_conversations
        terms = params.get('keywords') or str(params.get('query') or '').split()
        if not isinstance(terms, list) or not all(isinstance(t, str) and len(t) <= 120 for t in terms):
            raise ValueError('検索語は120文字以内の文字列で指定してください')
        return await search_conversations(user_id, terms, limit=min(50, max(1, int(params.get('limit') or 10))),
            offset=max(0, int(params.get('offset') or 0)), project_id=params.get('project_id'))
    if action == "list":
        rows = await projects.list_projects(user_id)
        query = str(params.get("query") or "").strip().casefold()
        rows = [p for p in rows if not query or query in " ".join(
            str(p.get(k) or "") for k in ("title", "description", "summary")
        ).casefold()]
        return {"projects": [summary(p) for p in rows], "count": len(rows)}
    if action not in ("read", "status", "delegate", "report", "work"):
        raise ValueError("未対応の操作です")
    target = (await projects.get_project_by_room_id(room_id) if action == 'work'
              else await projects.get_project(str(params.get("project_id") or ""), user_id))
    if not target or not target.get("room_id"):
        raise ValueError("対象プロジェクトが見つからないか、アクセス権がありません")
    target_room = target["room_id"]
    if not await chat.get_room(target_room, user_id):
        raise ValueError("対象の部屋へのアクセス権がありません")
    if action == "status":
        from app.services.run_service import RunService
        run = await RunService().get_current_run(target['id'])
        activity = await projects.get_execution_events(target['id'], run_id=run['id'], limit=20) if run else []
        return {'project': summary(target), 'run': run, 'activity': activity}
    if action == "read":
        limit = min(50, max(1, int(params.get("limit") or 4)))
        messages = await chat.get_messages(target_room, user_id, limit=limit, before=params.get("before"))
        messages.sort(key=lambda message: message.get('created_at') or '')
        result = {"project": summary(target), "messages": [
            {k: m.get(k) for k in ("id", "sender_type", "content", "created_at")} for m in messages
        ], "next_before": min((m["created_at"] for m in messages), default=None) if len(messages) == limit else None}
        from app.services import timeline_live
        result["editor"] = await asyncio.to_thread(timeline_live.editor_state, target_room)
        from app.services.run_service import RunService
        run = await RunService().get_current_run(target['id'])
        result['run'] = run
        result['activity'] = await projects.get_execution_events(target['id'], run_id=run['id'], limit=20) if run else []
        from app.services.command_cards import outbound_cards
        result['outbound'] = await outbound_cards(target_room)
        return result
    task = str(params.get("task") or "").strip()
    if not task or len(task) > 2800:
        raise ValueError("作業・報告の本文は1〜2800文字で指定してください")
    source = await projects.get_project_by_room_id(room_id)
    if not source or source.get("user_id") != user_id:
        raise ValueError("依頼元プロジェクトを確認できません")
    if action == "report":
        message = await chat.send_message(target_room, user_id,
            f"【{source['title']}からの報告】\n{task}\n\n[作業の部屋](/chat/{source['id']})", sender_type="ai", message_id=report_message_id)
        return {"reported": True, "message_id": message["id"], "project": summary(target)}
    if target_room == room_id and action != 'work':
        raise ValueError("今の部屋の作業は自分の作業モードで実行してください")
    # Immediate work has one durable owner. The shared watch table can be
    # consumed by older notification workers, which cannot execute this job.
    from app.services import command_job_state
    job_id = str(uuid4())
    command_job_state.create(job_id,user_id=user_id,room_id=target_room,origin_room_id=room_id,
        origin_project_id=source['id'],task=task,report_message_id=report_id(job_id),queue_owner='core')
    try:
        await _wake_job(job_id)
    except Exception:
        # A timeout is not proof the command failed: the Core may already have
        # acknowledged it in durable state. Never rerun or fail active work.
        saved = command_job_state.read(job_id)
        if not saved.get('accepted_at'):
            def reject(s):
                if s['state']=='queued' and not s.get('accepted_at'):
                    s.update(state='failed',error='作業担当への接続を確認できませんでした')
                    command_job_state.event(s,'error',s['error'])
            saved = command_job_state.change(job_id,reject)
            if saved['state']=='failed':
                return {'accepted':False,'job_id':job_id,'error':saved['error']}
    return {"accepted": True, "engine":"steerable_cli", "receipt": {'scheduled':True,'id':job_id},
        "project": summary(target), "report_message_id": report_id(job_id)}
