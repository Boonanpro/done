"""Run-scoped stop delivery. Receipt is never an execution-exit acknowledgement."""
import asyncio


async def restore_stop(room_id, run_id):
    """Restore a recorded stop before preparing/restarting an existing run.

    A failed read must propagate: absence of evidence is not permission to
    restart work. Only the exact run in the expected room may set its gate.
    """
    from app.services.run_service import RunService
    from app.services.cancellation import CancellationRegistry
    run = await RunService().get_run(run_id)
    if not run or run.get('id') != run_id or run.get('room_id') != room_id:
        raise ValueError('対象の作業記録を確認できません')
    if (run.get('metadata') or {}).get('stop_request'):
        CancellationRegistry.mark_matched_run_cancelled(room_id, run_id)
    return CancellationRegistry.is_run_cancelled(room_id, run_id)


async def local_stop(run, user_id):
    from app.core.generations import identity
    from app.services.project_service import ProjectService
    project = await ProjectService().get_project(run['project_id'], user_id)
    if not project or project.get('user_id') != user_id or project.get('room_id') != run['room_id']:
        raise PermissionError('対象の作業へのアクセス権がありません')
    metadata = run.get('metadata') or {}
    if metadata.get('process_owner') != identity() or metadata.get('started_by') == 'command_center':
        return {'accepted': False, 'stopped': False, 'reason': '実行先が一致しません。別の作業は停止していません。'}
    from app.services.cancellation import CancellationRegistry
    from app.agent.streaming_session import get_session
    from app.agent.cli_runner import request_cli_run_stop
    room, run_id = run['room_id'], run['id']
    gated = CancellationRegistry.cancel_run(room, run_id)
    session = get_session(room)
    interrupted = await asyncio.to_thread(session.interrupt, expected_run_id=run_id) if session else False
    process = await asyncio.to_thread(request_cli_run_stop, room, run_id)
    accepted = bool(gated or interrupted or process.get('accepted'))
    if accepted:
        from datetime import datetime, timezone
        from app.services.run_service import RunService
        try:
            saved = await RunService().update_run(run_id, metadata={'stop_request': {
                'at': datetime.now(timezone.utc).isoformat(), 'stopped': False}})
            if not saved:
                raise RuntimeError('停止の記録を保存できませんでした')
        except Exception:
            # Receipt delivery must not turn into a retry of the stop action
            # merely because recording it failed.
            return {'accepted': True, 'stopped': False, 'run_id': run_id,
                    'note': '停止を受け付けました。記録の保存と実行中の操作の終了は確認できていません。'}
    return {'accepted': accepted, 'stopped': False, 'run_id': run_id,
            'note': ('停止を受け付けました。実行中の操作の終了はまだ確認できていません。' if accepted
                     else '対象の実行を確認できませんでした。停止済みとは判断できません。')}


async def request_stop(run, user_id):
    """Send once to a known owner. A timeout is ambiguous, never a success."""
    import httpx
    from app.core import generations as G
    from app.services.browser_lifecycle import _token_path
    saved = G.read(G.key('room', run['room_id']))
    if saved and saved.get('run_id') == run['id']:
        owner = G.owner('room', run['room_id'])
        if not owner:
            return {'accepted': False, 'stopped': False, 'note': '作業の実行先に接続できません。'}
        port = owner['core']
    else:
        # Legacy turns have no generation record. The endpoint checks the
        # actual process identity; an old run can never stop a replacement.
        port = 9000
    try:
        async with httpx.AsyncClient(timeout=8, trust_env=False) as client:
            response = await client.post(f'http://127.0.0.1:{port}/internal/runs/stop',
                json={'run_id': run['id'], 'user_id': user_id},
                headers={'x-dan-browser-token': _token_path().read_text().strip()})
            response.raise_for_status()
            return response.json()
    except (OSError, httpx.HTTPError, ValueError):
        return {'accepted': False, 'stopped': False, 'note': '停止の受付を確認できませんでした。停止済みとは判断できません。'}


def status(run):
    if run and (run.get('metadata') or {}).get('stop_request'):
        return {'accepted': True, 'stopped': False,
                'note': '停止受付の記録があります。runの完了表示だけでは実行中の道具の終了まで証明できません。'}
    return None
