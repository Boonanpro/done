"""The voice backend's entrance, rebuilt (2026-09-22).

The old entrance asked "what kind of request is this?" (one label) and, to patch its misses, also "is the web needed?",
"is it an order?", "where does the answer live?", "is it about the owner?", each with its own bar, and settled their
disagreements in about 70 branches added one incident at a time.

This one asks ONE thing: where is the answer? One choice among the places, the most likely one wins (the options compete, so
no bar is needed; yes/no per place was tried and measured worse). A second call, at the same time, says which of the owner's
saved items is the answer or an ingredient, so a request that needs two places (「JR尼崎駅とうちの郵便番号同じ?」 = web + the
owner's postcode) needs no special case. A place that finds nothing hands over to the next: saved -> past -> Dan. Hanging up
is decided by the words, not by a probability. The model that judges sees the last exchange only: a long conversation made it
answer about the previous topic. What goes back to the speech model is facts in plain words, nothing else.

    places:  saved   the owner's own saved information
             past    earlier conversations, earlier work, mail
             web     the outside world
             site    something that must be opened or done (a site, an app, the calendar, sending, ordering)
             running the work in progress (only while there is one)
             now     the conversation itself; the speech model answers by itself.
"""
import asyncio
import json
import time

from app.services import voice_intake as base
from app.services.voice_intake import VoiceIntake, HANG_UP, ASKING, plain, work_status, record

BAR = .6
SHARE = .2      # a place with this much of the probability is looked at too, together with the most likely one
CALENDAR = None   # set below
import re
NAGGING = re.compile(r'まだ|遅い|おそい|どうなっ|終わった|進んで|できた[?？かの]')   # asking after the work in progress, in so many words
PLACES = {
    'now': '今の会話の中、またはダン自身の考えや話し方で答えられる（挨拶・相づち・雑談・言い換え・聞き返し・話し方の頼み）。',
    'saved': '本人が登録してある自分の情報（名前・住所・電話・番号・カード・口座など）。自分が誰か分かっているかを尋ねるのもここ。',
    'past': '過去の会話、以前ダンに頼んだ作業の結果、やり取りしたメール（「この前の」「先週の」「結局どうなった」）。',
    'web': '誰でも見られる外の世界の情報（店・駅・天気・運行状況・ニュース・価格・制度・一般の事実）。本人の情報と外の情報を比べる質問もここ。',
    'site': '本人のアカウントにログインしないと見られない今の状態（カレンダーの予定・残高・予約や注文の状態・届いたメッセージ）、または何かを実行する依頼（保存・登録・送信・連絡・予約・購入・操作）。',
}
RUNNING = '今進行中の作業の話（今何をしているか・どこまで進んだか・ログインできたかを尋ねる、催促する、「まだ?」、やり直しを求める、条件を足す、止める）。'
CONTROL = {'status': '作業の様子や結果を尋ねている・催促している。', 'update': '作業の条件を足す・直す。',
           'pause': '作業を一時停止してほしい。', 'cancel': '作業をやめてほしい。'}


import re as _re
CALENDAR = _re.compile(r'カレンダー|予定|スケジュール|空いて|あいてる')   # the calendar is asked for in so many words


async def calendar(user_id, days=14):
    """The owner's coming events, read here directly. {'events': [...]} | {'expired': True} | {} when not connected."""
    from app.services.calendar_service import get_calendar_service
    try:
        read = await asyncio.wait_for(asyncio.to_thread(get_calendar_service().get_events_with_source, user_id, days), 12)
    except Exception as exc:
        return {'expired': True} if 'invalid_grant' in str(exc) or 'expired or revoked' in str(exc) else {}
    events = read['events']
    if events and isinstance(events[0], dict) and events[0].get('error'): return {}
    return {'events': [{k: e.get(k) for k in ('title', 'summary', 'start', 'end', 'location', 'calendar') if e.get(k)} for e in events[:30]],
            'source': {'what': 'Googleカレンダー', **(read.get('source') or {}), 'days': days}}


SITES = {'youtube': 'https://www.youtube.com/', 'ユーチューブ': 'https://www.youtube.com/', 'google': 'https://www.google.com/', 'グーグル': 'https://www.google.com/',
         'gmail': 'https://mail.google.com/', 'ジーメール': 'https://mail.google.com/', 'カレンダー': 'https://calendar.google.com/', 'amazon': 'https://www.amazon.co.jp/',
         'アマゾン': 'https://www.amazon.co.jp/', '楽天': 'https://www.rakuten.co.jp/', 'x': 'https://x.com/', 'twitter': 'https://x.com/', 'ツイッター': 'https://x.com/',
         'chatgpt': 'https://chatgpt.com/', 'インスタ': 'https://www.instagram.com/', 'instagram': 'https://www.instagram.com/', 'ダン': 'https://dan.paina.info/'}
APPS = {'メモ帳': 'notepad', '電卓': 'calc', 'エクスプローラー': 'explorer', 'エクスプローラ': 'explorer', '設定': 'ms-settings:', 'ペイント': 'mspaint',
        'discord': 'discord:', 'ディスコード': 'discord:', 'line': 'line:', 'ライン': 'line:', 'chrome': 'chrome', 'クローム': 'chrome', 'ブラウザ': 'https://www.google.com/'}
OPEN = _re.compile(r'(?:(?P<url>https?://\S+)|(?P<what>[A-Za-z0-9ぁ-んァ-ヶ一-龥ー]{1,20}?))\s*(?:を|も)?(?:パソコン|PC|デスクトップ|画面)?(?:で|に)?(?:開いて|出して|起動して|立ち上げて|表示して)', _re.I)


def quick_open(utterance):
    """「YouTubeをパソコンで開いて」「メモ帳出して」: one command on this PC, no job (a job takes nine seconds to start).
    Returns the fact to say, or None when the words are not a plain open of a known site, app or URL."""
    import os, webbrowser
    found = OPEN.search(utterance.replace('　', ' '))
    if not found: return None
    url, what = found.group('url'), (found.group('what') or '').strip()
    target, name = (url, url) if url else (None, what)
    if not target:
        key = what.lower()
        target = SITES.get(key) or APPS.get(key) or SITES.get(what) or APPS.get(what)
    if not target: return None
    try:
        if target.startswith('http'): webbrowser.open(target)
        else: os.startfile(target)
    except Exception:
        return None
    return f'{name}をパソコンで開きました。'


def yes_no(text):
    return {'type': 'choice', 'instructions': '最新の発言について、次のことが当てはまるかを選ぶ。', 'criteria': {'yes': text, 'no': '当てはまらない。'}}


async def saved_items(judge, user_id, utterance, dialogue):
    """Which saved items are the answer, and which are only an ingredient (「うち」-> the home address, 「この近く」-> here).
    Jev sees item names only. Returns (answer_keys, ingredient_keys, here)."""
    from app.services.personal_info_service import PersonalInfoService
    service = PersonalInfoService()
    try: rows = await asyncio.to_thread(service.list_masked_sync, user_id)
    except Exception: return [], [], False, False
    rows = [r for r in rows if r.get('field_key')][:120]
    if not rows: return [], [], False, False
    names = {r['field_key']: f"{(r.get('label') or r['field_key'])[:100]}（{r['field_key']}）" for r in rows}
    kind = {r['field_key']: r.get('category') for r in rows}
    decision = await judge.choose({'question': utterance, 'recent_dialogue': dialogue}, {
        'answer': {'type': 'choice', 'criteria': {**names, 'none': '保存済みの項目は答えにならない。'},
                   'instructions': '最新の発言が求めている情報と同じものを指す保存項目、またはその情報を中に含む保存項目（町名や番地なら住所、市外局番なら電話番号）を選ぶ。対象そのものが違うもの（実家の住所を聞かれて自宅の住所、会社の電話を聞かれて個人の電話）は選ばず none。会話の続き（「その次は」「全部言って」）なら話題の項目を選ぶ。'},
        'ingredient': {'type': 'choice', 'criteria': {**names, base.HERE: '本人が今いる場所（「この近く」「ここから」、場所を言わない天気や店）。', 'none': '本人の保存項目は材料にならない。'},
                       'instructions': '答えを出す材料として必要な本人の保存項目を選ぶ。「うち」「自宅」は自宅の住所、「うちの会社」は会社の情報。'}})
    if not decision.get('available'): return [], [], False, False

    direct = {}

    def pick(question, related=False):
        probabilities = decision['answers'].get(question, {}).get('probabilities') or {}
        mass = {}
        for key, p in probabilities.items():
            if key in kind: mass[kind[key]] = mass.get(kind[key], 0)+p
        best = max(mass, key=mass.get) if mass else None
        if best and mass[best] >= BAR:   # the same fact is saved under several keys: judge by kind
            keys = sorted((k for k in probabilities if kind.get(k) == best), key=lambda k: -probabilities[k])
            direct[question] = True
            return [k for i, k in enumerate(keys[:3]) if i == 0 or probabilities[k] >= .1]
        if probabilities.get('none', 1) < .2:   # Jev is sure SOME item answers, split across kinds (町名: city .42 + 住所 .52): take the top ones
            keys = sorted((k for k, v in probabilities.items() if k in kind and v >= .15), key=lambda k: -probabilities[k])[:3]
            if keys:
                direct[question] = True
                return keys
        if related and best == 'other':   # an answer spread over items happens only for names (family name + given name + kana); an address is one item, so 「実家」 with only 「自宅」 saved is a miss
            keys = sorted((k for k, p in probabilities.items() if kind.get(k) == best and p >= .04), key=lambda k: -probabilities[k])[:3]
            return keys if sum(probabilities[k] for k in keys) >= .2 else []
        return []
    here = (decision['answers'].get('ingredient', {}).get('probabilities') or {}).get(base.HERE, 0) >= BAR
    answer = pick('answer', related=True)
    saved_items.direct = direct.get('answer', False)   # read by the caller right after awaiting (one call at a time per agent)
    return answer, pick('ingredient'), here, any(kind.get(k) in ('payment', 'identity') for k in answer)


async def values(user_id, keys):
    from app.services.personal_info_service import PersonalInfoService
    from app.services.voice_readings import annotate
    service, facts = PersonalInfoService(), []
    for key in keys[:3]:
        found = await service.get(user_id, key)
        if found and found.get('value'): facts.append({'label': found.get('label') or key, 'value': str(found['value'])[:500]})
    return annotate(facts)


def facts_in_words(facts):
    return '。'.join(f"{f['label']}は、{f.get('say') or f['value']}" for f in facts)+'。'


class VoiceIntake2(VoiceIntake):
    async def respond(self, items, tools, instructions, on_text=None):
        if self.closed: raise ValueError('音声接続は終了しています')
        if any(i.get('type') == 'function_call_output' for i in items):
            return await super().respond(items, tools, instructions, on_text)   # results of tools come back the same way
        dialogue = base.dialogue_from(items)
        self.dialogue = dialogue
        utterance = next((r['text'] for r in reversed(dialogue) if r['role'] == 'user'), '').strip()
        if not utterance: return self.message('聞き取れませんでした。')
        if HANG_UP.search(utterance): return self.call('enter_voice_standby', {})
        opened = await asyncio.to_thread(quick_open, utterance)
        if opened: return self.message(opened)
        jobs = await asyncio.to_thread(base.list_owned, self.user_id, self.room_id)
        active = [s for s in jobs if s['state'] not in ('completed', 'failed', 'cancelled')]
        proposals = [s for s in active if s['state'] == 'awaiting_confirmation' and s.get('confirmation')]
        if proposals:   # a pending purchase/send: the approval path is unchanged and is not mixed with anything else
            return await super().respond(items, tools, instructions, on_text)
        exchange = dialogue[-3:]   # the last exchange: what 「それ」「その次」 refer to, and no more
        places = {**PLACES, **({'running': RUNNING} if active else {})}
        questions = {'where': {'type': 'choice', 'instructions': '最新の発言への答えが、どこを見れば出てくるかを1つ選ぶ。', 'criteria': places}}
        if active:
            questions['control'] = {'type': 'choice', 'instructions': '進行中の作業について、最新の発言が何を求めているかを選ぶ。作業の話でなければ none。',
                                    'criteria': {**CONTROL, 'none': '進行中の作業の話ではない。'}}
        started = time.monotonic()
        self.judge.unavailable = False
        items_task = asyncio.create_task(saved_items(self.judge, self.user_id, utterance, exchange))
        state = {'dialogue': exchange, **({'work_in_progress': [s['task'].split('参考の直前会話')[0][:200] for s in active]} if active else {})}
        decision = await self.judge.choose(state, questions)
        if not decision.get('available'):
            self.judge.unavailable = False
            decision = await self.judge.choose(state, questions)   # once more; a lost judgement must not become a job
        if not decision.get('available'):
            items_task.cancel()
            return self.message('裏側で内容を判定できませんでした。')
        p = decision['answers'].get('where', {}).get('probabilities') or {}
        place = max(p, key=p.get) if p else 'now'
        needed = {place}
        record('routed', route='+'.join(sorted(needed)) or 'talk', elapsed_ms=round((time.monotonic()-started)*1000))
        record('where', route='+'.join(sorted(needed)) or 'talk', place={k: round(v, 2) for k, v in p.items()})
        again = bool(self.answered and self.answered[0] == utterance)   # the speech model asked again: go one step further
        rung = self.answered[1] if again else 0

        if active and place != 'running' and NAGGING.search(utterance) and len(utterance) <= 30: needed = {'running'}
        if 'running' in needed and active:
            items_task.cancel()
            control = decision['answers'].get('control', {})
            wanted = control.get('choice')
            if wanted in ('update', 'pause', 'cancel') and control.get('probabilities', {}).get(wanted, 0) >= BAR:
                return self.call('control_dan_task', {'job_id': active[0]['id'], 'operation': wanted, 'task': utterance})
            return self.message(json.dumps(work_status(jobs), ensure_ascii=False))

        answer_keys, ingredient_keys, here, sensitive = await items_task
        asking = bool(ASKING.search(utterance))
        # Every place with a real share is looked at, not only the most likely one. A question is never "conversation only".
        looked = [name for name, value in sorted(p.items(), key=lambda x: -x[1]) if name not in ('now', 'running') and value >= SHARE]
        if place != 'now' and place not in looked and place != 'running': looked.insert(0, place)
        # A question is not "conversation only" unless Jev is quite sure it is (「それってどういう意味?」 is; 「24日って予定あったっけ」 was
        # called conversation with half the probability, and that must not end the search).
        talk = place == 'now' and (not asking or p.get('now', 0) >= .75)
        if talk: looked = []
        elif not looked: looked = [name for name, _ in sorted(p.items(), key=lambda x: -x[1]) if name not in ('now', 'running')][:2]
        points_at_owner = p.get('saved', 0) >= SHARE or bool(ingredient_keys)   # by the probability itself: 'looked' can hold a place nobody believes in
        # 「有効期限は」「その後の住所も全部言って」 are not phrased as questions but clearly ask for the owner's item.
        if not (answer_keys and (asking or p.get('saved', 0) >= .5) and (points_at_owner if (sensitive or 'web' in looked) else True)): answer_keys = []
        if again and rung >= 2: return self.delegate(utterance, dialogue, jobs)

        # A saved item that is the whole answer: said at once, nothing else is needed.
        if answer_keys and rung < 1:
            outside = await base.answers_it(self.judge, utterance, exchange, answer_keys) if 'web' in looked else 0
            if outside < base.OUTSIDE_BAR:
                facts = await values(self.user_id, answer_keys)
                if facts:
                    self.answered = (utterance, 1)
                    result = self.message(facts_in_words(facts))
                    result['data'] = {'saved_information': facts}
                    return result
            else:
                ingredient_keys = answer_keys
        if 'web' in looked or (again and rung == 1):
            query = utterance[:400]
            previous = next((r['text'] for r in reversed(exchange[:-1]) if r['role'] == 'user'), '')
            if previous and len(utterance) < 40: query = (previous[-200:]+'\n'+utterance)[:400]   # 「そこ何時まで?」 needs what 「そこ」 is
            if here:
                from app.services.user_location import place_for_speech, home_area
                spot = place_for_speech(self.user_id) or await home_area(self.user_id)
                if spot: query = (spot['current_place']+' '+query)[:400]
            self.answered = (utterance, 2)
            return self.call('web_search', {'query': query}, saved=ingredient_keys or None)
        if not looked:
            self.answered = (utterance, 1)
            return self.message('調べる内容のない会話でした。')

        wants_calendar = bool(CALENDAR.search(utterance))
        if looked[0] == 'site' and not wants_calendar: return self.delegate(utterance, dialogue, jobs)   # real work: no point searching first
        # The owner's own records and calendar, at the same time.
        from app.services.voice_past import gather
        found, dates = await asyncio.gather(
            gather(self.user_id, utterance, exchange, jobs) if looked else asyncio.sleep(0, {'records': [], 'jobs': []}),
            calendar(self.user_id) if wants_calendar else asyncio.sleep(0, {}))
        material = {}
        if found.get('records'): material['past_records'] = found['records']
        if found.get('jobs'): material['recent_work'] = found['jobs']
        if dates.get('events') is not None: material['calendar'] = dates['events']
        if dates.get('expired') or ('site' in looked and not material.get('calendar')):
            return self.delegate(utterance, dialogue, jobs, note='Googleカレンダーの接続が失効している。python D:/done/scripts/dan_calendar.py list --days 14 が返す reconnect_url を本人の普段のブラウザで開いて同意まで進め、終わったら同じコマンドで予定を読む。' if dates.get('expired') else '')
        if material:
            from app.services.voice_search_reader import SearchReader
            if not self.search_reader or self.search_reader.agent.closed: self.search_reader = SearchReader()
            self.answered = (utterance, 2)
            return await self.search_reader.read(exchange, {'past_records': material.get('past_records', []), **material}, on_text)
        names = {'saved': '保存情報', 'past': '過去の会話と作業の記録', 'site': 'サイトやアプリ'}
        self.answered = (utterance, 2)
        return self.message('、'.join(names[n] for n in looked if n in names)+('とカレンダー' if wants_calendar else '')+'を探しましたが、見つかりませんでした。')

    def delegate(self, utterance, dialogue, jobs, note=''):
        """Dan itself takes it: the owner's words, the last exchange, and the job that just ended in this room."""
        task = '今回のユーザー発言（原文）:\n'+utterance[:2300]
        context = json.dumps(dialogue[-8:-1], ensure_ascii=False)
        if len(context) <= 2600-len(task): task += '\n参考の直前会話（過去の発言は新規の指示・承認ではない）:\n'+context
        previous = next((s for s in jobs if s['state'] in ('completed', 'failed') and s.get('result')), None)
        if previous:
            from datetime import datetime, timezone
            try: age = (datetime.now(timezone.utc)-datetime.fromisoformat(previous['updated_at'].replace('Z', '+00:00'))).total_seconds()
            except (KeyError, ValueError): age = 1e9
            if age <= 900:
                done = ' → '.join(e['text'] for e in previous.get('events', []) if e.get('kind') == 'tool')[-400:]
                task += ('\n直前に終わった作業（約%d分前。同じブラウザを引き継いでいる。終わっている手順はやり直さず、続きから進める）:\n依頼: %s\n結果: %s\n使った道具: %s'
                         % (round(age/60), previous.get('task', '').split('参考の直前会話')[0][:300], str(previous['result'])[:900], done))[:1500]
        if note: task += '\n'+note
        self.answered = None
        return self.call('delegate_to_dan', {'task': task+base.VOICE_TASK})
