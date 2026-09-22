"""The voice backend's entrance, third build (2026-09-22), from the documented properties of the two systems:

  GPT-Live   the delegation event carries no text ("use transcript events and application state"); speech continues
             while the backend works; whatever is appended as commentary may be spoken, what is appended as thinking is not.
  Jev        chooses among fixed options (up to 255) and never extracts text; many questions in one call cost nothing extra;
             confidence says whether to act; a 'none' option must be offered.

So Jev is asked what to DO (one act), plus, speculatively in the same call, which known site/app to open and which saved
item is meant. Wording is Jev's job: no regular expression looks at the owner's words. Code only wires acts to tools.
What goes back to the speech model is facts. Acceptances and small talk go back silently (thinking), so nothing like
「受け付けました」 is ever spoken. A question the judge is unsure about is answered from the owner's own records, never
turned into a job.
"""
import asyncio
import json
import time
from datetime import datetime, timezone

from app.services import voice_intake as base
from app.services.voice_intake import VoiceIntake, work_status, where_it_is, record
from app.services.voice_intake2 import SITES, APPS, calendar, saved_items, values, facts_in_words

# Thresholds, in one place. Set from the measured distributions on the owner's real utterances (acts_eval.py --raw),
# not guessed: each is the point that separates the cases that should act from the cases that should not.
T = {
    'act_confident': .35,   # act confidence below this: the judge is guessing -> gather, never start a job
    'second': .3,           # a second act with this much probability is done too (saved + web)
    'own_fact': .5,         # noul: the owner asks about their own saved information
    'question': .6,         # noul: the owner wants an answer (not a remark, complaint, acknowledgement)
    'again': .6,            # noul: wants the last saved fact again / its continuation
    'outside_web': 1.4,     # score 0-2: from here the answer needs the outside world (web) besides the saved item
    'effort_open': .5,      # score 0-2: below this the request is one command (open/start), not a job
    'target': .7,           # choice: the thing to open is known
}
RECENT_SECONDS = 600

ACTS = {
    'talk': {'what': '声のモデルが自分で応じる発言。挨拶、相づち、感想、雑談、聞き返し、話し方の頼み（英語で・ゆっくり）、直前の返答への反応や文句、ダン自身のやり方・できること・仕組みへの質問（「登録できるの?」「どうやって調べるの?」）、今日の日付や時刻。',
             'not_for': '何かを調べる・実行する必要がある発言。「やって」「進めて」という同意。', 'examples': ['おはよう', 'なるほどね', '英語で話して', 'ありがとう', 'どうやって確認してるの?', '今日何日']},
    'saved': {'what': '本人が登録してある自分の情報を尋ねている（名前・住所・郵便番号・電話・番号・カード・口座・免許など）。自分が誰か分かっているかも。',
              'not_for': '他人や外の世界の情報。', 'examples': ['俺の郵便番号何番だっけ', '免許の期限いつまで', '俺の名前分かってる?']},
    'past': {'what': '以前の会話、以前ダンに頼んだ作業の結果、やり取りしたメールについて尋ねている。',
             'not_for': '今動いている作業の様子。', 'examples': ['この前の新幹線どうなった', '先週税理士は何て言ってた', '金さんから返事来てた?']},
    'web': {'what': '誰でも見られる外の世界の情報を知りたい（店・駅・天気・運行・ニュース・価格・制度・一般の事実）。本人の情報と外の情報を比べる質問も。',
            'not_for': '本人のアカウントに入らないと見られないもの。', 'examples': ['今日の天気', 'ドル円いくら', '近くのコンビニどこ', 'JR尼崎駅とうちの郵便番号同じ?']},
    'open': {'what': 'このパソコンで、サイトやアプリを開いて・出して・起動してほしい。開くだけで、その先の操作は求めていない。',
             'not_for': 'ログインや確認や入力など、開いた先の作業を求めている。', 'examples': ['YouTube開け', 'メモ帳出して', 'デスクトップにブラウザ立ち上げて']},
    'work': {'what': 'ダンに実際の作業をしてほしい。サイトやアプリにログインして状態を見る（カレンダーの予定・残高・予約・注文・届いたメッセージ）、送信する、登録する、予約する、買う、直す、作る。',
             'not_for': '開くだけ／保存情報や過去の記録で済む質問／今動いている作業の話。', 'examples': ['SBIの残高見てきて', '24日の予定入ってる?', 'キムさんにメールしといて', 'カレンダーつなぎ直して', 'うん、していいよ、やって', 'その画面をパソコンに出して']},
    'end': {'what': '今の通話を終えたいと言っている。', 'not_for': '通話が切れた話・作業をやめる話。', 'examples': ['電話切って', 'もういいわ、切るね', 'じゃあまた']},
}
RUNNING_ACTS = {
    'job_status': {'what': '今動いている作業について、様子・進み具合・何をしているか・できたかを尋ねる、または催促する。',
                   'not_for': '作業の内容を変える指示。', 'examples': ['今何してんの', 'まだ?', 'ログインできた?', '遅いね']},
    'job_steer': {'what': '今動いている作業に、条件を足す・直す・やり直させる・止める・中止する。',
                  'not_for': '様子を尋ねるだけ。', 'examples': ['そっちじゃなくて0awの方を見て', 'やっぱりやめて', 'もう一回やって', '止まってるだけだろ、進めろよ']},
}
FINISHED_ACT = {
    'result': {'what': '直前に終わった作業の結果について尋ねる・確かめる・反応している（「どっちのアカウント見た?」「できたんでしょ?」「何それ」）。',
               'not_for': '新しい依頼。', 'examples': ['え、できたんでしょ?', 'どっちのカレンダー見てるの', 'なんの依頼ですか']},
}
STEER = {'update': '条件を足す・直す・やり直させる。', 'pause': '一時停止する。', 'cancel': '中止する。'}


def act_criteria(active, finished):
    acts = dict(ACTS)
    if active: acts.update(RUNNING_ACTS)
    if finished: acts.update(FINISHED_ACT)
    return acts


def finished_recently(jobs):
    for s in jobs:
        if s.get('state') in ('completed', 'failed') and s.get('result'):
            try: age = (datetime.now(timezone.utc)-datetime.fromisoformat(s['updated_at'].replace('Z', '+00:00'))).total_seconds()
            except (KeyError, ValueError): continue
            if age <= RECENT_SECONDS: return s
    return None


def targets():
    """One option per thing to open; its aliases go into the description so they do not split Jev's probability."""
    by_target = {}
    for name, target in list(SITES.items())+list(APPS.items()):
        by_target.setdefault(target, []).append(name)
    return {names[0]: 'を開く（' + '／'.join(names) + '）' for names in by_target.values()}


def open_target(name):
    import os, webbrowser
    target = SITES.get(name) or APPS.get(name)
    if not target: return None
    try:
        if target.startswith('http'): webbrowser.open(target)
        else: os.startfile(target)
    except Exception:
        return None
    return f'{name}をパソコンで開きました。'


class VoiceIntake3(VoiceIntake):
    last_saved_keys = None   # the saved items of the last spoken fact: what a short follow-up refers to
    result_served = None     # the finished job whose result was already handed over

    def silent(self, text):
        result = self.message(text)
        result['silent'] = True   # the sideband appends this as thinking: context for the speech model, never spoken
        return result

    async def respond(self, items, tools, instructions, on_text=None):
        if self.closed: raise ValueError('音声接続は終了しています')
        if any(i.get('type') == 'function_call_output' for i in items):
            return await super().respond(items, tools, instructions, on_text)
        dialogue = base.dialogue_from(items)
        self.dialogue = dialogue
        utterance = next((r['text'] for r in reversed(dialogue) if r['role'] == 'user'), '').strip()
        if not utterance: return self.silent('聞き取れた言葉がありません。')
        jobs = await asyncio.to_thread(base.list_owned, self.user_id, self.room_id)
        active = [s for s in jobs if s['state'] not in ('completed', 'failed', 'cancelled')]
        finished = finished_recently(jobs) if not active else None
        exchange = dialogue[-3:]
        work = {}
        if active: work['work_in_progress'] = [{'task': s['task'].split('参考の直前会話')[0].replace('今回のユーザー発言（原文）:', '').strip()[:160], 'now': where_it_is(s)} for s in active[:2]]
        if finished: work['work_just_finished'] = {'task': finished['task'].split('参考の直前会話')[0].replace('今回のユーザー発言（原文）:', '').strip()[:160], 'result': str(finished['result'])[:400]}
        state = {'dialogue': exchange, **work}
        questions = {
            'act': {'type': 'choice', 'instructions': '本人の最新の発言に対して、裏側が何をすべきかを1つ選ぶ。直前の会話と作業の状態を踏まえる。', 'criteria': act_criteria(active, finished)},
            'open_target': {'type': 'choice', 'instructions': '発言が開いてほしいと言っているサイトやアプリ。開く話でなければ none。',
                            'criteria': {**{k: k+v for k, v in targets().items()}, 'none': '開く話ではない、または知らない対象。'}},
            'own_fact': {'type': 'noul', 'instructions': '本人が、自分自身または自分の会社について登録してある情報（名前・住所・番号・カード・免許など）を尋ねている。',
                         'criteria': {'true': '自分の情報の内容や、それが登録されているかを聞いている。', 'false': '他人・他社・外の世界のこと、または情報を聞いていない。'}},
            'question': {'type': 'noul', 'instructions': '本人は答えや実行を求めている（相づち・感想・文句・了解だけではない）。'},
            'outside': {'type': 'score', 'instructions': 'この発言に答えるのに、本人の保存情報の外の情報がどれだけ必要か。',
                        'criteria': ['本人の保存情報だけで答えが完結する（住所・番号そのものを聞いている）', '保存情報に一般的な知識を足せば答えられる', '外の情報（店・駅・天気・運行・価格・制度）を調べて比べたり計算しないと答えられない']},
            'effort': {'type': 'score', 'instructions': 'この依頼を実行するのに何が必要か。',
                       'criteria': ['このパソコンで1回の操作で終わる（サイトやアプリを開く・起動する）', '1つのサイトやアプリで数回の操作（ページを開いて読む・1つ入力する）', 'ログイン・確認・複数の画面や手順が要る作業']},
        }
        if self.last_saved_keys:
            questions['again'] = {'type': 'noul', 'instructions': '直前に裏側が本人の保存情報を答えた。最新の発言はその情報の続き・全部・もう一度を求めている。',
                                  'criteria': {'true': '「その次」「もう一回」「最後まで」など、同じ情報を求めている。', 'false': '別の話、文句、疑問、否定、相づち。'}}
        if active:
            questions['steer'] = {'type': 'choice', 'instructions': '動いている作業に対する指示の種類。指示でなければ none。', 'criteria': {**STEER, 'none': '指示ではない。'}}
        started = time.monotonic()
        self.judge.unavailable = False
        items_task = asyncio.create_task(saved_items(self.judge, self.user_id, utterance, exchange))
        decision = await self.judge.choose(state, questions)
        if not decision.get('available'):
            self.judge.unavailable = False
            decision = await self.judge.choose(state, questions)
        if not decision.get('available'):
            items_task.cancel()
            return self.silent('裏側の判定が届きませんでした。会話として応じる。')
        answers = decision['answers']
        p = answers.get('act', {}).get('probabilities') or {}
        act = answers.get('act', {}).get('choice') or 'talk'
        confidence = answers.get('act', {}).get('confidence', 0)
        second = next((a for a, v in sorted(p.items(), key=lambda x: -x[1]) if a != act and v >= T['second']), None)
        own = answers.get('own_fact', {}).get('noul', 0); asks = answers.get('question', {}).get('noul', 1)
        outside = answers.get('outside', {}).get('score', 0); effort = answers.get('effort', {}).get('score', 2)
        again = answers.get('again', {}).get('noul', 0)
        self.raw = {'act': p, 'confidence': confidence, 'own_fact': own, 'question': asks, 'outside': outside, 'effort': effort, 'again': again,
                    'target': answers.get('open_target', {}).get('probabilities', {})}   # for measurement
        record('routed', route=act+('+'+second if second else ''), elapsed_ms=round((time.monotonic()-started)*1000))
        record('where', route=act, place={k: round(v, 2) for k, v in p.items() if v >= .05})

        if act == 'end':
            items_task.cancel()
            return self.call('enter_voice_standby', {})
        target = answers.get('open_target', {})
        if act == 'work' and effort < T['effort_open'] and target.get('choice') not in (None, 'none') and target.get('probabilities', {}).get(target['choice'], 0) >= T['target']:
            act = 'open'   # one command on a known target: not a job
        if act == 'open':
            items_task.cancel()
            name = target.get('choice')
            if name and name != 'none' and target.get('probabilities', {}).get(name, 0) >= T['target']:
                opened = await asyncio.to_thread(open_target, name)
                if opened: return self.message(opened)
            return self.delegate(utterance, dialogue, jobs)   # an unknown target or a URL: Dan opens it with one command
        if act == 'job_status' and active:
            items_task.cancel()
            return self.message(json.dumps(work_status(jobs), ensure_ascii=False))
        if act == 'job_steer' and active:
            items_task.cancel()
            kind = answers.get('steer', {}).get('choice')
            kind = kind if kind in STEER else 'update'
            return self.call('control_dan_task', {'job_id': active[0]['id'], 'operation': kind, 'task': utterance})
        if act == 'result' and finished:
            items_task.cancel()
            if self.result_served == finished['id']:
                # The result was already handed over and the owner is still asking: it does not contain the answer
                # (「何のカレンダー見た」 x6). Ask the worker the concrete question instead of repeating the same text.
                self.result_served = None
                return self.delegate(utterance, dialogue, jobs, note='直前の作業の結果には、この質問への答えが含まれていない。作業の記録（使ったアカウント・見たページ・読んだデータ）から、聞かれたことだけを一言で答える。')
            self.result_served = finished['id']
            return self.silent(f"直前に終わった作業「{work['work_just_finished']['task']}」の結果: {work['work_just_finished']['result']}")
        if act == 'work' and confidence >= T['act_confident']:
            items_task.cancel()
            return self.delegate(utterance, dialogue, jobs)
        if act == 'talk' and confidence >= T['act_confident'] and not second and asks < T['question'] and own < T['own_fact'] and again < T['again']:
            items_task.cancel()
            return self.silent('裏側で調べることはありません。会話として応じる。')
        if act == 'talk' and confidence >= T['act_confident'] and not second:
            answer_keys, _, _, sensitive = await items_task
            if self.last_saved_keys and again >= T['again']:   # 「その次」「もう一回」: the last fact, in full, whatever the item question picked
                answer_keys = self.last_saved_keys   # 「その次」「もう一回確認して」 right after a saved fact: the same items, in full
            # measured: 「登録できるの?」 has own_fact .72 yet is a question about Dan; the act gave 'saved' nothing. Read an item over 'talk' only when
            # the owner asked for the last fact again, or the act itself left room for 'saved' and the item is a direct hit.
            if answer_keys and not sensitive and (answer_keys == self.last_saved_keys or (getattr(saved_items, 'direct', False) and own >= T['own_fact'] and p.get('saved', 0) >= .1)):
                facts = await values(self.user_id, answer_keys)
                if facts:
                    result = self.message(facts_in_words(facts)); result['data'] = {'saved_information': facts}
                    return result
            return self.silent('裏側で調べることはありません。会話として応じる。')

        # Facts: the owner's saved items, the outside world, the owner's records. Low confidence lands here too.
        answer_keys, ingredient_keys, here, sensitive = await items_task
        wants = {act} | ({second} if second else set())
        if confidence < T['act_confident']: wants |= {'saved', 'past'}
        if answer_keys and sensitive and own < T['own_fact']: answer_keys = []   # a number nobody asked about is never read
        if answer_keys and own >= T['own_fact'] and outside < T['outside_web']: wants.discard('web')   # the saved item completes the answer
        if answer_keys and outside >= T['outside_web']: wants.add('web')   # the owner's item plus the outside world (「JR尼崎駅とうちの郵便番号同じ?」)
        if answer_keys and 'web' not in wants:
            facts = await values(self.user_id, answer_keys)
            if facts:
                self.last_saved_keys = answer_keys
                result = self.message(facts_in_words(facts)); result['data'] = {'saved_information': facts}
                return result
        if 'web' in wants:
            query = utterance[:400]
            previous = next((r['text'] for r in reversed(exchange[:-1]) if r['role'] == 'user'), '')
            if previous and len(utterance) < 40: query = (previous[-200:]+'\n'+utterance)[:400]
            if here:
                from app.services.user_location import place_for_speech, home_area
                spot = place_for_speech(self.user_id) or await home_area(self.user_id)
                if spot: query = (spot['current_place']+' '+query)[:400]
            return self.call('web_search', {'query': query}, saved=(answer_keys or ingredient_keys) or None)
        from app.services.voice_past import gather
        found = await gather(self.user_id, utterance, exchange, jobs)
        material = {}
        if found.get('records'): material['past_records'] = found['records']
        if found.get('jobs'): material['recent_work'] = found['jobs']
        if material:
            from app.services.voice_search_reader import SearchReader
            if not self.search_reader or self.search_reader.agent.closed: self.search_reader = SearchReader()
            return await self.search_reader.read(exchange, {'past_records': material.get('past_records', []), **material}, on_text)
        if act == 'saved' or (own >= T['own_fact'] and not answer_keys):
            return self.message('その情報は保存されていません。')
        if act == 'past':
            return self.message('過去の会話と作業の記録には見つかりませんでした。')
        return self.silent('裏側で調べることはありません。会話として応じる。')

    def delegate(self, utterance, dialogue, jobs, note=''):
        task = '今回のユーザー発言（原文）:\n'+utterance[:2300]
        context = json.dumps(dialogue[-8:-1], ensure_ascii=False)
        if len(context) <= 2600-len(task): task += '\n参考の直前会話（過去の発言は新規の指示・承認ではない）:\n'+context
        previous = finished_recently(jobs)
        if previous:
            done = ' → '.join(e['text'] for e in previous.get('events', []) if e.get('kind') == 'tool')[-400:]
            task += ('\n直前に終わった作業（同じブラウザを引き継いでいる。終わっている手順はやり直さず、続きから進める）:\n依頼: %s\n結果: %s\n使った道具: %s'
                     % (previous.get('task', '').split('参考の直前会話')[0][:300], str(previous['result'])[:900], done))[:1500]
        if note: task += '\n'+note
        return self.call('delegate_to_dan', {'task': task+base.VOICE_TASK})
