"""Job MCP boundaries: shared progress, pause, and one-use confirmation grants."""
import asyncio
import hashlib
import json
import os
import re
import uuid
from urllib.parse import urlsplit
from app.services import command_job_state as state

TOOLS = [
    {'name':'job_confirmation','description':'不可逆操作の確定内容を本人へ提示する。確認待ちは即座に返るので実行せず返事を待つ。実行予定の道具と引数を指定。',
     'input_schema':{'type':'object','properties':{'summary':{'type':'string'},'tool':{'type':'string'},'arguments':{'type':'object'}},
                     'required':['summary','tool','arguments']}},
]

class ConfirmationPending(RuntimeError):
    """A durable pause, not a long-running browser call or a failed job."""

def fingerprint(name, arguments, page=''):
    return hashlib.sha256(json.dumps([name,arguments,page],sort_keys=True,ensure_ascii=False).encode()).hexdigest()

async def available(job_id):
    while True:
        s = state.read(job_id)
        if not s or s['state'] in state.TERMINAL: raise RuntimeError('作業は停止済みです')
        if s['state']=='awaiting_confirmation':
            raise ConfirmationPending('本人への確認待ちです。操作は未実行です。確認内容は保存済みなので、このターンを終えて返事を待ってください。状況の読み取りはできます。')
        if s['state'] not in {'paused','awaiting_confirmation'} and s['applied_revision'] >= s['revision']:
            return s
        await asyncio.sleep(.1)

async def propose(job_id, summary, digest):
    initial = await available(job_id)
    proposal_id = str(uuid.uuid4())
    def prepare(s):
        if s['state'] != initial['state'] or s['revision'] != initial['revision']:
            raise RuntimeError('追加指示または停止を受け付けました。新しい状態を確認してください。')
        s.pop('approved',None)
        s['confirmation'] = {'id':proposal_id,'summary':summary[:3000],'fingerprint':digest,'revision':s['revision'],'created_at':state.now()}
        s['state'] = 'awaiting_confirmation'
        state.event(s,'confirmation',summary[:3000])
    state.change(job_id,prepare)
    raise ConfirmationPending('確認内容を本人へ提示しました。操作は未実行です。このターンを終えて返事を待ってください。承認後に同じ作業を再開します。')

def consume(job_id, digest):
    ok = False
    def take(s):
        nonlocal ok
        p = s.get('confirmation') or {}
        if (s['state']=='running' and s.get('approved') == p.get('id') and p.get('id')
            and p.get('fingerprint') == digest and p.get('revision') == s['revision']
            and s['applied_revision'] >= s['revision']):
            ok=True
            s.pop('approved',None); s.pop('confirmation',None)
            s['authorized_transaction_revision'] = s['revision']
    state.change(job_id,take)
    return ok

async def browser_target(arguments):
    from app.tools.browser import get_executor_page
    page = await get_executor_page()
    data = json.dumps({'ref':str(arguments.get('ref','')).lstrip('@'),'x':arguments.get('x'),'y':arguments.get('y')})
    return await page.evaluate('''(() => {const a='''+data+''';
      const sel='[data-dan-ref="'+CSS.escape(a.ref)+'"]';
      const e=a.ref?(window.__danDeep?window.__danDeep(sel)[0]:document.querySelector(sel)):
        (a.x!=null?document.elementFromPoint(a.x,a.y):document.activeElement);
      const t=e?.closest('button,a,input,[role="button"]')||e;
      return {url:location.href,label:(t?.innerText||t?.value||t?.getAttribute('aria-label')||'').trim(),
        type:t?.getAttribute('type'),onclick:t?.getAttribute('onclick'),body:document.body.innerText.slice(0,5000)};})()''')

READ_TOOLS = {'read_file','read_url','check_skill','get_personal_info','remember_personal_info',
              'get_credentials','save_credentials','get_current_time','command_center','write_file','edit_file',
              'save_totp_secret','attach_image','schedule_followup','watch','split_to_new_room',
              'studio_record','studio_encode','studio_probe','studio_extract_frame','studio_evaluate',
              'lookup','wait_until','get_location'}
READ_ACTIONS = {'open','open_target','screenshot','scroll','get_state','get_tabs','switch_tab','wait_for',
                'hold','release','session_status','fill_credential','fill_totp_code','wait_for_otp_from_app',
                'solve_captcha','type','fill_form','select','close','content','back','reload','hover',
                'wait_for_link_from_app','find','read'}
SENSITIVE = re.compile(r'購入|注文.*確定|予約.*確定|予約する|決済|支払|送信|投稿|公開|削除|払戻|取り消|取消|確定|\b(pay|purchase|place order|book now|send|publish|delete|confirm)\b', re.I)

def needs_confirmation(target):
    """Distinguish entering a workflow and own-account authentication from committing it."""
    label = ' '.join(target.get('label','').split())
    body = target.get('body','')
    # Smart EX's observed reservation-list action opens the refund review.
    # Bind the exception to the real origin, workflow and handler, never to
    # the word "refund" alone. The subsequent confirmation remains guarded.
    url=urlsplit(target.get('url',''))
    if (url.scheme=='https' and url.hostname in {'shinkansen2.jr-central.co.jp','shinkansen1.jr-central.co.jp'}
        and url.path=='/RSV_P/p74/ClientService' and label=='払戻'
        and re.search(r'cfEXPY_doAction\([\"\']RSWP230AIDP004[\"\']\)',target.get('onclick') or '')
        and re.search(r'(?m)^予約一覧\s*$',body)):
        return False
    # Compound menu entries describe available workflows, not an execution.
    if re.fullmatch(r'予約確認\s*[/／]\s*変更\s*[/／]\s*払戻(?:\s*予約件数\s*\d+件)?',label):
        return False
    if re.fullmatch(r'(?:予約|購入|注文|送信|投稿|支払|払戻)(?:履歴|一覧|詳細|状況|明細|照会)(?:を(?:見る|開く|確認))?',label):
        return False
    if re.fullmatch(r'(?:予約|購入|注文|支払|払戻)内容の確認(?:画面)?に進む',label):
        return False
    # Code delivery to the account's registered destination is a login step.
    # Payment/3DS authentication stays protected until the transaction is approved.
    auth = re.search(r'ワンタイムパスワード|認証コード|one.time (?:password|code)|verification code',body,re.I)
    transaction = re.search(r'決済|支払|購入を確定|注文を確定|3Dセキュア|SafeKey|payment|purchase',body,re.I)
    if auth and not transaction and re.fullmatch(r'(?:SMS|メール|コード|認証コード)(?:を)?(?:再)?送信|(?:コードを)?再送(?:信)?|(?:OK\s*)?次へ|認証する|verify|send code',label,re.I):
        return False
    if SENSITIVE.search(label): return True
    if not label: return True
    # Ordinary navigation and input submission don't imply a financial or
    # external-message commitment simply because the page contains a price.
    return False

async def guard(job_id, name, arguments):
    """Nothing is held for approval here any more (owner's decision 2026-09-22): a voice-delegated job has the same authority
    as chat Dan. Like chat Dan, the worker asks in words before an irreversible commitment (the rule in its instructions) and
    the owner's answer reaches it as a follow-up. Only the owner's own pause still holds a job."""
    await available(job_id)
    return

def redacted(value):
    if isinstance(value, dict):
        return {k:('[非表示]' if re.search(r'password|secret|token|credential|api.?key|card.?number|cvv',k,re.I)
                   else redacted(v)) for k,v in value.items()}
    if isinstance(value,list): return [redacted(v) for v in value]
    return value

async def special(job_id, name, arguments):
    if name == 'job_progress':
        state.publish(job_id,'progress',str(arguments.get('text','')))
        return {'published':True}
    if name == 'job_confirmation':
        # Browser confirmations are bound to the observed page at the actual
        # action boundary, so the agent cannot authorize a different checkout.
        if arguments['tool']=='browser':
            state.publish(job_id,'progress',arguments['summary'])
            return {'next':'指定した通常のブラウザ操作を呼んでください。実行直前に実画面の内容で本人への確認待ちになります。'}
        await propose(job_id,arguments['summary'],fingerprint(arguments['tool'],arguments['arguments']))
        return {'approved':True}
