"""Mirror the actual tool session after screen operations, independent of the site or app."""
from app.services.voice_stage import safe_image

SOURCES = {'browser': 'browser', 'browser_plan': 'browser', 'browser_flow': 'browser', 'phone': 'phone'}
# Lifecycle/metadata calls must neither open a screen nor replace the owner's current view.
NO_SCREEN = {'close', 'hold', 'release', 'session_status', 'devices', 'list_devices'}

async def execute(host, stage, tool, arguments):
    arguments = dict(arguments)
    source = SOURCES.get(tool)
    display = stage is not None and source and arguments.get('action') not in NO_SCREEN
    version = stage.version if display else None
    previous_room = getattr(stage, "_external_browser_room", None)
    previous_job = getattr(stage, "_external_job_id", None)
    if display and tool == 'browser':
        arguments['observation'] = 'full'
    out = await host.ask('call', with_media=True, name=tool, arguments=arguments)
    result = {'result': out.get('text', '')}
    if not display:
        return result
    # A newer user-requested scene wins over a slow tool finishing in the background.
    if stage.version != version:
        result['screen'] = {'shown': False, 'reason': '別の画面に切り替わりました。'}
        return result
    path = safe_image(out.get('stage_stream')) or safe_image(out.get('stage_image'))
    if not path:
        capture = {'action': 'screenshot'}
        if source == 'phone' and arguments.get('serial'):
            capture['serial'] = arguments['serial']
        try:
            observed = await host.ask('call', with_media=True, name=source, arguments=capture)
            path = safe_image(observed.get('stage_stream')) or safe_image(observed.get('stage_image'))
        except Exception:
            path = ''
    if stage.version != version:
        result['screen'] = {'shown': False, 'reason': '別の画面に切り替わりました。'}
    elif path:
        stage._apply('スマホの画面' if source == 'phone' else 'ブラウザの画面', image=path)
        stage._external_source = source
        browser_room = getattr(host, 'browser_room', None)
        stage._external_job_id = previous_job if browser_room and browser_room == previous_room else None
        stage._external_browser_room = browser_room
        stage._external_image = path
        stage._external_serial = out.get("stage_serial") or arguments.get("serial", "")
        result['screen'] = {'shown': True}
    else:
        # Do not leave an old photograph looking like evidence of the operation's result.
        stage._apply('操作後の画面を取得できませんでした', image='')
        result['screen'] = {'shown': False, 'reason': '操作後の画面は未確認です。操作を再送せず画面だけ確かめてください。'}
    return result


async def scroll(host, stage, direction):
    """One safe navigation call; no tool-discovery or second screen-read roundtrip."""
    if direction not in ('up','down'):
        return {'ok':False,'error':'方向は up か down です。'}
    if stage is None:
        return {'ok':False,'error':'操作する画面がありません。'}
    if getattr(stage,'frame',''):
        from app.services import voice_screen
        screen = voice_screen.current(stage)
        if not screen: return voice_screen.inspect(stage)
        return await voice_screen.operate(stage,'scroll',direction=direction,page_id=screen['page_id'])
    source = getattr(stage,'_external_source','')
    if source not in ('browser','phone') or not getattr(stage,'image','') or stage.image != getattr(stage,'_external_image',None):
        return {'ok':False,'error':'今表示している操作画面を確認できません。'}
    browser_room = getattr(stage, '_external_browser_room', None)
    if source == 'browser' and browser_room:
        from app.services import voice_tools, command_job_state
        job_id = getattr(stage, '_external_job_id', None)
        if job_id:
            job = command_job_state.owned(job_id, stage.user_id, stage.room_id)
            if job.get('browser_room') != browser_room or job.get('current_tool'):
                return {'ok':False,'error':'表示中のブラウザは操作中です。完了を待ってください。'}
        host = voice_tools.host(stage.user_id, stage.room_id, browser_room=browser_room)
    args={'action':'scroll','direction':direction}
    if source=='phone':
        serial=getattr(stage,'_external_serial','')
        if not serial: return {'ok':False,'error':'表示中のスマホを特定できません。'}
        args['serial']=serial
    return await execute(host,stage,source,args)
