"""Dan's browsers should be signed in to Chrome with the user's Google account, unless the user does not want that.

Owner (2026-10-01): a browser signed in as a person is the normal state; sites and Google treat a signed-in Chrome as a
person's. So Dan notices when the Chrome it works in is not signed in, asks the user once (naming the Google accounts it
knows, or asking which), and signs in itself once the user says which account. A user who says no is not asked again.

Whether a Chrome profile is signed in: its 'Local State' file, profile.info_cache.Default.user_name (what the avatar at
the top right shows; empty when only websites are logged in). What the user said: ~/.dan/chrome-signin/<user>.json
  {state: 'asked' | 'approved' | 'declined', account, at}
"""
import json
import os
import time
from pathlib import Path

ROOT = Path.home()/'.dan'/'chrome-signin'
ASK_AGAIN_DAYS = 7   # asked and never answered: once more after a week


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
        if '@' in login and login.lower() not in found:
            found.append(login.lower())
    return found


SIGN_IN = ('Chrome へのログイン手順（ダン用ブラウザ）: browser で chrome://settings/people を開き「同期を有効にする」または「ログイン」を押す。'
           'Google のログイン画面は browser で進める（保存済みの情報は get_credentials、2段階認証は fill_totp_code）。'
           'Chrome 自体の確認画面（「〇〇として続行」「同期を有効にしますか」など）はページではないので desktop で押す。'
           '同期は「同期をカスタマイズ」でパスワードとお支払い方法をオフにする。失敗したら同じ操作をくり返さず、止まって本人に報告する'
           '（Google はくり返しのログイン失敗でアカウントを止める）。終わったら chrome_signin(action=check) で確かめる。')


async def note(user_id, profile_dir):
    """What the model is told when a browser opens: '' when nothing is to be done."""
    if not user_id or not profile_dir or signed_in(profile_dir):
        return ''
    said = state(user_id)
    if said.get('state') == 'declined':
        return ''
    if said.get('state') == 'approved' and said.get('account'):
        return (f'（ダンへ）このブラウザはまだ Chrome にログインしていない。本人は {said["account"]} でのログインを承認済み。'
                '今の作業を先に済ませ、区切りで本人に聞かずにログインしておく。' + SIGN_IN)
    if said.get('state') == 'asked' and time.time() - said.get('at', 0) < ASK_AGAIN_DAYS*86400:
        return ''
    accounts = await known_accounts(user_id)
    _set(user_id, state='asked')
    ask = (f'このブラウザ（Chrome）を Google アカウントでログインしておきますか？ 候補: {" / ".join(accounts)}。どれにするか教えてください（ログインしないままでもよい）'
           if accounts else 'このブラウザ（Chrome）を Google アカウントでログインしておきますか？ ログインするなら、どのアカウントか（とパスワード）を教えてください（ログインしないままでもよい）')
    return ('（ダンへ）このブラウザは Chrome にログインしていない。今の作業は止めずに進め、本人への報告の最後に一言だけ聞く:'
            f'「{ask}」。答えを聞いたら chrome_signin で記録する（approve: account／decline）。承認されたらダンがログインする。')


TOOL = {
    'name': 'chrome_signin',
    'description': ('ダン用ブラウザ（Chrome 自体）の Google アカウントへのログインについて、本人の答えを記録する・状態を見る。'
                    'approve(account): 本人がそのアカウントでのログインを望んだ（この後ダンがログインする）。decline: 本人がログインを望まない（以後聞かない）。'
                    'check: 今のブラウザが Chrome にログインしているか。'),
    'input_schema': {'type': 'object', 'properties': {
        'action': {'type': 'string', 'enum': ['approve', 'decline', 'check']},
        'account': {'type': 'string', 'description': 'approve: ログインする Google アカウント'},
    }, 'required': ['action'], 'additionalProperties': False},
}


async def tool(params):
    user_id = os.environ.get('DAN_USER_ID', '')
    action = params.get('action')
    if action == 'approve':
        account = str(params.get('account') or '').strip().lower()
        if '@' not in account:
            return {'success': False, 'error': 'account にメールアドレスを入れてください'}
        _set(user_id, state='approved', account=account)
        return {'success': True, 'output': f'{account} でのログインを承認として記録した。' + SIGN_IN}
    if action == 'decline':
        _set(user_id, state='declined')
        return {'success': True, 'output': '本人はログインを望まない。以後は聞かず、ログインしないままのブラウザで作業する。'}
    from app.tools.browser import _executor_profile_dir
    account = signed_in(_executor_profile_dir())
    return {'success': True, 'output': f'このブラウザは {account} で Chrome にログインしている。' if account else 'このブラウザは Chrome にログインしていない。'}
