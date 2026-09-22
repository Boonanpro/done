"""First login on a site, done by code instead of one model round trip per field.

A remembered login replays in about 5 seconds, but the first time on ANY site the large model still walked the form
by hand: the owner's phone test spent two minutes on a login (open, look, find the credential, fill the id, look, fill
the password, look, click, look...), 6-9 seconds a step. A login has the same shape everywhere:

    id field -> password field -> submit -> (one-time code) -> out of the login page

Code does that shape. Jev is asked only where the page is ambiguous (which of several inputs is the id, which of several
buttons submits). Values come from the saved credentials and are typed by the existing fill_credential / fill_totp_code /
wait_for_otp_from_app actions, so nothing here ever sees a secret, the confirmation gate still applies, and every step is
recorded by browser_recipes exactly as if the model had done it: the second visit is a replay.

It never guesses twice. A rejected password, an unknown screen, a captcha it cannot place, several saved accounts for
the host: it stops and hands the page to the model with what was already done.
"""
import contextvars
import json
import logging
import os
import re
import time

from app.services import browser_recipes as recipes
from app.tools.browser_metrics import record_timing

logger = logging.getLogger(__name__)
running = contextvars.ContextVar('dan_browser_login_running', default=False)

STEP_WAIT_SECONDS = 10
POLL_SECONDS = .25
MAX_STAGES = 6
BAR = {'probability': .8, 'confidence': .75}
SUBMIT = re.compile(r'ログイン|ログオン|サインイン|sign\s*in|log\s*in|log\s*on|次へ|続ける|続行|進む|continue|next|認証する|送信する?$|submit|verify|確認する?$', re.I)
NOT_SUBMIT = re.compile(r'忘れ|forgot|新規|登録|sign\s*up|register|create|google|apple|facebook|line|twitter|microsoft|github|パスキー|passkey|ヘルプ|help|表示|show', re.I)
CODE_PAGE = re.compile(r'認証コード|確認コード|ワンタイム|セキュリティコード|二段階|2段階|２段階|verification code|one.time|security code|authenticat(?:or|ion) code|6桁|６桁|check your e-?mail|enter (?:the|your) code|code (?:we )?sent|receive a code|コードを送信しました|メールをご確認', re.I)
BY_MAIL = re.compile(r'メール|e-?mail', re.I)
# Fallback only: what the site says after a submit is found by comparing the page text before and after (any language).
REJECTED = re.compile(r'正しくありません|一致しません|間違|誤り|失敗しました|できませんでした|ロック|無効|incorrect|invalid|wrong|failed|locked|try again', re.I)
TEXT_INPUT = {'text', 'email', 'tel', 'number', ''}

CAPTCHA = r"""() => !!document.querySelector('.g-recaptcha,[data-sitekey],iframe[src*="recaptcha"],iframe[src*="turnstile"],iframe[src*="hcaptcha"],.h-captcha,.cf-turnstile')"""
PAGE_LINES = r"""() => (document.body && document.body.innerText || '').split(/\n/).map(s => s.replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 300)"""
PAGE_TEXT = r"""() => {
  const t = (document.body && document.body.innerText || '').replace(/\s+/g, ' ');
  return t.slice(0, 3000);
}"""


class Handoff(Exception):
    pass


async def steady(page, observe, seconds=4.0):
    """The snapshot once the page has stopped growing: two looks in a row with the same elements, a form among them if the
    address says login. Single-page sites draw the form, then the button, a moment after arrival."""
    deadline = time.perf_counter()+seconds
    previous, snap = None, await observe(page)
    while time.perf_counter() < deadline:
        count = len(snap['elements'])
        waiting_for_form = recipes.login_like(snap) and not inputs(snap)
        if previous == count and count and not waiting_for_form:
            break
        previous = count
        await page.wait_for_timeout(350)
        snap = await observe(page)
    return snap


def enabled():
    return os.environ.get('DAN_BROWSER_AUTOLOGIN', '1') != '0' and recipes.enabled()


def inputs(snap):
    return [e for e in snap['elements'] if e['tag'] == 'INPUT' and not e['disabled'] and e['role'] == 'textbox']


def shape(snap):
    """('credentials', id_candidates, password) | ('identifier', [field], None) | ('other', [], None)."""
    fields = inputs(snap)
    passwords = [e for e in fields if e['type'] == 'password']
    if len(passwords) > 1 or (passwords and len([e for e in fields if e['type'] in TEXT_INPUT]) > 3):
        return 'other', [], None   # two password boxes = sign-up or change-password; many text boxes = a registration form
    if passwords:
        before = fields[:fields.index(passwords[0])]
        return 'credentials', [e for e in before if e['type'] in TEXT_INPUT][-3:], passwords[0]
    texts = [e for e in fields if e['type'] in TEXT_INPUT]
    if len(texts) == 1 and recipes.login_like(snap):
        return 'identifier', texts, None   # id first, password on the next page
    return 'other', texts, None


OTHER_METHOD = re.compile(r'google|apple|facebook|line|twitter|microsoft|github|sso|passkey|パスキー|マジックリンク|magic|qr', re.I)


def methods(snap):
    """Buttons on a login page that has no form yet: one of them may lead to id + password."""
    return [e for e in snap['elements'] if e['role'] in {'button', 'link'} and not e['disabled'] and e['name']
            and not OTHER_METHOD.search(e['name']) and len(e['name']) <= 40][:12]


def submitters(snap, after=None):
    """Buttons that could submit the form, nearest after the last filled field first."""
    items = [e for e in snap['elements'] if e['role'] in {'button', 'link'} and not e['disabled']
             and SUBMIT.search(e['name'] or '') and not NOT_SUBMIT.search(e['name'] or '')]
    buttons = [e for e in items if e['role'] == 'button'] or items
    if after is not None:
        order = {e['ref']: i for i, e in enumerate(snap['elements'])}
        later = [e for e in buttons if order.get(e['ref'], 0) > order.get(after['ref'], 0)]
        buttons = later or buttons
    return buttons[:8]


async def choose(decisions, items, question, state):
    """One Jev choice among page elements; None unless it is sure."""
    if len(items) == 1: return items[0]
    if not items or decisions is None: return None
    criteria = {e['ref']: (e['role']+' '+(e['name'] or e['id'] or e['name_attr'] or '(名前なし)'))[:160] for e in items}
    criteria['none'] = 'どれでもない／分からない'
    decision = await decisions.choose(state, {'element': {'type': 'choice', 'instructions': question, 'criteria': criteria}})
    answer = decision.get('answers', {}).get('element', {}) if decision.get('available') else {}
    ref = answer.get('choice')
    if ref in criteria and ref != 'none' and answer.get('confidence', 0) >= BAR['confidence'] \
            and answer.get('probabilities', {}).get(ref, 0) >= BAR['probability']:
        return next(e for e in items if e['ref'] == ref)
    return None


async def saved_account(url):
    """The one saved credential for this host: (credential, None), or (None, why not)."""
    from app.services.credentials_service import get_credentials_service, narrow_url_matches
    user_id = os.environ.get('DAN_USER_ID', '00000000-0000-0000-0000-000000000001')
    matches = narrow_url_matches(await get_credentials_service().find_credentials_by_url(user_id, url))
    if not matches: return None, 'no_saved_credential'
    if len(matches) > 1: return None, 'several_saved_accounts: '+', '.join(str(m.get('service')) for m in matches if m.get('service'))
    return matches[0], None


async def maybe_login(params, result):
    """Called when open_target / click arrived somewhere and nothing remembered was replayed."""
    if not enabled() or params.get('login') is False or running.get() or recipes.replaying.get():
        return result
    if isinstance(result, dict) and result.get('replay'):
        return result   # a replay ran (or stopped half way): the model decides
    from app.tools.browser import get_executor_page
    from app.services.browser_replay import observe
    page = await get_executor_page()
    snap = await observe(page)
    if not recipes.login_like(snap):
        return result   # the usual case: not a login page, one look and out
    snap = await steady(page, observe)
    kind, _, _ = shape(snap)
    if kind == 'other' and not methods(snap):
        return result
    account, why = await saved_account(snap['url'])
    if not account:
        note = ('このサイトのログイン情報は保存されていません（自動ログインは行っていません）。本人に確認するか、パスワード再設定が必要です。' if why == 'no_saved_credential'
                else 'このサイトには複数のアカウントが保存されています（'+why.split(': ', 1)[-1]+'）。どれで入るかを service で指定して fill_credential してください。')
        if isinstance(result, dict) and isinstance(result.get('content'), list):
            result['content'].insert(0, {'type': 'text', 'text': note})
        return result
    return await run(page, snap, account)


async def run(page, snap, account):
    from app.agent.v2.tools import _execute_browser_tool, _get_browser_state, _browser_observation
    from app.services.browser_replay import observe
    from app.services.cancellation import CancellationRegistry
    from app.services import command_job_tools as gate
    from app.services.jev_decisions import Decisions

    started = time.perf_counter()
    job_id = os.environ.get('DAN_COMMAND_JOB_ID')
    user_id = os.environ.get('DAN_USER_ID')
    service, login_url = account.get('service'), snap['url']
    done, reason, detail, jev_calls = [], None, '', 0
    token = running.set(True)

    async def act(action, args, label):
        CancellationRegistry.check_cancelled_raise()
        if action == 'click':
            try: target = await gate.browser_target(args)
            except Exception: raise Handoff('page_changed_before_action')
            if gate.needs_confirmation(target): raise Handoff('sensitive_action_needs_agent')
        if job_id: await gate.guard(job_id, 'browser', {'action': action, **args})
        outcome = await _execute_browser_tool(action, {**args, 'observation': 'dom', 'login': False, 'replay': False})
        if isinstance(outcome, dict) and outcome.get('success') is False:
            raise Handoff(action+'_failed: '+str(outcome.get('error') or '')[:200])
        done.append(label)

    async def settle(previous):
        """Wait until the page is no longer the one the action was taken on."""
        deadline = time.perf_counter()+STEP_WAIT_SECONDS
        current = await observe(page)
        while time.perf_counter() < deadline and current['url'] == previous['url'] and current['password'] == previous['password'] \
                and recipes.landmarks(current) == recipes.landmarks(previous) and not await rejected():
            await page.wait_for_timeout(int(POLL_SECONDS*1000))
            current = await observe(page)
        return await steady(page, observe, 2.5) if current['url'] != previous['url'] else current

    async def text():
        try: return await page.evaluate(PAGE_TEXT)
        except Exception: return ''

    shown = set()   # the lines on the page before the submit
    judge = None     # the Jev client, once opened
    judged = {}      # new lines already classified: the wait loop looks four times a second

    async def lines():
        try: return await page.evaluate(PAGE_LINES)
        except Exception: return []

    async def rejected():
        """What the site wrote after the submit while staying on the form: its own words, whatever the language.
        UTAGE answered 「…に対応するログイン情報が登録されていません」, which no list of error words would have caught."""
        new = [line for line in await lines() if line not in shown and 4 <= len(line) <= 200][:6]
        if new and shown and tuple(new) in judged: return judged[tuple(new)]
        if new and shown:
            # A chat widget or a banner also adds lines after the submit (Lstep: 「お問い合わせはこちらをクリック」).
            options = {str(i): line for i, line in enumerate(new)}
            decision = await judge.choose({'task': 'a login form was just submitted', 'new_lines_on_the_page': new}, {'message': {
                'type': 'choice', 'instructions': 'ログインを送信した直後にページへ新しく現れた行のうち、ログインできなかったこと（IDやパスワードの誤り、ロック、入力の不備）を伝えている行を選ぶ。',
                'criteria': {**options, 'none': 'どの行もログインの失敗を伝えていない（案内・広告・問い合わせ窓口・読み込み中の表示など）。'}}}) if judge else {}
            answer = decision.get('answers', {}).get('message', {}) if decision.get('available') else None
            if answer is not None:
                pick = answer.get('choice')
                judged[tuple(new)] = options[pick] if pick in options and answer.get('probabilities', {}).get(pick, 0) >= .7 else ''
                return judged[tuple(new)]
            worded = [line for line in new if REJECTED.search(line)]   # Jev unreachable: only a line that says so in known words
            return worded[0] if worded else ''
        body = await text()
        found = REJECTED.search(body)
        return body[max(0, found.start()-60):found.end()+80] if found else ''

    try:
        async with Decisions(user_id, max_calls=10) as decisions:
            judge = decisions
            state = {'url': recipes.url_key(snap['url']), 'task': 'log in with the saved account'}
            submitted = False
            chosen = 0
            looks = 0
            coded = False
            for _ in range(MAX_STAGES+8):
                kind, ids, password = shape(snap)
                body = await text()
                until = time.perf_counter()+3   # RunPod shows 「Check your email」 first and draws the code boxes a moment later
                while submitted and CODE_PAGE.search(body) and not inputs(snap) and time.perf_counter() < until:
                    await page.wait_for_timeout(300)
                    snap = await observe(page)
                    kind, ids, password = shape(snap)
                if kind == 'credentials':
                    if submitted:   # the same form again after submitting: the site said no. Never try twice (lockouts).
                        detail = await rejected()
                        raise Handoff('login_rejected')
                    if ids and account.get('id'):
                        field = await choose(decisions, ids, 'ログインID（会員ID・ユーザー名・メールアドレス）を入力する欄を選ぶ。', state)
                        if field is None: raise Handoff('id_field_unclear')
                        await act('fill_credential', {'ref': field['ref'], 'field': 'username', 'url': login_url, 'service': service}, 'id')
                        snap = await observe(page)
                        kind, ids, password = shape(snap)
                        if password is None: raise Handoff('page_changed_before_action')
                    await act('fill_credential', {'ref': password['ref'], 'field': 'password', 'url': login_url, 'service': service}, 'password')
                    try: robot_check = await page.evaluate(CAPTCHA)
                    except Exception: robot_check = False
                    if robot_check:
                        # Lstep keeps its ログイン button disabled until the "I'm not a robot" box is solved. Dan already solves these alone.
                        await act('solve_captcha', {}, 'robot check')
                        until = time.perf_counter()+4   # the page enables its button a moment after the check is accepted
                        while time.perf_counter() < until and not submitters(await observe(page)):
                            await page.wait_for_timeout(300)
                    snap = await observe(page)
                    _, _, password = shape(snap)
                    button = await choose(decisions, submitters(snap, password), 'ログインを実行する（フォームを送信する）ボタンを選ぶ。', state)
                    before = snap
                    shown.clear(); shown.update(await lines())
                    if button is not None: await act('click', {'ref': button['ref']}, 'submit '+json.dumps(button['name'], ensure_ascii=False))
                    elif any(e['role'] == 'button' and e['disabled'] for e in snap['elements']): raise Handoff('submit_button_disabled')   # something on the page is still unmet
                    elif password is not None: await act('keyboard_press', {'key': 'Enter'}, 'submit Enter')
                    else: raise Handoff('submit_unclear')
                    submitted = True
                    snap = await settle(before)
                elif kind == 'identifier' and not submitted and account.get('id'):
                    await act('fill_credential', {'ref': ids[0]['ref'], 'field': 'username', 'url': login_url, 'service': service}, 'id')
                    snap = await observe(page)
                    button = await choose(decisions, submitters(snap, ids[0]), '入力したIDを送って次の画面へ進むボタンを選ぶ。', state)
                    if button is None: raise Handoff('next_unclear')
                    before = snap
                    await act('click', {'ref': button['ref']}, 'next '+json.dumps(button['name'], ensure_ascii=False))
                    snap = await settle(before)
                elif submitted and coded and CODE_PAGE.search(body) and inputs(snap):
                    # RunPod: the code was typed and the site was already moving on, but the code screen was still drawn; a second
                    # wait for a code that would never be sent turned a finished login into a reported failure.
                    before = snap
                    snap = await settle(before)
                    if CODE_PAGE.search(await text()) and inputs(snap): raise Handoff('code_not_accepted')
                elif submitted and CODE_PAGE.search(body) and inputs(snap):
                    fields = [e for e in inputs(snap) if e['type'] in TEXT_INPUT]
                    field = await choose(decisions, fields[:6], '認証コード（ワンタイムパスワード）を入力する欄を選ぶ。', state)
                    if field is None: raise Handoff('code_field_unclear')
                    if account.get('totp_secret'):
                        await act('fill_totp_code', {'ref': field['ref'], 'service': service, 'url': login_url}, 'authenticator code')
                    else:
                        source = 'email' if BY_MAIL.search(body) and not re.search(r'SMS|ショートメッセージ|携帯電話', body, re.I) else 'sms'
                        mailbox = {'email_address': account['id']} if source == 'email' and '@' in str(account.get('id') or '') else {}   # the code goes to the address that logs in
                        await act('wait_for_otp_from_app', {'ref': field['ref'], 'service': service, 'source': source, **mailbox}, 'code by '+source)
                    coded = True
                    snap = await observe(page)
                    button = await choose(decisions, submitters(snap, field), '入力した認証コードを送信するボタンを選ぶ。', state) if inputs(snap) and CODE_PAGE.search(await text()) else None
                    before = snap
                    if button is not None:
                        await act('click', {'ref': button['ref']}, 'submit '+json.dumps(button['name'], ensure_ascii=False))
                        snap = await settle(before)
                    else:
                        snap = await settle(before)   # many sites submit by themselves once the code is complete
                elif submitted and not snap['password'] and not CODE_PAGE.search(body):
                    break   # out of the login page
                elif kind == 'other' and not submitted and chosen < 2 and methods(snap):
                    # The page asks how to sign in before it shows a form.
                    items = methods(snap)
                    criteria = {e['ref']: (e['role']+' '+e['name'])[:120] for e in items}
                    decision = await decisions.choose(state, {'method': {'type': 'choice',
                        'instructions': 'ID（メールアドレス）とパスワードを入力してログインする画面へ進むためのボタンを選ぶ。GoogleやAppleなど他社のアカウント、SSO、メールで届くリンクやコードだけでログインする方法は選ばない。',
                        'criteria': {**criteria, 'none': 'パスワードでのログインへ進むボタンは無い／分からない'}}})
                    answer = decision.get('answers', {}).get('method', {}) if decision.get('available') else {}
                    ref = answer.get('choice')
                    # HeyGen: 「パスワードを使用」 .46 and 「メールアドレスを使用」 .22 — both lead to the password form, so the mass was split.
                    # What matters is that Jev sees A way (none is small); third-party and link-only methods are not among the candidates.
                    probabilities = answer.get('probabilities', {})
                    if ref not in criteria or probabilities.get('none', 1) > .3 or probabilities.get(ref, 0) < .4: raise Handoff('login_method_unclear')
                    before = snap
                    await act('click', {'ref': ref}, 'method '+json.dumps(criteria[ref], ensure_ascii=False))
                    chosen += 1
                    await page.wait_for_timeout(400)
                    snap = await steady(page, observe, 2.5)
                elif looks < 8:
                    # Between two screens a single-page site shows neither (RunPod: the address changes, the text follows). Look again.
                    looks += 1
                    await page.wait_for_timeout(400)
                    snap = await observe(page)
                    continue
                else:
                    raise Handoff('unknown_screen')
                jev_calls = decisions.calls
            else:
                raise Handoff('too_many_stages')
            if snap['password']:
                detail = await rejected()
                raise Handoff('login_rejected' if detail else 'still_on_login_page')
    except Handoff as exc:
        reason = str(exc)
    except Exception as exc:
        logger.warning('browser login stopped', exc_info=True)
        reason = 'execution_'+type(exc).__name__
    finally:
        running.reset(token)
    if reason is None:
        # fish.audio: the login was the last thing done in that session, so the recorder never saw "the next step" that tells it
        # where the login ended, and nothing was remembered. Show it the final page now.
        try:
            path = recipes._run_file(); recorded = recipes._read(path, None)
            if recorded:
                recipes._settle(recorded, await recipes.snapshot(page)); recipes._write(path, recorded)
        except Exception:
            logger.debug('login recording not finalised', exc_info=True)
    elapsed = round((time.perf_counter()-started)*1000, 2)
    record_timing('workflow', 'browser_login', elapsed, 'handoff' if reason else 'verified', {'tool_calls': len(done)})
    final = {}
    if not CancellationRegistry.check_cancelled():
        observation = _browser_observation.set('full')
        try: final = await _get_browser_state(page)
        except Exception: reason = reason or 'final_observation_unavailable'
        finally: _browser_observation.reset(observation)
    summary = {'logged_in': reason is None, 'needs_agent': reason is not None, 'reason': reason, 'site_message': detail[:200],
               'account': service, 'completed_steps': done, 'jev_calls': jev_calls, 'elapsed_ms': elapsed}
    final['login'] = summary
    message = ('Logged in with the saved account; the site left the login page. Do not enter credentials again. '
               'The screen below is where the site went (destination, or a notice to handle); continue with the task. '
               if reason is None else
               'An automatic login was started but stopped ('+reason+'). The steps in completed_steps were ALREADY executed: do not repeat them. '
               + ('The site REJECTED the saved credentials (site_message): do not submit them again — a repeat can lock the account. '
                  'Check whether another saved account fits, whether the site wants a different id form, or start the password reset. ' if reason == 'login_rejected' else '')
               + 'Continue manually from the screen below. ')
    final.setdefault('content', []).insert(0, {'type': 'text', 'text': message+json.dumps(summary, ensure_ascii=False)})
    return final
