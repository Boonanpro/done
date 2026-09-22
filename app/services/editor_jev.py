"""Optional fast judgments. Credentials stay server-side; failures preserve Astra's path."""
import asyncio
import math
import logging
import time
import weakref
import httpx

MODEL = 'jev-latest'
SERVICE = 'typesafe_jev'
_keys = {}
_clients = weakref.WeakKeyDictionary()


def client():
    loop=asyncio.get_running_loop()
    existing=_clients.get(loop)
    if existing is None or existing.is_closed:
        existing=httpx.AsyncClient(limits=httpx.Limits(max_connections=8,max_keepalive_connections=4,keepalive_expiry=60))
        _clients[loop]=existing
    return existing

async def api_key(user_id):
    cached = _keys.get(user_id)
    if cached and time.monotonic() - cached[0] < 30:
        return cached[1]
    from app.services.credentials_service import get_credentials_service
    # The credential service uses synchronous database IO internally.
    def read():
        return asyncio.run(get_credentials_service().get_credential(user_id, SERVICE))
    value = await asyncio.to_thread(read)
    key = value.get('password') if value and value.get('credential_type') == 'api_key' else None
    _keys[user_id] = (time.monotonic(), key)
    return key

async def judge(user_id, state, questions, *, timeout=1.8):
    statuses=[]
    async def request():
        key = await api_key(user_id)
        if not key:
            return {'available': False, 'reason': 'not_configured'}
        for attempt in range(2):
            remaining=timeout-(time.perf_counter()-started)
            if remaining<=0:raise asyncio.TimeoutError()
            r = await client().post('https://api.typesafe.ai/v1/systemone',timeout=remaining,
                headers={'Authorization': 'Bearer ' + key},
                json={'model': MODEL, 'state': state, 'questions': questions})
            statuses.append(r.status_code)
            if attempt or r.status_code not in (500,502,503,504,529):break
            try:delay=max(.08,float(r.headers.get('retry-after','.08')))
            except ValueError:break
            if delay>=timeout-(time.perf_counter()-started):break
            await asyncio.sleep(delay)
        r.raise_for_status()
        data = r.json()
        if not isinstance(data.get('answers'), dict):
            raise ValueError('Invalid answers')
        return {'available': True, 'answers': data['answers'], 'usage': data.get('usage', {})}
    started = time.perf_counter()
    try:
        result = await asyncio.wait_for(request(), timeout=timeout+.4)
    except Exception as exc:
        status=exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else None
        logging.getLogger(__name__).info('Jev unavailable: %s status=%s', type(exc).__name__,status)
        result = {'available': False, 'reason': 'unavailable','error_type':type(exc).__name__,'http_status':status}
    result['elapsed_ms'] = round((time.perf_counter() - started) * 1000)
    result['http_statuses']=statuses
    return result

def confident(answer, allowed):
    if not isinstance(answer, dict):
        return None
    confidence = answer.get('confidence')
    if not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or confidence < .9:
        return None
    return answer.get('choice') if answer.get('choice') in allowed else None

async def presentation_action(user_id, dialogue, items, focus=None):
    if not items:
        return {'handled': False, 'reason': 'no_presentations'}
    choices = {i['id']: i['title'] for i in items}
    result = await judge(user_id, {'conversation': dialogue, 'displayed_items': items, 'pointer_focus': focus}, {
        'action': {'type': 'choice', 'instructions':
            'ユーザーの最後の発言全体が、提示済み見本の表示・再生・一時停止だけを依頼しているか。'
            '会話の文脈を読む。否定、仮定、質問、別の依頼や制作・変更・検索を含む場合はother。'
            'タイムラインの操作はother。候補が表示されているだけでは操作依頼ではない。',
            'criteria': {'reveal': '既存の見本をもう一度見せる', 'play': '既存の見本を再生する',
                         'pause': '既存の見本の再生を一時停止する', 'other': 'それ以外・不明'}},
        'target': {'type': 'choice', 'instructions':
            '最後の依頼が指す提示済み見本を会話から選ぶ。番号は表示順を参照。ポインターは補助情報で、'
            '必ずしも発言の対象ではない。複数対象や曖昧な場合はnone。',
            'criteria': {**choices, 'none': '対象不明・複数・該当なし'}}})
    answer = result.get('answers', {})
    action = confident(answer.get('action'), {'reveal', 'play', 'pause'})
    target = confident(answer.get('target'), choices)
    return {'handled': bool(action and target), 'action': action, 'item_id': target,
            'elapsed_ms': result['elapsed_ms'], 'reason': result.get('reason'), 'model': MODEL,
            'usage': result.get('usage', {})}

async def rank_candidates(user_id, queries, candidates):
    """Recommend an ordering only. Keep all evidence and Astra's final judgment."""
    if len(candidates) < 2:
        return None
    result = await judge(user_id, {'request': queries, 'candidates': candidates[:24]}, {
        str(n): {'type': 'score', 'instructions':
            f'候補candidates[{n}]はrequestにどの程度合うか。記載の情報だけで判断。'
            '検索タイトルや説明は映像本編の確認ではない。',
            'criteria': ['不適合', '情報不足', '部分的に合う', '強く合う']}
        for n in range(min(len(candidates), 24))})
    scores = {}
    for key, answer in result.get('answers', {}).items():
        value = answer.get('score') if isinstance(answer, dict) else None
        if key.isdigit() and int(key) < len(candidates) and isinstance(value, (int, float)) and math.isfinite(value) and 0 <= value <= 3:
            scores[int(key)] = value
    return {'order': sorted(scores, key=lambda n: -scores[n]), 'elapsed_ms': result['elapsed_ms'],
            'model': MODEL, 'usage': result.get('usage', {}),
            'note': '検索説明に基づく候補番号の推薦順。映像本編の検品ではなく、全候補から担当が判断する。'} if scores else None
