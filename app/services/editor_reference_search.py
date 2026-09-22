"""Concurrent reference discovery without a production agent or desktop browser."""
import asyncio
import json
import re
import time
import uuid
import httpx
from app.services.editor_presentation import present

_latest = {}


async def search_web(queries):
    """Use search grounding directly; return source evidence, never guessed media."""
    from app.config import settings
    if not isinstance(queries, list) or not 1 <= len(queries) <= 3 or any(not isinstance(q, str) or not q.strip() or len(q) > 250 for q in queries):
        raise ValueError('検索語は1〜3件、各250文字以内で指定してください')
    started = time.perf_counter()
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post('https://generativelanguage.googleapis.com/v1beta/interactions',
            headers={'x-goog-api-key': settings.GOOGLE_GEMINI_API_KEY},
            json={'model':'gemini-3.8-flash', 'tools':[{'type':'google_search'}],
                  'input':'検索担当として、次の検索語に合う実在ページを探してください。最大6件、各候補のタイトル・直接URL・合致点を一言、出典付きで返してください。作品・画像・動画の検索には実物の掲載ページ、制作方法の検索には手順の資料を返します。X、YouTube、作者サイトなど情報源を限定しません。導入、総括、制作案は不要です。検索で分かったことと実物を視聴して確認したことは区別してください。検索語:\n'+'\n'.join(queries)})
    response.raise_for_status()
    grounded_ms=round((time.perf_counter()-started)*1000)
    data = response.json()
    candidates = []
    texts = []
    seen = set()
    for step in data.get('steps', []):
        if step.get('type') != 'model_output':
            continue
        for part in step.get('content', []):
            if part.get('text'):
                texts.append(part['text'])
            for citation in part.get('annotations', []):
                url = citation.get('url', '')
                if citation.get('type') == 'url_citation' and url.startswith('https://') and url not in seen:
                    seen.add(url)
                    candidates.append({'url':url, 'title':citation.get('title', url), 'inspection':'search_only'})
    from urllib.parse import urlparse
    async with httpx.AsyncClient(timeout=8, follow_redirects=False) as client:
        async def expand(item):
            if urlparse(item['url']).hostname != 'vertexaisearch.cloud.google.com':
                return
            try:
                r = await client.get(item['url'])
                direct = r.headers.get('location', '')
                if r.is_redirect and direct.startswith('https://'):
                    item['citation_url'] = item['url']
                    item['url'] = direct
            except httpx.HTTPError:
                pass
        await asyncio.gather(*(expand(item) for item in candidates))
    return {'ok':bool(candidates), 'candidates':candidates, 'summary':'\n'.join(texts),
            'elapsed_ms':round((time.perf_counter()-started)*1000),
            'timings':{'grounded_search_ms':grounded_ms,'redirect_ms':round((time.perf_counter()-started)*1000)-grounded_ms},
            'note':'出典付き検索結果。Webページは動画ファイルではありません。present_referencesのsourceで公開URLの取得・表示をまとめて行えます。中身を先に調べたい時はresolve_referenceを使えます。'}

def _text(value):
    if isinstance(value, str): return value
    if not isinstance(value, dict): return ''
    return value.get('simpleText') or value.get('content') or ''.join(r.get('text','') for r in value.get('runs',[]))

def parse_results(html):
    match=re.search(r'(?:var ytInitialData|window\["ytInitialData"\])\s*=\s*',html)
    if not match: raise ValueError('検索結果を取得できませんでした')
    data=json.JSONDecoder().raw_decode(html[match.end():])[0]
    results=[];seen=set()
    def add(vid,title,short=False):
        if re.fullmatch(r'[\w-]{11}',str(vid or '')) and title and vid not in seen:
            seen.add(vid);results.append({'title':title,'url':f'https://www.youtube.com/{"shorts/" if short else "watch?v="}{vid}',
                'kind':'video','note':'検索で見つかった参考候補です。再生して雰囲気を比べられます。'})
    def walk(node):
        if isinstance(node,list):
            for v in node:walk(v)
        elif isinstance(node,dict):
            if 'videoRenderer' in node:
                v=node['videoRenderer'];add(v.get('videoId'),_text(v.get('title')));return
            if 'reelItemRenderer' in node:
                v=node['reelItemRenderer'];add(v.get('videoId'),_text(v.get('headline')),True);return
            if 'shortsLockupViewModel' in node:
                v=node['shortsLockupViewModel'];cmd=v.get('onTap',{}).get('innertubeCommand',{})
                title=_text(v.get('overlayMetadata',{}).get('primaryText'))
                if not title:title=v.get('accessibilityText','').split(',')[0]
                add(cmd.get('reelWatchEndpoint',{}).get('videoId'),title,True);return
            for v in node.values():walk(v)
    walk(data)
    return results[:12]

async def search(room,content_id,queries,is_current=lambda:True):
    if not isinstance(queries,list) or not 1<=len(queries)<=3 or any(not isinstance(q,str) or not q.strip() or len(q)>250 for q in queries):
        raise ValueError('検索語は1〜3件、各250文字以内で指定してください')
    key=(room,content_id);request_id=uuid.uuid4().hex;_latest[key]=request_id
    started=time.perf_counter();first_ms=None;items=[];seen=set();errors=[];presentation=None
    async with httpx.AsyncClient(timeout=8,follow_redirects=True) as client:
        async def fetch(q):
            try:
                r=await client.get('https://www.youtube.com/results',params={'search_query':q})
                r.raise_for_status();return parse_results(r.text)
            except (httpx.HTTPError,ValueError) as e:
                errors.append(type(e).__name__);return []
        tasks=[asyncio.create_task(fetch(q)) for q in queries]
        try:
            for task in asyncio.as_completed(tasks):
                batch=await task
                if _latest.get(key)!=request_id or not is_current():return {'ok':False,'canceled':True}
                # Give different searches room in the first comparison.
                for candidate in batch[:4]:
                    if candidate['url'] not in seen:
                        seen.add(candidate['url']);items.append(candidate)
                if items:
                    if first_ms is None:first_ms=round((time.perf_counter()-started)*1000)
        finally:
            for task in tasks:
                if not task.done():task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            if _latest.get(key)==request_id:_latest.pop(key,None)
    elapsed=round((time.perf_counter()-started)*1000)
    return {'ok':bool(items),'candidates':items[:12],'first_results_ms':first_ms,'elapsed_ms':elapsed,
            'queries':queries,'errors':errors,'note':'検索候補です。まだ表示していません。タイトルと目的を照合して適切な候補を選びpresent_referencesで提示してください。映像本編は未確認です。' if items else '候補が見つかりませんでした。検索語を変えるか別の情報源を調べられます。'}
