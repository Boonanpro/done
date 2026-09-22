"""Independent, steerable Astra CLI jobs; no paid intermediary completion model."""
import asyncio
import json
import os
from pathlib import Path
import re
import time

from app.services import command_job_state as state
from app.services.editor_codex import CodexTurn

_tasks = {}
_slots = asyncio.Semaphore(4)

def mark_status(job_id, status):
    saved = state.read(job_id)
    if saved and saved.get('queue_owner') == 'core':
        if saved['state']=='completed':
            state.change(job_id,lambda s:s.update(delivery_pending=status=='pending'))
        return  # Job state is authoritative; no notification worker owns it.
    from app.services.followups import mark_status as legacy_status
    legacy_status(job_id,status)

async def recover():
    """A restarted owner must not silently resume an uncertain transaction."""
    from app.services.run_service import RunService
    if not state.ROOT.exists(): return
    for path in state.ROOT.glob('*.json'):
        s = state.read(path.stem)
        if not s or s['state'] in state.TERMINAL: continue
        if s.get('run_id'):
            state.publish(s['id'],'error','実行接続が切れたため停止しました。実行済み操作の確認が必要です。',state='failed',error='Core restarted')
            await RunService().update_run(s['run_id'],state='failed')
            await asyncio.to_thread(mark_status,s['id'],'failed')
        elif s.get('queue_owner') == 'core' and s['state']=='queued':
            dispatch({'id':s['id'],'user_id':s['user_id'],'room_id':s['room_id'],
                'spec':{key:s[key] for key in ('origin_room_id','origin_project_id','task')}})


async def dispatch_pending():
    """Core-only recovery of unstarted jobs and idempotent result delivery."""
    if not state.ROOT.exists(): return
    for path in state.ROOT.glob('*.json'):
        s=state.read(path.stem)
        if not s or s.get('queue_owner')!='core': continue
        if ((s['state']=='queued' and not s.get('run_id')) or
            (s['state']=='completed' and s.get('delivery_pending'))):
            dispatch({'id':s['id'],'user_id':s['user_id'],'room_id':s['room_id'],
                'spec':{key:s[key] for key in ('origin_room_id','origin_project_id','task')}})

def dispatch(row):
    job_id = row['id']
    if job_id not in _tasks or _tasks[job_id].done():
        _tasks[job_id] = asyncio.create_task(run(row))
    return _tasks[job_id]

async def run(row):
    from app.services.chat_service import ChatService
    from app.services.project_service import ProjectService
    from app.services.run_service import RunService
    from app.services.command_center import CONFIRMATION_RULE, report_id, execute
    from app.agent.cli_runner import _build_system_prompt
    job_id, spec = row['id'], row['spec']
    chat, projects, runs = ChatService(), ProjectService(), RunService()
    s = state.create(job_id, user_id=row['user_id'], room_id=row['room_id'],
        origin_room_id=spec['origin_room_id'], origin_project_id=spec['origin_project_id'],
        task=spec['task'], report_message_id=report_id(job_id))
    # Restart recovery never replays a potentially committed transaction.
    if s.get('run_id'):
        if s['state'] == 'completed' and s.get('result'):
            try:
                await execute({'action':'report','project_id':spec['origin_project_id'],'task':s['result'][:2800]},
                    row['room_id'],row['user_id'],report_message_id=report_id(job_id))
                await asyncio.to_thread(mark_status,job_id,'done')
            except Exception:
                await asyncio.to_thread(mark_status,job_id,'pending')
            return
        if s['state'] not in state.TERMINAL:
            state.publish(job_id, 'error', '実行接続が終了しました。実行済みの操作は再実行せず、状態確認が必要です。',
                          state='failed', error='実行接続が終了しました')
            await runs.update_run(s['run_id'], state='failed')
        await asyncio.to_thread(mark_status, job_id, 'done' if s['state']=='completed' else 'failed')
        return
    owner = None
    monitor = None
    receiving = None
    try:
        async with _slots:
            if state.read(job_id)['state'] in state.TERMINAL:
                return
            state.publish(job_id,'progress','実行先を確認しています')
            project = await projects.get_project_by_room_id(row['room_id'])
            if not project:raise RuntimeError('実行先のプロジェクトが見つかりません')
            message = await chat.send_message(row['room_id'], row['user_id'],
                '【あなたの依頼・Done経由】\n' + spec['task'], sender_type='system',
                message_id=report_id(job_id + ':request'))
            run_row = await runs.create_run(project['id'], row['room_id'], origin_message_id=message['id'],
                metadata={'started_by':'command_center', 'watch_id':job_id, 'engine':'steerable_cli',
                          'origin_room_id':spec['origin_room_id']})
            initial_state = state.read(job_id)['state']
            state.publish(job_id, 'progress', '依頼内容を確認しています', run_id=run_row['id'],
                          state='running' if initial_state=='queued' else initial_state)
            instructions = await asyncio.to_thread(_build_system_prompt, project.get('title',''),
                project.get('description') or '', project.get('status') or 'in_progress',
                latest_user_message=spec['task'], room_id=row['room_id'], user_id=row['user_id'], include_room_role=False)
            instructions += '\n' + CONFIRMATION_RULE + '''
この依頼は独立した作業です。利用者との追加会話は同じ実行へ届きます。
購入・送信・削除・支払いなど取り返しのつかない確定の直前だけ、具体的な内容と金額を言葉で伝えて本人の返事を待つ（そこでターンを終える。返事は追加の発言として届く）。それ以外の操作は承認を求めずに最後まで進める。承認や追加指示が届くと同じ作業が再開する。
ブラウザはこの作業専用。通常のDanブラウザ道具を使う。コマンドも使える（カレンダーは python D:/done/scripts/dan_calendar.py list --days 7 など）。
PCの画面にページやアプリを出してほしいと言われたら、コマンドで一発で出す（例: python -c "import webbrowser;webbrowser.open('URL')" で普段のブラウザに開く）。
ブラウザは通常、画面の文字と要素参照を返す。画像が必要なら screenshot を使う。
確認済みの複数操作は browser_script でまとめられる。途中の観測を見て判断する必要があるところで区切る。
実行結果と残件を短く報告する。外部APIのクライアントを自作して確認手順を迂回しない。
'''
            # Only the job-scoped Dan MCP is enabled; inherited connectors cannot
            # bypass the job's confirmation and pause boundary.
            config_path = Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))) / 'config.toml'
            names = re.findall(r'^\[mcp_servers\.([^\].]+)\]', config_path.read_text(encoding='utf-8'), re.M) if config_path.exists() else []
            mcp = {n.strip('"'): {'enabled':False} for n in names}
            mcp['dan_job'] = {'command':'python', 'args':[str(Path(__file__).resolve().parents[2]/'app/mcp_server.py')],
                'tool_timeout_sec':3600, 'default_tools_approval_mode':'approve',
                'env': {'DAN_USER_ID':row['user_id'], 'DAN_SESSION_ID':row['room_id'],
                    'DAN_BROWSER_ROOM':state.browser_room(job_id), 'DAN_COMMAND_JOB_ID':job_id,
                    'DAN_BROWSER_HEADLESS':'1', 'DAN_BROWSER_OBSERVATION':'dom', 'DAN_CORE_PORT':'9000'}}
            owner = CodexTurn()
            owner.receive_timeout = 3600
            recent = await chat.get_messages(row['room_id'],row['user_id'],limit=8)
            history = [{'role':'user','content':'部屋の記録（過去の発言）: '+str(m.get('content',''))[:6000]}
                for m in sorted(recent,key=lambda m:m.get('created_at') or '') if m.get('id')!=message['id']]
            await owner.start([*history,{'role':'user','content':spec['task']}], [{'type':'web_search'}], instructions,
                'gpt-6-astra', sandbox='danger-full-access',   # the same reach as chat Dan; the owner's decision 2026-09-22
                config_overrides={'mcp_servers':mcp})
            state.change(job_id, lambda s:s.update(thread_id=owner.thread_id))
            pending = {}
            turn_active = True
            sent = 0
            async def controls():
                nonlocal sent
                heartbeat = 0
                while True:
                    await asyncio.sleep(.15)
                    s = state.read(job_id)
                    if s['state'] == 'cancelled':
                        owner.send({'id':900000, 'method':'turn/interrupt', 'params':{'threadId':owner.thread_id,'turnId':owner.turn_id}})
                        owner.close(); return
                    if not turn_active:
                        continue
                    for item in s['inputs']:
                        if item['revision'] > sent:
                            owner.serial += 1
                            pending[owner.serial] = item['revision']
                            owner.send({'id':owner.serial, 'method':'turn/steer', 'params':{
                                'threadId':owner.thread_id, 'expectedTurnId':owner.turn_id,
                                'input':[{'type':'text','text':item['text']}]}})
                            sent = item['revision']
                    if time.monotonic() - heartbeat > 10:
                        await runs.update_run(run_row['id'], state=s['state'] if s['state'] in {'paused','awaiting_confirmation'} else 'running',only_if_active=True)
                        heartbeat = time.monotonic()
            monitor = asyncio.create_task(controls())
            result = ''
            while True:
                event = await owner.receive()
                method, params = event.get('method'), event.get('params',{})
                if method and 'id' in event:
                    state.publish(job_id,'diagnostic','実行接続からの要求: '+method)
                if method is None and event.get('id') in pending:
                    revision = pending.pop(event['id'])
                    if event.get('error'):
                        state.publish(job_id, 'error', '追加指示を反映できなかったため停止しています', state='paused')
                    else:
                        def applied(s):
                            s['applied_revision'] = max(s['applied_revision'], revision)
                            state.event(s, 'applied', '追加指示を実行担当が受け取りました')
                        state.change(job_id, applied)
                elif method == 'item/completed' and params.get('item',{}).get('type') == 'agentMessage':
                    result = params['item']['text']
                    if params['item'].get('phase') != 'final_answer':
                        state.publish(job_id, 'progress', result)
                    await projects.save_execution_event(project['id'], row['room_id'], 'reasoning',
                        content=result, run_id=run_row['id'])
                elif method == 'turn/completed':
                    turn_active = False
                    s = state.read(job_id)
                    if s['state'] == 'cancelled': break
                    if params['turn']['status'] != 'completed': raise RuntimeError(str(params['turn'].get('error') or params['turn']['status']))
                    if s['state'] in {'awaiting_confirmation','paused'} or s.get('approved') or s['revision'] > s['applied_revision']:
                        if s['state'] in {'awaiting_confirmation','paused'}:
                            await runs.update_run(run_row['id'],state=s['state'],only_if_active=True)
                        while s['state'] in {'awaiting_confirmation','paused'}:
                            await asyncio.sleep(.15)
                            s=state.read(job_id)
                        if s['state']=='cancelled': break
                        if s['state'] in state.TERMINAL: return
                        continuation={'state':s['state'],'confirmation':s.get('confirmation'),
                            'approved':bool(s.get('approved')),'new_inputs':[i for i in s['inputs'] if i['revision']>s['applied_revision']]}
                        resumed=await owner.rpc('turn/start',{'threadId':owner.thread_id,'input':[{'type':'text','text':
                            '本人の返事を受け付けた現在の作業状態です。確定操作はまだ実行していません。画面を読み取り、承認済みの具体的な操作だけを再開してください。条件変更があれば以前の承認は無効です。\n'+json.dumps(continuation,ensure_ascii=False)}]})
                        owner.turn_id=resumed['turn']['id']
                        revision=s['revision']
                        sent=max(sent,revision)
                        state.change(job_id,lambda current:current.update(applied_revision=max(current['applied_revision'],revision)))
                        await runs.update_run(run_row['id'],state='running',only_if_active=True)
                        result=''
                        turn_active=True
                        continue
                    if not result: raise RuntimeError('作業結果が空でした')
                    state.publish(job_id, 'result', result, result=result, state='completed')
                    await runs.update_run(run_row['id'], state='completed')
                    await execute({'action':'report','project_id':spec['origin_project_id'],'task':result[:2800]},
                        row['room_id'], row['user_id'], report_message_id=report_id(job_id))
                    await asyncio.to_thread(mark_status, job_id, 'done')
                    return
                elif method == 'process/closed':
                    if state.read(job_id)['state'] == 'cancelled': break
                    raise RuntimeError('実行接続が終了しました')
                elif method and 'id' in event:
                    owner.send({'id':event['id'],'error':{'code':-32601,'message':'Use the job-scoped Dan tools.'}})
            await runs.update_run(run_row['id'], state='superseded')
            await asyncio.to_thread(mark_status, job_id, 'cancelled')
    except Exception as exc:
        saved = state.read(job_id)
        if saved and saved['state'] == 'completed':
            state.publish(job_id,'error','作業結果は保存済みです。部屋への配達を再試行します。')
            await asyncio.to_thread(mark_status,job_id,'pending')
            return
        text = '作業を停止しました: ' + str(exc)[:600]
        s = state.publish(job_id, 'error', text, state='failed', error=text)
        if s.get('run_id'): await runs.update_run(s['run_id'], state='failed')
        await asyncio.to_thread(mark_status, job_id, 'failed')
    finally:
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if owner: owner.close()
