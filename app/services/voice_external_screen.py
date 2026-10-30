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
    path = safe_image(out.get('stage_image'))
    if not path:
        capture = {'action': 'screenshot'}
        if source == 'phone' and arguments.get('serial'):
            capture['serial'] = arguments['serial']
        try:
            observed = await host.ask('call', with_media=True, name=source, arguments=capture)
            path = safe_image(observed.get('stage_image'))
        except Exception:
            path = ''
    if stage.version != version:
        result['screen'] = {'shown': False, 'reason': '別の画面に切り替わりました。'}
    elif path:
        stage._apply('スマホの画面' if source == 'phone' else 'ブラウザの画面', image=path)
        stage._external_source = source
        result['screen'] = {'shown': True}
    else:
        # Do not leave an old photograph looking like evidence of the operation's result.
        stage._apply('操作後の画面を取得できませんでした', image='')
        result['screen'] = {'shown': False, 'reason': '操作後の画面は未確認です。操作を再送せず画面だけ確かめてください。'}
    return result
