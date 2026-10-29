"""Dan's browsers should be signed in to Chrome with the user's Google account, unless the user does not want that.

Owner (2026-10-01): a browser signed in as a person is the normal state; sites and Google treat a signed-in Chrome as a
person's. So Dan notices when the Chrome it works in is not signed in, asks the user once (naming the Google accounts it
knows, or asking which), and signs in itself once the user says which account. A user who says no is not asked again.
Owner (2026-10-15): signing in is recommended, and once approved Dan signs in before it works on a site, not afterwards:
pages such as reCAPTCHA judge the browser while Dan is using them. A failed sign-in is recorded and not retried for a day,
since Google suspends accounts after repeated failed sign-ins.

Whether a Chrome profile is signed in: its 'Local State' file, profile.info_cache.Default.user_name (what the avatar at
the top right shows; empty when only websites are logged in). What the user said: ~/.dan/chrome-signin/<user>.json
  {state: 'asked' | 'approved' | 'declined', account, at, failed_at}
"""
import json
import os
import time
from pathlib import Path

ROOT = Path.home()/'.dan'/'chrome-signin'
ASK_AGAIN_DAYS = 7   # asked and never answered: once more after a week
RETRY_AFTER_FAILED = 86400   # a failed sign-in is not tried again for a day
SIGN_IN_PAGES = ('chrome://', 'accounts.google.com', 'myaccount.google.com')   # the sign-in itself


def signed_in(profile_dir):
    """The Google account this Chrome profile is signed in with, or ''."""
    try:
        info = json.loads((Path(profile_dir)/'Local State').read_text(encoding='utf-8'))
        return ((info.get('profile') or {}).get('info_cache') or {}).get('Default', {}).get('user_name') or ''
    except (OSError, ValueError):
        return ''


def _file(user_id):
    return ROOT/f'{user_id}.json'


def state(user_id):
    try:
        return json.loads(_file(user_id).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _set(user_id, **fields):
    ROOT.mkdir(parents=True, exist_ok=True)
    _file(user_id).write_text(json.dumps({**state(user_id), **fields, 'at': time.time()}, ensure_ascii=False), encoding='utf-8')


async def known_accounts(user_id):
    """The Google accounts Dan has saved logins for (addresses only)."""
    from app.services.credentials_service import get_credentials_service
    service = get_credentials_service()
    found = []
    for row in await service.list_credentials(user_id):
        name = (row.get('service') or '').lower()
        if 'google' not in name and 'gmail' not in name:
            continue
        try: login = ((await service.get_credential(user_id, row.get('service'))) or {}).get('id') or ''
        except Exception: login = ''
        if '@' in login and 'gserviceaccount' not in login and login.lower() not in found:   # a machine identity cannot sign in to Chrome
            found.append(login.lower())
    return found


SIGN_IN = ('Chrome へのログイン手順（ダン用ブラウザ）: browser で chrome://settings/people を開き「同期を有効にする」または「ログイン」を押す。'
           'Google のログイン画面は browser で進める（保存済みの情報は fill_credential、2段階認証はスマホへの通知が出たら「別の方法を試す」'
           '→「Google 認証システム」を選んで fill_totp_code）。'
           'Chrome 自体の確認画面（「〇〇として続行」「同期を有効にしますか」など）はページではないので desktop で押す。'
           '履歴の同期を聞かれたら「利用しない」を押す（「同期をカスタマイズ」が出たらパスワードとお支払い方法をオフにする）。失敗したら同じ操作をくり返さず、止まって本人に報告する'
           '（Google はくり返しのログイン失敗でアカウントを止める）。失敗したら chrome_signin(action=failed) で記録する（1日は試さない）。'
           '終わったら chrome_signin(action=check) で確かめる。')


async def note(user_id, profile_dir, url=''):
    """What the model is told when a browser opens: '' when nothing is to be done."""
    if not user_id or not profile_dir or signed_in(profile_dir):
        return ''
    if any(page in (url or '') for page in SIGN_IN_PAGES):
        return ''   # Dan is signing in right now
    said = state(user_id)
    if said.get('state') == 'declined':
        return ''
    if said.get('state') == 'approved' and said.get('account'):
        if time.time() - said.get('failed_at', 0) < RETRY_AFTER_FAILED:
            return ''
        return (f'（ダンへ）このブラウザはまだ Chrome にログインしていない。本人は {said["account"]} でのログインを承認済み。'
                'このページを操作する前に、本人に聞かずにログインを済ませ、それから open_target でこのページを開き直して作業を始める。'
                '（ログインしたブラウザは Google の画像認証などで止まりにくい）' + SIGN_IN)
    if said.get('state') == 'asked' and time.time() - said.get('at', 0) < ASK_AGAIN_DAYS*86400:
        return ''
    accounts = await known_accounts(user_id)
    _set(user_id, state='asked')
    why = 'ログインしておくと、Google の「私はロボットではありません」などで止まりにくくなるのでおすすめです。'
    ask = (f'このブラウザ（Chrome）を Google アカウントでログインしておきますか？ {why}候補: {" / ".join(accounts)}。どれにするか教えてください（ログインしないままでもよい）'
           if accounts else f'このブラウザ（Chrome）を Google アカウントでログインしておきますか？ {why}ログインするなら、どのアカウントか（とパスワード）を教えてください（ログインしないままでもよい）')
    return ('（ダンへ）このブラウザは Chrome にログインしていない。今の作業は止めずに進め、本人への報告の最後に一言だけ聞く:'
            f'「{ask}」。答えを聞いたら chrome_signin で記録する（approve: account／decline）。承認されたらダンがログインする。')


TOOL = {
    'name': 'chrome_signin',
    'description': ('ダン用ブラウザ（Chrome 自体）の Google アカウントへのログインについて、本人の答えを記録する・状態を見る。'
                    'approve(account): 本人がそのアカウントでのログインを望んだ（この後ダンがログインする）。decline: 本人がログインを望まない（以後聞かない）。'
                    'failed: ログインを試して失敗した（1日は試さず、ログインしないまま作業する）。'
                    'check: 今のブラウザが Chrome にログインしているか。'),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['approve', 'decline', 'failed', 'check']},
        'account': {'type': 'string', 'description': 'approve: ログインする Google アカウント'},
    }, 'required': ['action'], 'additionalProperties': False},
}


async def tool(params, room_id=''):
    user_id = os.environ.get('DAN_USER_ID', '')
    action = params.get('action')
    if action == 'approve':
        account = str(params.get('account') or '').strip().lower()
        if '@' not in account:
            return {'success': False, 'error': 'account にメールアドレスを入れてください'}
        _set(user_id, state='approved', account=account, failed_at=0)
        return {'success': True, 'output': f'{account} でのログインを承認として記録した。' + SIGN_IN}
    if action == 'decline':
        _set(user_id, state='declined')
        return {'success': True, 'output': '本人はログインを望まない。以後は聞かず、ログインしないままのブラウザで作業する。'}
    if action == 'failed':
        _set(user_id, failed_at=time.time())
        return {'success': True, 'output': 'ログインの失敗を記録した。1日は試さず、ログインしないまま作業を続け、失敗したことを本人に報告する。'}
    from app.tools.browser import _browser_room_id, _executor_profile_dir
    from app.services.browser_lifecycle import profile_for_room
    # Run in the core, the env names no room and _executor_profile_dir is the master profile, not this room's browser.
    account = signed_in(profile_for_room(room_id) if room_id and not _browser_room_id() else _executor_profile_dir())
    return {'success': True, 'output': f'このブラウザは {account} で Chrome にログインしている。' if account else 'このブラウザは Chrome にログインしていない。'}
