"""Web search as one of Dan's own tools, for every part of Dan (owner, 2026-10-03). Chat Dan searched with the Claude
CLI's built-in search and the voice backend with OpenAI's; the job worker (DeepSeek) had none and searched by driving a
browser to a search site and opening results one by one (40-60 s where a search call takes 6-13 s). A capability that
lives with one model's vendor is a gap for the others, so it is a Dan tool here.

One search for chat, jobs and the voice backend (the voice backend kept its own copy until 2026-10-23), on DeepSeek alone:
DeepSeek's Search API returns a ranked list (a long summary and, on request, the page text per result) but no answer, so
deepseek-flash first turns the question into one or two queries with the dates written out (「明日」「今週末」 found other
days' pages and no weekend events), both run at once, and deepseek-flash answers from the merged list. Measured on 20
Japanese questions (docs/current/search-deepseek-20261023.md): as right as OpenAI's hosted search (17.5 of 18 gradable
questions each), median 3.1 s against 5.0 s (max 3.6 s against 18 s).
OpenAI's search stayed behind it as a fallback until 2026-10-25, when the owner asked for one engine per job: a second
engine doubled the paths (engine switch, cooldown, a second time limit) for the rare DeepSeek failure, and a failed
search is answered by saying so or by the browser.

search_list is the DeepSeek Search call itself, given to the job worker (a model that reads a list itself needs no
answering step). Pages are read by read_url (Jina Reader) everywhere: DeepSeek's Fetch was about twice as slow and lost
most of the text on a third of 12 pages (2026-10-25)."""
import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

DEEPSEEK = 'https://api.deepseek.com'
ANSWER_MODEL = 'deepseek-flash'

TOOL = {
    'name': 'web_search',
    'description': ('ウェブを検索して、答えに必要な事実を出どころ（URL）付きで受け取る。公開されている情報の調べもの（店・施設・会社・ニュース・'
                    '天気・料金・仕様・手順など）は、ブラウザで検索サイトを開く前にまずこれを使う（1回3〜5秒）。別々のことを調べる時は、'
                    '1回の手で複数呼ぶと並行で動く。ブラウザを使うのは、ログインが要る・サイトの中で操作する（検索窓・絞り込み・予約や在庫の'
                    '最新状況）・見た目で確かめる・検索の答えが足りない時（返ってきた URL を開いて読む）。'),
    'input_schema': {'type': 'object', 'properties': {
        'query': {'type': 'string', 'description': '調べたいこと（自然な文でよい。場所や時期など条件も入れる）'},
    }, 'required': ['query'], 'additionalProperties': False},
}


def _now():
    return datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y年%m月%d日 %H:%M（日本時間）')


_env_cache = [0.0, {}]


def _env(key):
    """A value from .env, re-read at most every 10 s (Core's environment does not carry DeepSeek's key, and the engine
    switch takes effect without a restart)."""
    if time.monotonic() > _env_cache[0]:
        from dotenv import dotenv_values
        _env_cache[:] = [time.monotonic() + 10, dotenv_values(Path(__file__).resolve().parents[2] / '.env')]
    return os.environ.get(key) or _env_cache[1].get(key) or ''


def _ds_headers():
    key = _env('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY が無い')
    return {'Authorization': 'Bearer ' + key}


async def search_list(client, query, count=8, content=False, question=None):
    """DeepSeek Search: the ranked results (title, url, site_name, date, summary, content)."""
    body = {'query': query[:128], 'count': count, 'need_content': content}
    if question:
        body['ori_question'] = question[:128]
    r = await client.post(DEEPSEEK + '/v1/tools/search', json=body, headers=_ds_headers(), timeout=20)
    if r.status_code != 200:
        raise RuntimeError(f'DeepSeek 検索 {r.status_code}: ' + str((r.json().get('error') or {}).get('message') if r.headers.get('content-type', '').startswith('application/json') else '')[:160])
    return r.json().get('results') or []


async def _flash(client, system, user, max_tokens):
    r = await client.post(DEEPSEEK + '/chat/completions', headers=_ds_headers(), timeout=30,
                          json={'model': ANSWER_MODEL, 'thinking': {'type': 'disabled'}, 'max_tokens': max_tokens,
                                'response_format': {'type': 'json_object'},
                                'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': user}]})
    r.raise_for_status()
    return json.loads(r.json()['choices'][0]['message']['content'] or '{}')


QUERIES = ('今は {now}。ウェブ検索に投げる検索語を作る係です。質問から、検索エンジンに入れる日本語の検索語を1〜2個作る。\n'
           '- 「明日」「今週末」「今日」などは具体的な日付（例: 10月24日）に直して入れる。\n'
           '- 2個目は言い換えか、公式サイトに当たりやすい語にする。各64字以内。\n'
           '- JSON で返す: {{"queries": ["...", "..."]}}')

ANSWER = ('今は {now}。あなたはウェブ検索の結果を読んで、質問への答えをまとめる係です。\n'
          '- 結果に書かれている事実だけを使い、日本語で簡潔に書く（3〜6行）。数値・日付・時刻・固有名詞はそのまま。\n'
          '- 天気・株価・為替・ニュースなど日付で変わる情報は、今日の日付に合う物だけを使う。各結果の日付と本文中の日付を見て、別の日の数字を答えにしない。合う物が無ければ「見つからなかった」と書く。\n'
          '- 結果どうしで食い違う時は、公式・新しい方を取り、食い違いがあると一言添える。\n'
          '- 金額は日本の利用者向けの表記（円、または公式の米ドル表記）を先に書く。\n'
          '- JSON で返す: {{"answer": "答えの文", "sources": [使った結果の番号]}}')


async def queries(client, question):
    """One or two search queries with relative dates written out (deepseek-flash, about 0.7 s)."""
    try:
        out = await _flash(client, QUERIES.format(now=_now()), question, 120)
        found = [q.strip() for q in (out.get('queries') or []) if isinstance(q, str) and q.strip()][:2]
        return found or [question]
    except Exception:
        return [question]


async def _deepseek(question):
    import httpx
    async with httpx.AsyncClient() as client:
        qs = await queries(client, question)
        lists = await asyncio.gather(*[search_list(client, q, 8, True, question) for q in qs], return_exceptions=True)
        if all(isinstance(x, Exception) for x in lists):
            raise lists[0]
        lists = [x for x in lists if not isinstance(x, Exception)]
        seen, results = set(), []
        for i in range(max(map(len, lists), default=0)):   # interleave the queries' lists, best first
            for rows in lists:
                if i < len(rows) and rows[i].get('url') and rows[i]['url'] not in seen:
                    seen.add(rows[i].get('url'))
                    results.append(rows[i])
        results = results[:12]
        if not results:
            return {'answer': '', 'sources': []}
        blocks = []
        for i, r in enumerate(results, 1):
            text = ('（ページ本文）\n' + r['content'][:3500]) if i <= 4 and r.get('content') else (r.get('summary') or r.get('snippet') or '')
            blocks.append(f'[{i}] {r.get("title") or ""} ({r.get("site_name") or ""}) 日付:{r.get("date") or "不明"}\nURL: {r.get("url")}\n{text}')
        out = await _flash(client, ANSWER.format(now=_now()), '質問: ' + question + '\n\n検索結果:\n' + '\n\n'.join(blocks), 700)
        used = [results[i - 1] for i in out.get('sources') or [] if isinstance(i, int) and 0 < i <= len(results)]
        return {'answer': str(out.get('answer') or '').strip(),
                'sources': [{'title': r.get('site_name') or r.get('title') or '', 'url': r['url']} for r in used]}


SECONDS = 15   # DeepSeek's whole search (queries, search, answer) takes about 3 s; a call never waits longer than this


async def find(query):
    """The answer to a question from the web: {'success', 'answer', 'sources': [{title, url}], 'seconds'} or
    {'success': False, 'error'}. Bounded (2026-10-24 review): DeepSeek's own waits add up to 80 s, which kept a call
    silent on a slow day."""
    started = time.perf_counter()
    try:
        got = await asyncio.wait_for(_deepseek(query), SECONDS)
    except asyncio.TimeoutError:
        return {'success': False, 'error': f'検索できなかった（{SECONDS}秒で答えが返らなかった）'}
    except Exception as exc:
        return {'success': False, 'error': '検索できなかった（' + (str(exc)[:160] or type(exc).__name__) + '）'}
    if not got['answer']:
        return {'success': False, 'error': '検索できなかった（答えが見つからなかった）'}
    return {'success': True, **got, 'seconds': round(time.perf_counter() - started, 2)}


async def search(query):
    found = await find(query)
    if not found['success']:
        return {'success': False, 'error': found['error']}
    lines = [found['answer']] + (['', '出どころ:'] + [f'- {s["title"]} {s["url"]}' for s in found['sources'][:8]] if found['sources'] else [])
    return {'success': True, 'output': '\n'.join(lines)}


async def tool(params):
    query = str(params.get('query') or '').strip()
    if not query:
        return {'success': False, 'error': 'query が空'}
    return await search(query)
