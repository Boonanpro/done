"""Where a request made on a call goes, chosen by Jev from a fixed list (2026-11-05, the owner's 「進めて」).

Why: in the owner's call of 2026-11-05 0:59 (10 min 49 s) the speech model handed each request to a backend model
(gpt-6-luna, Responses delegation) that took 3-6 s a round only to pick a tool, and picked the wrong one: checking the
free slots of two salons on their booking sites went to the short web lookup, which could not do it and said 「確認できな
かった」 three times; from 1:04 to 1:09 nothing ran at all. The same request in the chat took chat Dan 1 min 54 s.
「今どういう状況？」 took a 6 s round to read a job file and was answered twice (the speech model's own 「確認してる」, then
the backend's 「まだ確認できてない」).

So the call uses client delegation (live-delegation: the application answers) and this module answers it:
- Jev chooses where the request goes from options written by where and with what the work is done (ROUTES), plus one
  「止める」 and one 「変える」 option for each piece of work running in the call. About 0.15 s.
- The status of the call's work is answered here from the job files and the lookups at once (status_text).
- Reading the web, a map, saved information or past records goes to the background lookup (voice_lookup).
- Work on sites, apps, Dan's artifacts or Dan itself goes to chat Dan (a parallel job of the room, engine 'make'), with
  the call's transcript, so chat Dan reads the conditions itself and nobody rewrites them.
- Messages, documents and pictures on the stage (writing and approving), and anything Jev is unsure of, go to the earlier
  backend: gpt-6-luna with the call's tools, run here (luna_answer).
The answer to a delegation goes back as commentary with its id before the automatic acknowledgement (ACK_DELAY_MS), so
the speech model says one thing, not an acknowledgement and then the answer.

Switch: DAN_VOICE_ROUTER=0 returns to the Responses delegation. Logged as metadata only (route, probability, times).
"""
import asyncio
import json
import os
import re
import time

ACK_DELAY_MS = 800        # the longest wait the API allows before it asks the speech model for an acknowledgement itself
SETTLE_S = .35            # the owner's last words may still be arriving when the delegation is created
SETTLE_MAX_S = 1.2
CONFIDENT = .6            # below this, the request goes to luna_answer
JEV_TIMEOUT_S = 1.5
LUNA_ROUNDS = 8
LUNA_SECONDS = 90
TRANSCRIPT = '\n\n通話のここまでの文字起こし'   # the job's task head (the owner's words) is what the room's chat shows

ROUTES = {
    'status': '今動いている作業や調べものの様子・進み具合・結果を聞いている（「今どう？」「まだ？」「どうなった？」「何してる？」「どこまでできた？」）。新しい頼みは無い。',
    'calendar': '本人のカレンダーの予定を聞いている（今日・明日・今週・ある日の予定、空いている日）。',
    'lookup': 'ウェブ・地図・ニュース・天気・店・商品・値段・営業時間・行き方・乗り換え・病気や体の症状などを調べて答える質問や候補探し。'
              '本人について知っているか（保存した住所・番号・好きな食べ物などの好み）や、ダンとの過去の会話・作業の記録を思い出して答える質問もここ。予約サイトやログインが要るページの中を見る必要は無い。',
    'show': 'この会話に出たページや、本人の成果物（〜室・サイトなど作ってあるもの）を画面に出して・見せて・開いてと頼んでいる。探すところからなら lookup。',
    'site': 'サイトや本人のアカウントの中で確かめる・手続きする: 予約サイトの空き状況・予約・申し込み・注文・請求書の支払い・振込・解約、'
            'Googleドキュメントやドライブ・メール・SNS・会員ページなど、ログインが要る所の中を探す・見る。',
    'app': 'スマホやパソコンのアプリ・端末の設定を操作する（LINE・インスタのDMを開く・送る、スマホやパソコンの設定、画面が消える・スリープなど端末の動き）。',
    'make': 'ダンの成果物（ページ・サイト・LP・動画・資料・プログラム）を作る・直す・続ける、時間のかかる制作や調べた結果のまとめ。',
    'document': '本人の成果物の中の文書（X運用室の記事や投稿、台本室の台本）を書く・直す・開いて見せる・反映する・投稿する。画面でその成果物を開いて一緒に直す。',
    'dan': 'ダン自身を直す・変える: ダンの通話や通話の画面・チャットの見え方、ダンの設定・動き方・話し方、ダンにつないだカレンダーやアカウントの扱い（つなぐ・外す・表示しない）。',
    'message': '人へのメッセージやメールの下書きを作る・直す、画面に出ている下書きや画像を直す、送信の承認や取り消し（「送って」「いいよ」「やめて」）、'
               '画像を作る、話を図や表にする、画面を上下に送る。',
    'rooms': '別の部屋（〜室・別のチャット）で動いている作業やテストの様子を聞く・止める。',
    'end': 'この通話（電話）そのものを終える（「切って」「通話を終わります」「また後で」「忙しいから切って」）。作業やテストを止める話は end ではない。',
    'other': '相談・雑談・考えや意見を聞きたい、ダンのできることや自己紹介、上のどれにも当てはまらない、いくつかの頼みが混ざっている、判断に迷う。',
}
TO_CHAT_DAN = ('site', 'app', 'make', 'dan')
ASK = ('通話で本人がダンに頼んだこと・聞いたことの行き先を1つ選ぶ。conversation の最後の本人の言葉が今の頼みで、それより前は文脈。'
       '何の話かではなく、どこで・何を使ってやるかで選ぶ（美容院もレストランも、予約サイトで空きを見るなら site）。')
WORK = {'status': '「{label}」の様子・進み具合・結果・番号などを聞いている（「まだ？」「どう？」「承認番号は？」）。',
        'stop': '「{label}」を止める・取り消す・もういい・中止してと言っている。',
        'change': '「{label}」への訂正・条件の追加・やり方の指示（どこで見るか・どのページ・別の候補・画面に出して・もう一度やって）。',
        'new': '「{label}」とは別の新しい頼みや話。'}
CALENDAR = {'today': '今日の予定', 'tomorrow': '明日の予定', 'week': '今日から7日間の予定',
            'other': 'それ以外の日・期間、または日が分からない'}
FILLERS = re.compile(r'^(?:えっと|えーと|えー|あの|あのー|あー|なんか|ちょっと|で|じゃあ|うん|まあ|そう|ねえ|おい|ダン)[、,。\s]*')


def enabled():
    from app.services import voice_responses
    return os.environ.get('DAN_VOICE_ROUTER', '1') != '0' and voice_responses.background()


def session_delegation():
    return {'type': 'client', 'acknowledgement_delay_ms': ACK_DELAY_MS}


def label_of(text, limit=24):
    """A short name for the request, from the owner's words (said back in 「…」 by the speech model)."""
    text = ' '.join(str(text or '').split())
    for _ in range(4):
        text = FILLERS.sub('', text)
    text = re.split(r'(?<=[。？！?!])', text)[0].strip('、。 ')
    return (text[:limit] + '…') if len(text) > limit else text


def questions(running, targets):
    """The route, the calendar span, the page to show, and for each running piece of work (newest four) what the owner's
    words do to it. Asked as one more question per work: as route options, corrections such as 「ホットペッパーで確認するんだって」
    went to a new site job, and 「でもこれ四十キロじゃん」 to a lookup (scripts/voice_route_eval.py, 38 of 50 at first)."""
    out = {'route': {'type': 'choice', 'criteria': dict(ROUTES), 'instructions': ASK},
           'calendar': {'type': 'choice', 'criteria': CALENDAR, 'instructions': '予定を聞いている時、どの期間か。'}}
    for i, work in enumerate(running[-4:]):
        out[f'work_{i}'] = {'type': 'choice', 'criteria': {k: v.format(label=work['label']) for k, v in WORK.items()},
                            'instructions': f'最後の本人の言葉が、今動いている「{work["label"]}」について何を言っているか。'}
    if targets:
        out['target'] = {'type': 'choice', 'criteria': {**targets, 'none': '上のどれでもない・分からない'},
                         'instructions': '画面に出してと頼んだのは、どのページや成果物か。'}
    return out


def decide(answers, running):
    """(route, probability) from Jev's answers: what the words do to a running work first, then the route."""
    best = None
    for i, work in enumerate(running[-4:]):
        what, p = chosen(answers, f'work_{i}')
        if what in ('stop', 'change') and p >= CONFIDENT and (best is None or p > best[1]):
            best = (f'{what}:{work["kind"]}:{work["id"]}', p)
    if best is not None:
        return best
    route, probability = chosen(answers, 'route')
    asking = [chosen(answers, f'work_{i}') for i in range(len(running[-4:]))]
    if any(what == 'status' and p >= CONFIDENT for what, p in asking) and route not in ('end',):
        return 'status', max(p for what, p in asking if what == 'status')
    return (route if probability >= CONFIDENT else 'other'), probability


def chosen(answers, name):
    answer = (answers or {}).get(name) or {}
    choice = answer.get('choice')
    return choice, float((answer.get('probabilities') or {}).get(choice, 0) or 0)


def turns_text(turns, limit=12000):
    text = chr(10).join(('本人' if t['role'] == 'user' else 'ダン') + ': ' + str(t.get('text') or '').strip() for t in turns if str(t.get('text') or '').strip())
    return text[-limit:]


class Router:
    """The delegations of one call (voice_sideband creates it when this server owns the call)."""
    def __init__(self, session_id, user_id, room_id, dialogue, send, record, spoke, backend=None, stage=None, end_call=None):
        self.session_id, self.user_id, self.room_id = session_id, user_id, room_id
        self.dialogue, self.send, self.record, self.spoke = dialogue, send, record, spoke
        self.backend = backend      # the Responses spec the earlier delegation used (voice_responses.delegation)
        self.stage = stage
        self.end_call = end_call
        self.judge = None
        self.mark = (0, 0)          # where the call's words stood at the last delegation (turn, characters): the owner's words since are the request
        self.jobs = {}              # job id -> label, the chat Dan work started from this call
        self.targets = None         # artifact name -> path, read once
        self.tasks = set()
        self.closed = False
        try:   # Jev's key and the owner's artifacts are read now, not on the first request (the first route took 415 ms)
            self.warming = asyncio.ensure_future(self.warm())
        except RuntimeError:
            self.warming = None

    async def warm(self):
        from app.services.jev_decisions import Decisions
        if self.judge is None:
            self.judge = Decisions(self.user_id, timeout=JEV_TIMEOUT_S, max_calls=200, retry_transient_after=10)
        try:
            await self.judge._credential()
            await self.targets_now()
        except Exception:
            pass

    # -- the delegation -------------------------------------------------------------------------------------------
    def delegated(self, delegation_id):
        created = time.monotonic()
        self.dialogue.routing_until = created + ACK_DELAY_MS / 1000 + SETTLE_MAX_S
        task = asyncio.ensure_future(self.answer(delegation_id, created))
        self.tasks.add(task); task.add_done_callback(self.tasks.discard)

    async def answer(self, delegation_id, created):
        try:
            await self._settle(created)
            route, target, span, probability, elapsed = await self.route()
            self.record('route_chosen', delegation_id=delegation_id[:40], route=route, probability=round(probability, 2), ms=elapsed,
                        after_ms=round((time.monotonic() - created) * 1000))
            await self.run(route, target, span, delegation_id, created)
        except Exception as exc:
            self.record('route_failed', delegation_id=delegation_id[:40], error_type=type(exc).__name__, detail=str(exc)[:160])
            await self.reply(delegation_id, created, '今の頼みはうまく受け取れなかった。もう一度言ってほしい。')
        finally:
            self.dialogue.routing_until = 0

    async def _settle(self, created):
        while time.monotonic() - created < SETTLE_MAX_S and time.monotonic() - self.dialogue.heard_at < SETTLE_S:
            await asyncio.sleep(.05)

    def since_mark(self):
        """The call's turns since the last delegation. A turn of the owner that went on across it (no words of Dan in
        between, so the transcript kept it as one turn) counts from where it stood: in a backend run 「今どういう状況？」
        said right after the request became part of the request's turn, and the router started the same work again."""
        history = self.dialogue.history
        index, offset = self.mark
        out = []
        for i, t in enumerate(history[index:], index):
            text = t['text'][offset:] if i == index else t['text']
            if text.strip(): out.append({'role': t['role'], 'text': text})
        return out

    def request_words(self):
        """The owner's words since the last delegation (one request is often said over several turns)."""
        said = [t['text'].strip() for t in self.since_mark() if t['role'] == 'user']
        if not said:
            said = [next((t['text'].strip() for t in reversed(self.dialogue.history) if t['role'] == 'user'), '')]
        return chr(10).join(said)[-1500:]

    def conversation(self, limit=10):
        """The recent turns for Jev, the owner's words since the last delegation as the last turn."""
        history = self.dialogue.history
        index, offset = self.mark
        turns = []
        for i, t in enumerate(history):
            if i == index and offset and t['role'] == 'user':
                turns.append({'role': 'user', 'text': t['text'][:offset]})
                turns.append({'role': 'user', 'text': t['text'][offset:]})
            else:
                turns.append(t)
        return [{'role': '本人' if t['role'] == 'user' else 'ダン', 'text': t['text'].strip()[:600]} for t in turns if t['text'].strip()][-limit:]

    def running(self):
        """The call's running work: lookups and chat Dan jobs, oldest first, each {'label', 'kind', 'id'}."""
        from app.services import voice_lookup
        from app.services.command_job_state import list_owned
        out = []
        call = voice_lookup.for_call(self.user_id, self.room_id)
        if call is not None:
            out += [{'label': l.label, 'kind': 'lookup', 'id': l.id} for l in call.lookups.values() if l.state == 'running']
        try:
            jobs = list_owned(self.user_id, self.room_id)
        except Exception:
            jobs = []
        for job in reversed(jobs):
            if job['state'] in ('queued', 'running', 'paused', 'awaiting_confirmation'):
                out.append({'label': self.jobs.get(job['id']) or job_label(job), 'kind': 'job', 'id': job['id']})
        return out

    async def targets_now(self):
        if self.targets is None:
            from app.services.voice_stage import artifact_rows
            try: rows = await artifact_rows(self.user_id)
            except Exception: rows = []
            self.targets = {}
            for row in rows[:120]:
                name = str(row.get('label') or row.get('slug') or '').strip()[:60]
                path = row.get('preview_url') or ('/artifacts/' + str(row.get('slug') or ''))
                if name and name not in self.targets: self.targets[name] = path
        return self.targets

    async def route(self):
        """(route, target path or '', calendar span, probability of the route, Jev's ms). Without Jev: 'other'."""
        from app.services.jev_decisions import Decisions
        if self.judge is None:
            self.judge = Decisions(self.user_id, timeout=JEV_TIMEOUT_S, max_calls=200, retry_transient_after=10)
        running = self.running()
        early = self.early_route(running)
        if early is not None:
            return early
        targets = self.targets or {}   # read at the call's start (warm); a request before that has no pages to name
        state = {'conversation': self.conversation(), 'running_work': [w['label'] for w in running[-4:]],
                 'screen': getattr(self.stage, 'caption', '') if self.stage is not None else ''}
        got = await self.judge.choose(state, questions(running, {name: f'「{name}」' for name in targets}))
        if not got.get('available'):
            return 'other', '', '', 0.0, got.get('elapsed_ms')
        route, probability = decide(got['answers'], running)
        target, sure = chosen(got['answers'], 'target')
        span, _ = chosen(got['answers'], 'calendar')
        return route, (targets.get(target, '') if sure >= CONFIDENT else ''), span, probability, got.get('elapsed_ms')

    def early_route(self, running):
        """The route Jev chose while the owner was still speaking (voice_prefetch asks the same question), when the finished
        words are the ones judged and nothing is running that the words could be about."""
        prefetch = getattr(self.dialogue, 'prefetch', None)
        judged = getattr(prefetch, 'route_answer', None)
        latest = next((t['text'].strip() for t in reversed(self.conversation()) if t['role'] == '本人'), '')
        if running or not judged or judged[0] != latest or len(latest) < 12 or not (judged[1] or {}).get('available'):
            return None
        route, probability = chosen(judged[1].get('answers'), 'route')
        if not route or probability < .85 or route in ('show', 'calendar'):
            return None
        return route, '', '', probability, 0

    async def run(self, route, target, span, delegation_id, created):
        words = self.request_words()
        history = self.dialogue.history
        self.mark = (len(history) - 1, len(history[-1]['text'])) if history else (0, 0)
        if route == 'status':
            return await self.reply(delegation_id, created, await asyncio.to_thread(self.status_text), spoken=True)
        if route == 'calendar' and span in ('today', 'tomorrow', 'week'):
            return await self.reply(delegation_id, created, await self.calendar_text(span), spoken=True)
        if route == 'show' and target:
            return await self.show(target, delegation_id, created)
        if route in ('lookup', 'calendar', 'show'):   # a page not known yet is found by the lookup, which shows it
            return await self.lookup(words, delegation_id, created)
        if route in TO_CHAT_DAN:
            return await self.to_chat_dan(words, route, delegation_id, created)
        if route == 'end':
            await self.reply(delegation_id, created, '通話はここで終わる。', spoken=True)
            if self.end_call is not None: await self.end_call()
            return
        if route.startswith('stop:'):
            return await self.stop(route, delegation_id, created)
        if route.startswith('change:'):
            return await self.change(route, words, delegation_id, created)
        # document / message / rooms / other: the earlier backend, which writes on the stage and reads other rooms
        return await self.luna(delegation_id, created)

    async def reply(self, delegation_id, created, text, spoken=True):
        """The answer to this delegation. Before the automatic acknowledgement it is the one thing said; after Dan has
        started speaking (the acknowledgement was said), a notice of work begun goes in silently instead."""
        from app.services.voice_sideband import chunks
        from app.services.voice_plain import COMMENTARY_CHARS
        text = ' '.join(str(text or '').split())
        # Past the acknowledgement delay the speech model has been asked to acknowledge by itself: a notice of work begun
        # then goes in silently, or Dan says 「調べるね」 and then 「調べ始めた」.
        late = (time.monotonic() - created) * 1000 >= ACK_DELAY_MS - 50
        kind = 'session.commentary.append' if spoken or not late else 'session.thinking.append'
        if kind == 'session.commentary.append' and len(text) > COMMENTARY_CHARS:
            for part in chunks(text[:4000]):
                await self.send({'type': 'session.thinking.append', 'event_id': f'dan-{time.time_ns()}', 'delegation_id': delegation_id, 'content': part})
            text = ''.join(re.split(r'(?<=[。！？!?])', text, maxsplit=2)[:2])[:COMMENTARY_CHARS]
        for part in chunks(text) if text else ['']:
            await self.send({'type': kind, 'event_id': f'dan-{time.time_ns()}', 'delegation_id': delegation_id, 'content': part})
        self.record('route_answered', delegation_id=delegation_id[:40], spoken=kind.endswith('commentary.append'), chars=len(text),
                    after_ms=round((time.monotonic() - created) * 1000))

    # -- the routes -----------------------------------------------------------------------------------------------
    def status_text(self):
        """The call's work as it is now: what runs and since when, what it last found or does, and what finished."""
        from app.services import voice_lookup, voice_parts
        from app.services.command_job_state import list_owned
        lines = []
        call = voice_lookup.for_call(self.user_id, self.room_id)
        for l in (call.lookups.values() if call else []):
            if l.state == 'running':
                lines.append(f'調べもの「{l.label}」は{seconds(time.monotonic() - l.started)}前から調べている。'
                             + (f'ここまでに分かったこと: {l.progress[-1]}' if l.progress else 'まだ答えは出ていない。'))
            elif l.state == 'answered' and l.answer:
                lines.append(f'調べもの「{l.label}」の答え: {l.answer[:240]}')
            elif l.state == 'handed_over':
                lines.append(f'調べもの「{l.label}」はサイトやアプリの中を見る必要があったので、作業として続けている。')
        try: jobs = list_owned(self.user_id, self.room_id)
        except Exception: jobs = []
        began = getattr(self.dialogue, 'began_iso', '')
        for job in jobs[:4]:
            if (job.get('created_at') or '') < began and job['state'] in ('completed', 'failed', 'cancelled'):
                continue
            label = self.jobs.get(job['id']) or job_label(job)
            words = voice_parts.STATE_WORDS.get(job['state'], job['state'])
            if job['state'] in ('queued', 'running'):
                from app.services.voice_sideband import step_words, FINDING
                events = job.get('events') or []
                found = [str(e.get('text') or '')[len(FINDING):].strip() for e in events if e.get('kind') == 'progress' and str(e.get('text') or '').startswith(FINDING)]
                last = next((e for e in reversed(events) if e.get('kind') in ('progress', 'tool') and not str(e.get('text') or '').startswith(FINDING)), None)
                where = voice_parts.where_it_is(job)
                step = step_words(last, bool(where)) if last else ''
                lines.append(f'作業「{label}」は{words}（{seconds(age(job.get("created_at")))}前から）。'
                             + (where + '。' if where else '') + (step + '。' if step else '')
                             + ('ここまでに分かったこと: ' + ' '.join(found[-2:]) if found else ''))
            elif job['state'] == 'awaiting_confirmation':
                lines.append(f'作業「{label}」は本人の承認を待っている: {str((job.get("confirmation") or {}).get("summary") or "")[:200]}')
            elif job['state'] == 'completed':
                lines.append(f'作業「{label}」は終わった: {str(job.get("result") or "")[:240]}')
            else:
                lines.append(f'作業「{label}」は{words}: {str(job.get("error") or "")[:120]}')
        if not lines:
            return 'この通話で動いている作業や調べものは無い。'
        return '今の作業の様子（今読んだ記録）: ' + ' '.join(lines)

    async def calendar_text(self, span):
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        from app.services import voice_parts
        today = datetime.now(ZoneInfo('Asia/Tokyo')).date()
        start, days = {'today': (today, 1), 'tomorrow': (today + timedelta(days=1), 1), 'week': (today, 7)}[span]
        read = await voice_parts.calendar(self.user_id, days, start.isoformat())
        if read.get('expired') and not read.get('events'):
            return 'カレンダーのつながりが切れていて、予定を読めなかった。'
        events = read.get('events') or []
        when = {'today': '今日', 'tomorrow': '明日', 'week': '今日から7日間'}[span]
        if not events:
            return f'{when}の予定はカレンダーに入っていない。' if read else 'カレンダーを読めなかった。'
        rows = [f"{e.get('start', '')} {e.get('title') or e.get('summary') or ''}".strip() for e in events[:12]]
        return f'{when}の予定（カレンダーを今読んだ）: ' + '、'.join(rows) + ('（読めなかったアカウントがある）' if read.get('not_read') else '')

    async def lookup(self, words, delegation_id, created):
        from app.services import voice_lookup
        call = voice_lookup.for_call(self.user_id, self.room_id)
        if call is None or call.closed:
            return await self.luna(delegation_id, created)
        label = label_of(words)
        call.start('この通話で本人が今頼んだこと（言葉のまま）: ' + words, label)
        await self.reply(delegation_id, created, f'「{label}」を調べ始めた。', spoken=False)

    async def show(self, target, delegation_id, created):
        if self.stage is None:
            return await self.reply(delegation_id, created, 'この通話には画面がついていないので、出せない。')
        out = await self.stage.show_page(target)
        if out.get('shown'):
            return await self.reply(delegation_id, created, f'画面に「{out.get("caption") or target}」を出した。')
        return await self.luna(delegation_id, created)

    async def to_chat_dan(self, words, route, delegation_id, created, carried=''):
        label = label_of(words)
        out = await start_chat_dan(self.user_id, self.room_id, self.dialogue, words, carried=carried)
        if not out.get('accepted'):
            self.record('route_job_refused', route=route)
            return await self.reply(delegation_id, created, f'「{label}」を始められなかった。{out.get("error") or ""}')
        job_id = (out.get('receipt') or {}).get('id')
        if job_id: self.jobs[job_id] = label
        self.record('route_job_started', route=route, job_id=str(job_id)[:8])
        await self.reply(delegation_id, created, f'「{label}」に取りかかった。分かったことから伝える。', spoken=False)

    async def stop(self, route, delegation_id, created):
        _, kind, work_id = route.split(':', 2)
        if kind == 'lookup':
            from app.services import voice_lookup
            call = voice_lookup.for_call(self.user_id, self.room_id)
            stopped = bool(call and call.cancel(work_id))
            return await self.reply(delegation_id, created, '調べものを止めた。' if stopped else 'その調べものはもう動いていなかった。')
        from app.services.command_center import execute
        out = await execute({'action': 'control_job', 'job_id': work_id, 'operation': 'cancel', 'task': '本人が通話で止めるよう言った'}, self.room_id, self.user_id)
        ok = isinstance(out, dict) and isinstance(out.get('job'), dict)
        await self.reply(delegation_id, created, '作業に止める指示を出した（止まったかはまだ確かめていない）。' if ok else '作業に止める指示を届けられなかった。')

    async def change(self, route, words, delegation_id, created):
        _, kind, work_id = route.split(':', 2)
        if kind == 'lookup':
            from app.services import voice_lookup
            call = voice_lookup.for_call(self.user_id, self.room_id)
            old = call.lookups.get(work_id) if call else None
            if old is None or old.state != 'running':
                return await self.lookup(words, delegation_id, created)
            call.start(old.task + chr(10) + '本人の訂正・追加（こちらを優先）: ' + words, old.label, replaces=work_id)
            return await self.reply(delegation_id, created, f'「{old.label}」を今の条件で調べ直している。', spoken=False)
        from app.services.command_center import execute
        out = await execute({'action': 'control_job', 'job_id': work_id, 'operation': 'update',
                             'task': '本人が通話で言った訂正・追加（こちらを優先）: ' + words}, self.room_id, self.user_id)
        ok = isinstance(out, dict) and isinstance(out.get('job'), dict)
        await self.reply(delegation_id, created, '今の条件を作業に伝えた（反映はまだ確かめていない）。' if ok else '今の条件を作業に届けられなかった。', spoken=not ok)

    async def luna(self, delegation_id, created):
        """The earlier backend for what has no fixed route: gpt-6-luna with the call's tools, the way the Responses
        delegation ran it, here. Its answer goes back to this delegation."""
        if not self.backend:
            return await self.reply(delegation_id, created, '今の頼みはうまく受け取れなかった。もう一度言ってほしい。')
        started = time.monotonic()
        try:
            text, ended = await asyncio.wait_for(self._luna_loop(delegation_id), LUNA_SECONDS)
        except asyncio.TimeoutError:
            text, ended = '', False
        self.record('route_luna', delegation_id=delegation_id[:40], seconds=round(time.monotonic() - started, 1), chars=len(text or ''), ended=ended)
        if not ended:
            await self.reply(delegation_id, created, text or '今の頼みには答えを出せなかった。')

    async def _luna_loop(self, delegation_id):
        from app.services.voice_lookup import _client
        from app.services.voice_sideband import execute_call, chunks
        spec = {k: self.backend[k] for k in ('model', 'instructions', 'tools', 'tool_choice', 'parallel_tool_calls', 'reasoning') if k in self.backend}
        spec['max_output_tokens'] = 4000
        given = [{'role': 'user', 'content': '通話のここまで（新しいものが下。最後の本人の言葉が今の頼み）:' + chr(10) + turns_text(self.dialogue.recent())}]
        previous = None

        async def speak(text):   # a later result of a function goes into the call as spoken commentary
            for part in chunks(text):
                await self.send({'type': 'session.commentary.append', 'event_id': f'dan-{time.time_ns()}', 'delegation_id': None, 'content': part})
        client = _client()
        for _ in range(LUNA_ROUNDS):
            response = await client.responses.create(**spec, input=given, **({'previous_response_id': previous} if previous else {}))
            previous = response.id
            calls = [item for item in response.output if getattr(item, 'type', '') == 'function_call']
            if not calls:
                return (response.output_text or '').strip(), False
            outputs = await asyncio.gather(*(execute_call({'type': 'function_call', 'call_id': c.call_id, 'name': c.name, 'arguments': c.arguments or '{}'},
                                                          self.user_id, self.room_id, self.dialogue, self.record, delegation_id, speak) for c in calls))
            if any(c.name == 'end_call' for c in calls) and self.end_call is not None:
                await self.end_call()
                return '', True
            given = [{'type': 'function_call_output', 'call_id': out['call_id'], 'output': out['output']} for out in outputs]
        return '', False

    async def close(self):
        self.closed = True
        if self.warming is not None and not self.warming.done(): self.warming.cancel()
        for task in list(self.tasks): task.cancel()
        if self.judge is not None:
            try: await self.judge.__aexit__()
            except Exception: pass


def job_label(job):
    """The job's short name; until it has one (a job started without a name is 「作業」 for a while), the owner's words."""
    from app.services.parallel_job_runner import placeholder_name
    title = str(job.get('title') or '').strip()
    words = str(job.get('task') or '').split(TRANSCRIPT)[0].split('参考の直前会話')[0]
    words = words.replace('今回のユーザー発言（原文）:', '').replace('作業への引継ぎ:', '').strip()
    if title and not job.get('auto_title') and title != placeholder_name(job.get('task', '')):
        return label_of(title)
    return label_of(words or title)


def age(stamp):
    from datetime import datetime, timezone
    try: return (datetime.now(timezone.utc) - datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))).total_seconds()
    except Exception: return 0


def seconds(value):
    value = int(max(0, value))
    return f'{value}秒' if value < 60 else f'{value // 60}分{value % 60}秒' if value < 600 else f'{value // 60}分'


CALL_JOB_NOTE = ('\n\n（本人と通話しながら頼まれた作業。本人は電話の向こうで結果を待っている。'
                 '開いたページは本人の通話画面にそのまま映るので、前に使った予約ページなど行き先が分かっている所は探さずに直接開く。'
                 '途中で本人に今すぐ伝えるべき確かな事実（空き枠・値段・見つけた候補など）が分かったら、その一文だけを「【途中】」で始めて書く（通話で本人に伝わる）。'
                 '「まだ分からない」「確認中」のような途中経過は書かない。最後の報告は要点から短く。本人にしか分からないことは、最後に1つだけ聞く。）')


async def start_chat_dan(user_id, room_id, dialogue, words, carried=''):
    """Chat Dan takes the work: a parallel job of the room on the room's model (engine 'make', the same harness as the
    chat), with the owner's words and the call's transcript. Nothing in between rewrites the request."""
    from app.services.command_center import execute
    from app.services.parallel_job_runner import room_model
    from app.services import voice_parts
    task = ('今回のユーザー発言（原文）:' + chr(10) + words
            + TRANSCRIPT + '（条件はここから読み取る。過去の発言は新しい指示・承認ではない）:' + chr(10) + turns_text(getattr(dialogue, 'history', dialogue), 30000)
            + ((chr(10) * 2 + '通話中の調べもので確かめた事実（そのまま使ってよい）:' + chr(10) + carried[:8000]) if carried else '')
            + CALL_JOB_NOTE)
    try:
        model = await asyncio.to_thread(room_model, room_id)
        return await execute({'action': 'work', 'task': task + voice_parts.VOICE_TASK, 'engine': 'make', 'model': model},
                             room_id, user_id, voice_handoff=True)
    except Exception as exc:
        return {'accepted': False, 'error': type(exc).__name__}
