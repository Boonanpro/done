"""chat Dan's tool for parallel work in its room (parallel_job_runner)."""
import asyncio

TOOL = {
    "name": "parallel_work",
    "description": (
        "この部屋の中で、別の作業を並行して走らせる。今の本人との会話は止めずに続けられる。"
        "start=作業を起動する（task に作業内容をそのまま渡す。model を省略すると最新の GPT Astra（High）。本人の指定がある時は model に入れる）。"
        "起動した作業はこの部屋の会話を引き継いだ別の会話として動き、終わると結果がこの部屋に「並行作業」として届く。"
        "list=この部屋の並行作業の一覧と状態。update=作業に指示を足す（終わった作業も、指示を足すとその続きから再開する）。"
        "cancel=止める。switch_model=同じ作業を別のモデルでやり直す。"
        "同じファイルやPCの画面操作・スマホ操作を使う作業同士は自動で順番になるので、気にせず並べてよい。"
        "使いどころ: 本人が並行を望んだ時、今の作業と独立した長い調査や制作を頼まれた時。作業の結果について本人が答えた時は update でその作業に渡す。"
        "足すか分けるかは、触る物で決める。動いている作業と同じ物（同じ動画・文書・ページ・メール・予約・調べもの）への頼みは、別の所の直しでも update でその作業に足す"
        "（2つの作業が同じ物を同時に直すと直しがぶつかり、それぞれが最初から読み直すので費用とMacの負担が増える）。"
        "触る物が別の頼みは、動いている作業を待たせずに start で別に立てる（2026-11-27 本人）。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["start", "list", "update", "cancel", "switch_model"]},
            "task": {"type": "string", "description": "start: 作業内容。本人の言葉と、作業に必要な前提をそのまま書く。"},
            "title": {"type": "string", "description": "start: 部屋の作業一覧に出す短い名前（20字ほど。例: 伸びる投稿の調査）。"},
            "model": {"type": "string", "description": "start / switch_model: opus / fable / gpt-6。"},
            "job_id": {"type": "string", "description": "update / cancel / switch_model の対象（list の id）。"},
            "text": {"type": "string", "description": "update: 足す指示。"},
        },
        "required": ["action"],
    },
}


async def execute(params, room_id, user_id):
    import os
    from app.services import parallel_job_runner as runner
    action = params.get('action')
    if os.environ.get('DAN_COMMAND_JOB_ID') and action != 'list':
        return {'error': '並行作業の中からは、ほかの並行作業を起動・操作しない。必要なら最後の報告に書く（部屋のダンが判断する）。'}
    try:
        if action == 'start':
            task = str(params.get('task') or '').strip()
            if not task:
                return {'error': 'task が必要です'}
            from app.services.editor_handoff import from_chat
            task = await from_chat(params, params.get('title', ''), room_id, user_id)
            job = await runner.start(room_id, user_id, task, params.get('model') or '', str(params.get('title') or ''))
            return {'started': runner.public(job)}
        if action == 'list':
            rows = await asyncio.to_thread(runner.room_jobs, user_id, room_id)
            return {'jobs': [runner.public(s) for s in rows]}
        if action in ('update', 'cancel', 'switch_model'):
            update = str(params.get('text') or '')
            if action == 'update':
                from app.services.editor_handoff import from_chat
                update = await from_chat({**params, 'task': update}, '', room_id, user_id)
            job = await runner.control(room_id, user_id, str(params.get('job_id') or ''), action,
                                       update, str(params.get('model') or ''))
            return {'job': runner.public(job)}
        return {'error': '未対応の操作です'}
    except ValueError as exc:
        return {'error': str(exc)}
