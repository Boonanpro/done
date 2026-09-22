"""The Core side of an API job: the same preamble, state, steering, cancellation and delivery as a Codex CLI job
(command_job_runner), but the model loop runs in api_job_worker (a small Python process using the Responses API) instead
of the Codex CLI with an MCP child. Chosen per job: state['engine'] == 'api' (voice-originated work by default).
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from app.services import command_job_state as state
from app.services.command_job_runner import mark_status

JOB_INSTRUCTIONS = '''
この依頼は独立した作業です。利用者との追加会話は同じ実行へ届きます。
購入・送信・削除・支払いなど取り返しのつかない確定の直前だけ、具体的な内容と金額を言葉で伝えて本人の返事を待つ（そこでターンを終える。返事は追加の発言として届く）。それ以外の操作は承認を求めずに最後まで進める。承認や追加指示が届くと同じ作業が再開する。
ブラウザはこの作業専用。通常のDanブラウザ道具を使う。コマンド（bash）も使える（カレンダーは python D:/done/scripts/dan_calendar.py list --days 7 など）。
PCの画面にページやアプリを出してほしいと言われたら、コマンドで一発で出す（例: python -c "import webbrowser;webbrowser.open('URL')" で普段のブラウザに開く）。
ブラウザは通常、画面の文字と要素参照を返す。画像が必要なら screenshot を使う。
同じサイトで同じ種類の作業を頼まれたら、まず flow（action=list）を見て、合う手順があれば replay を使う。
実行結果と残件を短く報告する。外部APIのクライアントを自作して確認手順を迂回しない。
'''


async def run(row):
    from app.services.chat_service import ChatService
    from app.services.project_service import ProjectService
    from app.services.run_service import RunService
    from app.services.command_center import CONFIRMATION_RULE, report_id, execute
    from app.agent.cli_runner import _build_system_prompt
    job_id, spec = row['id'], row['spec']
    chat, projects, runs = ChatService(), ProjectService(), RunService()
    process, monitor = None, None
    try:
        if state.read(job_id)['state'] in state.TERMINAL:
            return
        state.publish(job_id, 'progress', '実行先を確認しています')
        project = await projects.get_project_by_room_id(row['room_id'])
        if not project: raise RuntimeError('実行先のプロジェクトが見つかりません')
        message = await chat.send_message(row['room_id'], row['user_id'], '【あなたの依頼・Done経由】\n' + spec['task'],
                                          sender_type='system', message_id=report_id(job_id + ':request'))
        run_row = await runs.create_run(project['id'], row['room_id'], origin_message_id=message['id'],
                                        metadata={'started_by': 'command_center', 'watch_id': job_id, 'engine': 'api', 'origin_room_id': spec['origin_room_id']})
        initial_state = state.read(job_id)['state']
        state.publish(job_id, 'progress', '依頼内容を確認しています', run_id=run_row['id'], state='running' if initial_state == 'queued' else initial_state)
        if os.environ.get('DAN_API_JOB_FULL_PROMPT') == '1':
            instructions = await asyncio.to_thread(_build_system_prompt, project.get('title', ''), project.get('description') or '',
                                                   project.get('status') or 'in_progress', latest_user_message=spec['task'],
                                                   room_id=row['room_id'], user_id=row['user_id'], include_room_role=False)
        else:
            # A job needs the job's rules, not the whole persona (13k characters resent on every call)
            instructions = f"あなたはダン。本人（このアカウントの持ち主）に頼まれた作業を、このパソコンのブラウザや道具で実行する。部屋: {project.get('title', '')}。"
        instructions += '\n' + CONFIRMATION_RULE + JOB_INSTRUCTIONS
        recent = await chat.get_messages(row['room_id'], row['user_id'], limit=8)
        history = ['部屋の記録（過去の発言）: ' + str(m.get('content', ''))[:6000]
                   for m in sorted(recent, key=lambda m: m.get('created_at') or '') if m.get('id') != message['id']]
        state.change(job_id, lambda s: s.update(instructions=instructions, history=history))
        env = {**os.environ, 'DAN_USER_ID': row['user_id'], 'DAN_SESSION_ID': row['room_id'], 'DAN_BROWSER_ROOM': state.browser_room(job_id),
               'DAN_COMMAND_JOB_ID': job_id, 'DAN_BROWSER_HEADLESS': '1', 'DAN_BROWSER_OBSERVATION': 'dom', 'DAN_CORE_PORT': '9000',
               'PYTHONIOENCODING': 'utf-8'}
        root = Path(__file__).resolve().parents[2]
        creation = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0   # never a console window (owner's rule)
        process = await asyncio.create_subprocess_exec(sys.executable, '-m', 'app.services.api_job_worker', job_id, cwd=str(root), env=env,
                                                       stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE, creationflags=creation)
        state.change(job_id, lambda s: s.update(worker_pid=process.pid))

        async def controls():
            heartbeat = 0
            while True:
                await asyncio.sleep(.2)
                s = state.read(job_id)
                if s['state'] == 'cancelled' and process.returncode is None:
                    process.terminate(); return
                if time.monotonic() - heartbeat > 10:
                    await runs.update_run(run_row['id'], state=s['state'] if s['state'] in {'paused', 'awaiting_confirmation'} else 'running', only_if_active=True)
                    heartbeat = time.monotonic()
        monitor = asyncio.create_task(controls())
        _, stderr = await process.communicate()
        s = state.read(job_id)
        if s['state'] == 'cancelled':
            await runs.update_run(run_row['id'], state='superseded')
            await asyncio.to_thread(mark_status, job_id, 'cancelled')
            return
        if s['state'] != 'completed':
            tail = (stderr or b'').decode('utf-8', 'replace').strip().splitlines()[-1:] if stderr else []
            raise RuntimeError(f'実行担当が終了しました (rc={process.returncode})' + (': ' + tail[0][:300] if tail else ''))
        result = s.get('result') or ''
        await runs.update_run(run_row['id'], state='completed')
        await execute({'action': 'report', 'project_id': spec['origin_project_id'], 'task': result[:2800]}, row['room_id'], row['user_id'],
                      report_message_id=report_id(job_id))
        await asyncio.to_thread(mark_status, job_id, 'done')
    except Exception as exc:
        saved = state.read(job_id)
        if saved and saved['state'] == 'completed':
            state.publish(job_id, 'error', '作業結果は保存済みです。部屋への配達を再試行します。')
            await asyncio.to_thread(mark_status, job_id, 'pending')
            return
        text = '作業を停止しました: ' + str(exc)[:600]
        s = state.publish(job_id, 'error', text, state='failed', error=text)
        if s.get('run_id'): await runs.update_run(s['run_id'], state='failed')
        await asyncio.to_thread(mark_status, job_id, 'failed')
    finally:
        if monitor:
            monitor.cancel()
            await asyncio.gather(monitor, return_exceptions=True)
        if process and process.returncode is None:
            process.terminate()
