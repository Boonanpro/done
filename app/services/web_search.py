"""Web search as one of Dan's own tools, for every part of Dan (owner, 2026-10-03). Chat Dan searched with the Claude
CLI's built-in search and the voice backend with OpenAI's; the job worker (DeepSeek) had none and searched by driving a
browser to a search site and opening results one by one (40-60 s where a search call takes 6-13 s). A capability that
lives with one model's vendor is a gap for the others, so it is a Dan tool here.

Backed by OpenAI's hosted web search (the search model reads the pages and returns the facts with their sources)."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

MODEL = os.environ.get('DAN_WEB_SEARCH_MODEL') or os.environ.get('DAN_VOICE_SEARCH_MODEL') or 'gpt-5.6-terra'

TOOL = {
    'name': 'web_search',
    'description': ('ウェブを検索して、答えに必要な事実を出どころ（URL）付きで受け取る。公開されている情報の調べもの（店・施設・会社・ニュース・'
                    '天気・料金・仕様・手順など）は、ブラウザで検索サイトを開く前にまずこれを使う（1回6〜13秒）。別々のことを調べる時は、'
                    '1回の手で複数呼ぶと並行で動く。ブラウザを使うのは、ログインが要る・サイトの中で操作する（検索窓・絞り込み・予約や在庫の'
                    '最新状況）・見た目で確かめる・検索の答えが足りない時（返ってきた URL を開いて読む）。'),
    'input_schema': {'type': 'object', 'properties': {
        'query': {'type': 'string', 'description': '調べたいこと（自然な文でよい。場所や時期など条件も入れる）'},
    }, 'required': ['query'], 'additionalProperties': False},
}


async def search(query):
    import httpx
    from app.config import settings
    body = {'model': MODEL, 'tools': [{'type': 'web_search'}], 'tool_choice': 'required', 'reasoning': {'effort': 'low'},
            # the search model has no clock: without today's date it answered with another day's figures (2026-09-24)
            'instructions': '今は ' + datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y年%m月%d日 %H:%M（日本時間）') + '。'
                            '質問に答えるのに必要な事実を、日本語で簡潔に書く。数値・日付・時刻・固有名詞はそのまま。',
            'input': query}
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post('https://api.openai.com/v1/responses', json=body, headers={'Authorization': 'Bearer ' + settings.OPENAI_API_KEY})
        data = r.json()
        if r.status_code != 200:
            return {'success': False, 'error': str((data.get('error') or {}).get('message') or r.status_code)[:200]}
        text, sources = [], []
        for out in data.get('output', []):
            if out.get('type') != 'message':
                continue
            for part in out.get('content', []):
                text.append(part.get('text', ''))
                for a in part.get('annotations') or []:
                    if a.get('type') == 'url_citation' and a.get('url') and a['url'] not in [s['url'] for s in sources]:
                        sources.append({'title': a.get('title') or '', 'url': a['url']})
        found = ' '.join(text).strip()[:4000]
        lines = [found] + (['', '出どころ:'] + [f'- {s["title"]} {s["url"]}' for s in sources[:8]] if sources else [])
        return {'success': True, 'output': '\n'.join(lines)}
    except Exception as exc:
        return {'success': False, 'error': f'検索できなかった: {type(exc).__name__}'}


async def tool(params):
    query = str(params.get('query') or '').strip()
    if not query:
        return {'success': False, 'error': 'query が空'}
    return await search(query)
