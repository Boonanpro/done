"""Jev intake -> existing tools or one persistent worker. No coordinator LLM."""
import asyncio
import json
import logging
import re
import time
import uuid

from app.services.jev_decisions import Decisions
from app.services.command_job_state import list_owned
from app.services.voice_trace import record

logger=logging.getLogger(__name__)
MATERIAL_ROUTES=('search','history','other','conversation',None)   # answered from gathered materials; the rest are controls
ROUTES={
    'conversation':'今の会話で既に分かった情報の言い換え・説明・再確認。新しい外部調査や操作は不要。',
    'search':'最新の外部情報を検索する質問。購入・予約の操作や複雑な比較計画はwork。',
    'status':'現在の仕事の進捗・結果・何を待っているか・確認待ちの内容を尋ねる質問。仕事の変更ではない。',
    'history':'以前伝えた情報、保存された記憶、別の部屋を含む過去の会話や結果を確認する質問。',
    'work':'新しい実作業・ブラウザ操作・制作・複雑な調査や計画を依頼する。予約の購入・変更・取消もここ。',
    'update':'進行中の仕事の条件を追加・訂正する実行指示。単なる進捗や確認内容への質問はstatus。',
    'pause':'進行中の仕事を一時停止する。通話の終了ではない。',
    'cancel':'進行中の仕事自体を中止する。予約・商品の取消はwork。',
    'confirm':'提示された具体的な確定内容に対して今実行してよいと承認する。条件変更や質問は含まない。',
    'end':'今の音声通話を終える依頼。引用・仮定・否定・仕事停止ではない。',
    'other':'雑談・曖昧な指示・上記以外。',
}

STATE_WORDS={'queued':'これから始める','running':'作業中','paused':'一時停止中','awaiting_confirmation':'本人の承認待ち',
    'completed':'完了','failed':'失敗','cancelled':'中止'}
ASKING=re.compile(r'[?？]|誰|何|なに|どこ|いつ|どれ|どう|分か|わか|知って|教え|っけ|かな|ある[?？のか]|あった')   # a question, not 「オッケー、合ってる」
HANG_UP=re.compile(r'(電話|通話|でんわ).{0,6}(切って|切れ(?!た|て[るいま])|切ろ|終わって|終わりにして|終了して|消せ|消して)|^(もう)?切って(くれ|ください)?[。!！]*$')   # an order, not talk about a call that dropped

DOING={'open':'ページを開いている','open_target':'ページを開いている','click':'画面のボタンやリンクを押している','human_click':'画面を押している',
    'type':'文字を入力している','fill_form':'フォームに入力している','fill_credential':'ログイン情報を入力している','fill_totp_code':'認証コードを入力している',
    'wait_for_otp_from_app':'認証コードが届くのを待っている','wait_for_link_from_app':'確認メールのリンクを待っている','solve_captcha':'ロボット確認を解いている',
    'follow':'画面をたどっている','read':'画面を読んでいる','find':'画面の中を探している','content':'画面を読んでいる','screenshot':'画面を見ている','scroll':'画面を送っている',
    'lookup':'ダンの記録を調べている','read_url':'ウェブのページを読んでいる','get_personal_info':'保存情報を確認している','get_credentials':'ログイン情報を確認している',
    'remember_personal_info':'情報を保存している','web_search':'ウェブで調べている','desktop':'PCのアプリを操作している','get_location':'現在地を確認している'}

def where_it_is(job):
    """The page the job's browser is on and what it is doing there, from what the tool layer recorded (not the model's notes)."""
    tool=job.get('current_tool') or job.get('last_tool') or {}
    doing=DOING.get(tool.get('action') or tool.get('name') or '','')
    text=str((job.get('last_observation') or {}).get('text') or '')
    url=re.search(r'URL:\s*(\S+)',text); title=re.search(r'タイトル:\s*([^\n]{1,60})',text)
    host=re.sub(r'^https?://(www\.)?([^/]+).*$',r'\2',url.group(1)) if url else ''
    page=f"「{title.group(1).strip()}」（{host}）" if title and title.group(1).strip() else host
    if job.get('current_tool') and doing:doing='今'+doing
    elif doing:doing='直前に'+doing.replace('いる','いた')
    return '、'.join(x for x in (f'ブラウザは{page}を開いている' if page else '',doing) if x)

def work_status(jobs):
    """What Dan is doing right now, from the job files on this machine: answered at once, in a few hundred characters.
    It used to be a tool call through the phone that carried the whole job list (80,000 characters) both ways."""
    rows=[]
    for s in list(jobs)[:3]:
        events=s.get('events',[])
        rows.append({'依頼':s.get('task','').split('参考の直前会話')[0].replace('今回のユーザー発言（原文）:','').strip()[:160],
            '状態':STATE_WORDS.get(s.get('state'),s.get('state')),
            '今やっていること':next((e['text'][:200] for e in reversed(events) if e.get('kind')=='progress'),'') if s.get('state') in ('running','queued') else '',
            '今の画面と操作':where_it_is(s) if s.get('state') in ('running','queued','awaiting_confirmation','paused') else '',
            '承認を待っている内容':((s.get('confirmation') or {}).get('summary') or '')[:300],
            '結果':str(s.get('result') or '')[:600]})
    return {'work_status':rows,'note':'これがダンの作業の今の状況の全部。聞かれたことに、この中から一言二言で答える（例:「はい、今EXサイトにログインしているところです」）。'
        '道具の名前や「確認待ち」などの内部の言葉はそのまま読まず、普通の言葉に言い換える。作業が無ければ「今は何も作業していません」。'}

def plain(data):
    """A result for the speech model in plain words: facts, status, next step. None when the data has no plain form."""
    if data.get('saved_information'):
        facts='。'.join(f"{f['label']}は、{f.get('say') or f['value']}" for f in data['saved_information'][:3])
        return '本人が保存している情報です。'+facts+'。省略せずに伝えてください。'
    if data.get('not_saved'):
        return 'その情報はまだ保存されていません。教えてもらえれば保存できます。'
    if 'work_status' in data:
        rows=data['work_status']
        if not rows:return '今は何も作業していません。'
        s=rows[0]
        parts=[f"今の作業は「{s['依頼'][:80]}」で、状態は{s['状態']}です"]
        if s.get('今の画面と操作'):parts.append(s['今の画面と操作'])
        if s.get('今やっていること') and s['今やっていること'] not in ('依頼内容を確認しています','実行先を確認しています'):parts.append('作業側のメモ: '+s['今やっていること'][:120])
        if s.get('承認を待っている内容'):parts.append('本人の返事を待っている内容: '+s['承認を待っている内容'][:160])
        if s.get('結果'):parts.append('結果: '+s['結果'][:260])
        return '。'.join(parts)+'。'
    return None

def dialogue_from(items):
    """Only the client conversation envelope supplies the current utterance."""
    for item in reversed(items):
        content=item.get('content')
        parts=content if isinstance(content,list) else [{'text':content}] if isinstance(content,str) else []
        for part in reversed(parts):
            try: data=json.loads(part.get('text',''))
            except (ValueError,TypeError):continue
            if isinstance(data,dict) and isinstance(data.get('dialogue'),list):
                return [dict(role=r['role'],text=r['text']) for r in data['dialogue']
                        if isinstance(r,dict) and r.get('role') in ('user','assistant') and isinstance(r.get('text'),str)]
    return []

def live_request(items):
    """What the speech model itself asked the backend for. It may know 'search this' when the owner's words alone do not say so."""
    for item in reversed(items):
        content=item.get('content')
        parts=content if isinstance(content,list) else [{'text':content}] if isinstance(content,str) else []
        for part in reversed(parts):
            try:data=json.loads(part.get('text',''))
            except (ValueError,TypeError):continue
            if isinstance(data,dict) and isinstance(data.get('dialogue'),list):
                request=data.get('request')
                return (request if isinstance(request,str) else json.dumps(request,ensure_ascii=False) if request else '')[:600]
    return ''

def final_input(items):
    for item in reversed(items):
        content=item.get('content')
        parts=content if isinstance(content,list) else [{'text':content}] if isinstance(content,str) else []
        for part in reversed(parts):
            try:data=json.loads(part.get('text',''))
            except (ValueError,TypeError):continue
            if isinstance(data,dict) and isinstance(data.get('dialogue'),list):
                return data.get('utterance_final') is True if 'utterance_final' in data else None
    return None

async def saved_final_reply(user_id,room_id,utterance,proposal):
    """Older installed clients lack a final-transcript flag. Use their saved
    full utterance, never a partial phrase or a previous approval."""
    from app.services.chat_service import ChatService
    from datetime import datetime
    import unicodedata
    def normalized(text):return ''.join(unicodedata.normalize('NFKC',text).removeprefix('🎙').split()).rstrip('。.!！?？')
    deadline=time.monotonic()+3.5
    while True:
        rows=await ChatService().get_messages(room_id,user_id,limit=8)
        latest=next(iter(sorted((r for r in rows if r.get('sender_type') in {'human','user'}),key=lambda r:r.get('created_at') or '',reverse=True)),None)
        if latest and proposal.get('created_at') and latest.get('created_at'):
            after=datetime.fromisoformat(latest['created_at'].replace('Z','+00:00'))>datetime.fromisoformat(proposal['created_at'].replace('Z','+00:00'))
            if after and normalized(latest.get('content',''))==normalized(utterance):
                return True
        if time.monotonic()>=deadline:return False
        await asyncio.sleep(.25)

def spoken_result(data):
    """Share current facts, not old task imperatives or replayed progress."""
    if isinstance(data.get('jobs'),list) or isinstance(data.get('job'),dict):
        rows=data.get('jobs') if isinstance(data.get('jobs'),list) else [data['job']]
        return {'jobs':[{'task':s.get('task','').split('参考の直前会話')[0][:400],
            'state':s.get('state'),'result':str(s.get('result') or '')[:2000],
            'confirmation':(s.get('confirmation') or {}).get('summary'),
            'progress':next((e['text'][:600] for e in reversed(s.get('events',[])) if e['kind']=='progress'),'')
            if s.get('state')=='running' else ''} for s in rows[:6]]}
    if isinstance(data.get('messages'),list):
        messages=[]
        for m in data['messages']:
            role=m.get('sender_type') or m.get('role') or m.get('from')
            role={'human':'user','ai':'assistant','dan':'assistant'}.get(role,role)
            text=m.get('content') if m.get('content') is not None else m.get('text','')
            messages.append({'role':role,'text':str(text),'at':m.get('created_at') or m.get('at')})
        return {**data,'messages':messages}
    return data

async def saved_fact(judge,user_id,utterance,dialogue):
    """The owner's own saved information as a material for the answer, found in about half a second.

    Returns None (no saved item is involved), or a dict for the speech model:
      {'saved_information':[{label,value},...],'keys':[...],'role':'answer'}       the item asked for
      {'saved_information':[...],'keys':[...],'role':'ingredient'}                 not asked for, but needed to answer
                                                                                  (「うちから一番近いコンビニ」 needs the home address)
      {'not_saved':True}                          the owner asked for a fact about themselves that is not saved
    Jev sees item names only, never values."""
    from app.services.personal_info_service import PersonalInfoService
    service=PersonalInfoService()
    try:rows=await asyncio.to_thread(service.list_masked_sync,user_id)
    except Exception:return None
    rows=[r for r in rows if r.get('field_key')][:120]
    if not rows:return None
    # Some items were saved with their value as the label (last_name | 本田): the key says what the item IS.
    criteria={r['field_key']:f"{(r.get('label') or r['field_key'])[:100]}（{r['field_key']}）" for r in rows}
    started=time.monotonic()
    decision=await judge.choose({'question':utterance,'recent_dialogue':dialogue[-6:]},{
        'field':{'type':'choice','criteria':{**criteria,'none':'保存済みの項目では答えにならない（過去の会話や作業の結果を調べる必要がある、保存されていない事柄）。'},
            'instructions':'本人の最新の発言が求めている情報に、そのまま答えになる保存済みの項目を選ぶ。直前の会話の続き（「その後は」「全部言って」など）なら、'
                           '会話で話題になっている項目を選ぶ。項目名が求められている対象と一致する時だけ選び、近いだけの項目は選ばない。'},
        'ingredient':{'type':'choice','criteria':{**criteria,HERE:'本人が今いる場所（「この近く」「ここから」「今いる所」「この辺」。場所を言わずに尋ねる天気・店・施設・道順も、今いる場所が材料になる）。','none':'本人の保存項目は材料にならない（一般的な質問、他の場所や他人の話、雑談、作業の依頼）。'},
            'instructions':'最新の発言に答えを出すために、材料として必要になる本人の保存項目を選ぶ。発言の中の「うち」「自宅」「俺んち」「家の近く」「最寄り」は'
                           '自宅の住所が、「うちの会社」は会社の情報が材料になる。発言が本人の場所・持ち物・契約に触れていなければ none。'},
        'about_self':{'type':'choice','criteria':{
            'self_fact':'本人が、自分自身や自分の会社について登録してあるはずの事実（住所・電話・生年月日・番号・名前など）を尋ねている。自分が誰か・自分の名前を分かっているかを尋ねるのもここ。',
            'other':'それ以外（他人や他社の情報、過去の会話や作業、依頼、雑談）。'},
            'instructions':'最新の発言が何を求めているかを選ぶ。'}})
    if not decision.get('available'):return None
    category={r['field_key']:r.get('category') for r in rows}
    def hit(name):
        # Measured live with the owner's real item names: the same fact saved under several keys (住所 x3, 電話 x2) splits
        # the mass, so judge by kind. Answerable questions gave their kind >= .58 and "none" <= .41; questions about
        # past talk, work or other people gave "none" >= .70 and any kind <= .30. The bar sits in that gap.
        probabilities=decision.get('answers',{}).get(name,{}).get('probabilities') or {}
        masses={}
        for k,p in probabilities.items():
            if k in category:masses[category[k]]=masses.get(category[k],0)+p
        kind=max(masses,key=masses.get) if masses else None
        if not (kind and masses[kind]>=.5 and probabilities.get('none',0)<=.45):return probabilities,[]
        kin=sorted([k for k in probabilities if category.get(k)==kind],key=lambda k:-probabilities[k])
        return probabilities,[k for i,k in enumerate(kin[:3]) if i==0 or probabilities[k]>=.1]
    probabilities,keys=hit('field');role='answer'
    about=decision.get('answers',{}).get('about_self',{})
    # 「二十四日って言ってんの」 matched an item and an e-Tax number was read aloud, unasked. An item is THE ANSWER only when
    # the words ask for a fact about the owner; everything else may use it as an ingredient at most.
    if keys and about and about.get('probabilities',{}).get('self_fact',0)<.5:keys=[]
    here=(decision.get('answers',{}).get('ingredient',{}).get('probabilities') or {}).get(HERE,0)
    if not keys and here>=.5:
        record('saved_fact',route='here',elapsed_ms=round((time.monotonic()-started)*1000))
        return {'here':True}
    if not keys:
        _,keys=hit('ingredient');role='ingredient'
    about=decision.get('answers',{}).get('about_self',{})
    # 「会社の電話番号って何番で登録してたっけ」: the item was picked as an ingredient only, yet the owner is asking for their own fact.
    if keys and role=='ingredient' and about.get('choice')=='self_fact' and about.get('probabilities',{}).get('self_fact',0)>=.8:role='answer'
    record('saved_fact',route=('hit' if role=='answer' else 'ingredient') if keys else 'miss',elapsed_ms=round((time.monotonic()-started)*1000))
    if not keys and about.get('probabilities',{}).get('self_fact',0)>=.4:
        # No single item is the answer, yet the owner asks about themselves: the answer may be spread over items
        # (family name + given name + kana). Bring out the closest ones of one kind. Never from payment/identity:
        # reading a number nobody asked for is harm, so those kinds need a direct hit.
        close=sorted(((k,v) for k,v in probabilities.items() if k in category and v>=.04 and category[k] not in ('payment','identity')),key=lambda x:-x[1])[:3]
        kinds={category[k] for k,_ in close}
        if close and sum(v for _,v in close)>=.2 and len(kinds)==1 and not kinds&{'payment','identity'}:
            keys=[k for k,_ in close];role='answer'
    if not keys:
        if about.get('choice')=='self_fact' and about.get('probabilities',{}).get('self_fact',0)>=.8 and probabilities.get('none',0)>=.6:
            return {'not_saved':True}
        return {'asked_about_self':True} if about.get('probabilities',{}).get('self_fact',0)>=.4 else None
    facts=[];found_keys=[]
    for k in keys:
        found=await service.get(user_id,k)
        if found and found.get('value'):facts.append({'label':found.get('label') or k,'value':str(found['value'])[:500]});found_keys.append(k)
    return {'saved_information':facts,'keys':found_keys,'role':role} if facts else None


async def answers_it(judge,utterance,dialogue,labels):
    """With the matched item named: does telling its value complete the answer, or is outside information needed too?"""
    decision=await judge.choose({'question':utterance,'recent_dialogue':dialogue[-4:],'matched_saved_items':labels},{
        'complete':{'type':'choice','instructions':'本人の保存項目 matched_saved_items の値を伝えれば、最新の発言への答えとして完結するかを選ぶ。',
            'criteria':{'complete':'その値を伝えれば答えになる（その項目そのものを尋ねている）。',
                        'needs_outside':'その値に加えて、外部の情報（他の場所・店・駅・会社・天気・料金・制度など）を調べて比べたり計算したりしないと答えにならない。'}}})
    return decision.get('answers',{}).get('complete',{}).get('probabilities',{}).get('needs_outside',0) if decision.get('available') else 0


SAVED_FACT_NOTES={'saved_information':'本人が以前保存した情報。省略せず、番地・建物名・部屋番号・桁まで全部そのまま伝える。ここに無い部分を「登録されていない」と言わない。','not_saved':'この情報はまだ保存されていない。「登録されていない」で終わらせず、今教えてくれれば保存できると伝えて、内容を聞く。教えてもらえたら保存を依頼する。'}
SEARCH_BAR=.7
HERE='__current_place__'
VOICE_TASK='\n音声通話からの依頼です。報告は声で読み上げられるので、短く、新しく分かった事実だけを書く（同じ説明や謝罪をくり返さない）。見るだけの操作（ログイン、履歴・明細・状況の表示）は承認を求めずに進める。承認が要るのは購入・取消・送信など取り返しのつかない確定だけ。新規登録をする時は、使うメールアドレス（lookup の source=addresses で本人のアドレス一覧を出す）とパスワードの決め方を、始める前に本人に確認する。'
ACT_BAR=.8
WHERE_BAR=.5
OUTSIDE_BAR=.85   # live: real combinations gave >= .95, plain saved-item questions <= .68

class VoiceIntake:
    def __init__(self,user_id,room_id):
        self.user_id=user_id;self.room_id=room_id
        self.closed=False;self.pending={};self.judge=Decisions(user_id,timeout=1.8,max_calls=800)
        self.active=False
        self.search_reader=None
        import threading
        from app.services.voice_readings import towns
        threading.Thread(target=towns,daemon=True).start()   # the postcode table takes about a second to load: not during an answer
        self.answered=None   # (utterance, rung) of the last material reply: asking again climbs to the next rung

    def warm(self,*args):
        """Measured: the first judgement of a call paid about 1.5s for the credential and the connection, close to the
        1.8s limit, and a lost judgement is a lost answer. Pay that while the call is still connecting."""
        async def open_connection():
            try:await self.judge.choose({'text':'もしもし'},{'ready':{'type':'choice','criteria':{'yes':'挨拶','no':'それ以外'}}})
            except Exception:pass
            self.judge.unavailable=False
        try:
            asyncio.get_running_loop().create_task(open_connection())
            if not self.search_reader:
                from app.services.voice_search_reader import SearchReader
                self.search_reader=SearchReader()
        except RuntimeError:pass
    def close(self):
        self.closed=True
        if self.search_reader:self.search_reader.close()
        if self.judge._client:
            try:asyncio.get_running_loop().create_task(self.judge._client.aclose())
            except RuntimeError:pass
    async def steer(self,items):return False

    def message(self,text):
        data=None
        try:
            data=json.loads(text)
            if isinstance(data,dict):text=plain(data) or text
        except ValueError:pass
        # 'data' is for tests and traces; the speech model gets the plain text.
        return {'output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':text}]}],
                'backend':'jev_intake','model':'jev-latest','data':data if isinstance(data,dict) else None}

    def call(self,name,args,saved=None):
        key='voice-intake-'+uuid.uuid4().hex
        self.pending[key]={'name':name,'dialogue':getattr(self,'dialogue',[]),'saved':saved}
        record('tool_requested',tool=name,call_id=key)
        return {'output':[{'type':'function_call','call_id':key,'name':name,'arguments':json.dumps(args,ensure_ascii=False)}],
                'backend':'jev_intake','model':'jev-latest'}

    async def respond(self,items,tools,instructions,on_text=None):
        if self.closed:raise ValueError('音声接続は終了しています')
        results=[i for i in items if i.get('type')=='function_call_output']
        if results:
            texts=[];names=[]
            for item in results:
                pending=self.pending.pop(item.get('call_id'),None)
                if not pending:raise ValueError('処理済みまたは不明な道具結果です')
                name=pending['name'];names.append(name)
                data=json.loads(item.get('output') or '{}')
                record('tool_result',tool=name,call_id=item.get('call_id'),
                    result_chars=len(item.get('output') or ''),error_type='tool_error' if data.get('error') else None,
                    message_count=len(data.get('messages',[])))
                if name=='web_search':
                    from app.services.voice_search_reader import SearchReader
                    if not self.search_reader or self.search_reader.agent.closed:
                        self.search_reader=SearchReader()
                    if pending.get('saved'):
                        from app.services.personal_info_service import PersonalInfoService
                        service=PersonalInfoService();facts=[]
                        for k in pending['saved'][:3]:
                            found=await service.get(self.user_id,k)
                            if found and found.get('value'):facts.append({'label':found.get('label') or k,'value':str(found['value'])[:500]})
                        if facts:
                            from app.services.voice_readings import annotate
                            data={**data,'saved_information':annotate(facts)}
                    from app.services.user_location import place_for_speech,home_area
                    place=place_for_speech(self.user_id) or await home_area(self.user_id)
                    if place:data={**data,'place':place}
                    return await self.search_reader.read(pending['dialogue'],data,on_text)
                if data.get('error'):texts.append('確認できませんでした: '+str(data['error'])[:500])
                elif data.get('accepted'):texts.append('（裏側の状態）作業は開始済み。結果は届き次第別に伝わる。今、本人に伝える新しい事実はない。')
                elif name=='enter_voice_standby':texts.append('通話を終了します。')
                else:texts.append(json.dumps(spoken_result(data),ensure_ascii=False))
            result=self.message('\n'.join(texts))
            # An acceptance or a control acknowledgement is context, not something to say: the speech model already knows it delegated.
            if all(n in ('delegate_to_dan','control_dan_task') for n in names):result['silent']=True
            return result
        dialogue=dialogue_from(items)
        self.dialogue=dialogue
        utterance=next((r['text'] for r in reversed(dialogue) if r['role']=='user'),'').strip()
        if not utterance:return self.message('依頼の内容をもう一度お願いします。')
        jobs=await asyncio.to_thread(list_owned,self.user_id,self.room_id)
        active=[s for s in jobs if s['state'] not in ('completed','failed','cancelled')]
        candidates={s['id']:s['task'][:180] for s in active}
        routes=dict(ROUTES)
        if not active:
            for name in ('pause','cancel','update','confirm','status'):routes.pop(name)
        proposals=[s for s in active if s['state']=='awaiting_confirmation' and s.get('confirmation')]
        qs={'route':{'type':'choice','instructions':'最新の発言の意図を直前の会話と対象から選ぶ。予約の取消を新たに頼むのはwork、実行中の仕事を止めるのはcancel。分類は実行の承認を意味しない。', 'criteria':routes},
            'target':{'type':'choice','instructions':'最新発言が指す既存の仕事を選ぶ。別件・新規作業・対象不明ならnone。','criteria':{**candidates,'none':'特定の既存仕事ではない'}}}
        if not candidates:qs.pop('target')
        # The route is one label, but a request is often a combination (「JR尼崎駅と郵便番号同じ?」 = saved fact + search).
        # Ask for each material separately, in the same call, so nothing is lost to the single choice.
        qs['web']={'type':'choice','instructions':'最新の発言に正しく答えるのに、ウェブで調べる必要があるかを選ぶ。',
            'criteria':{'needed':'外部の最新情報や一般の事実（店・駅・施設・会社・商品・天気・ニュース・価格・制度・他人や他社の情報など）を調べないと答えられない。本人の情報と外の情報を比べる質問もここ。',
                        'not_needed':'本人の保存情報、今の会話、過去の会話や作業の記録だけで答えられる。雑談・相づち・実作業の依頼・進行中の仕事への指示もここ。'}}
        qs['act']={'type':'choice','instructions':'最新の発言が、ダンに何かを実行してほしいという依頼かを選ぶ。',
            'criteria':{'do':'保存・登録・訂正・送信・連絡・予約・購入・注文・操作・ログインして確認など、ダンに実際の作業をしてほしいと頼んでいる。',
                        'no':'質問（教えて・何だっけ・どうなった）、調べもの、雑談、相づち、感想、通話の終了。'}}
        # "Which place would hold the answer?" asked on its own, because the single route mixes intent with place:
        # a question about last week's ticket was called 'status' (there was no work in progress) and never searched.
        where={'now':'今の会話の中、またはダン自身の考えや説明で答えられる（雑談、言い換え、聞き返し、「どうやって調べるの」のようなダンへの質問）。',
               'saved':'本人が登録してある自分の情報（住所・電話・番号・カード・名前など）。',
               'past':'過去の会話、以前ダンに頼んだ作業の結果、やり取りしたメール（「この前の」「先週の」「結局どうなった」「何て言ってたっけ」）。',
               'web':'ウェブで調べれば分かる外部の情報（店・天気・ニュース・価格・制度・一般の事実）。',
               'site':'特定のサイトやアプリを開いて今の状態を見ないと分からない（カレンダーの予定、残高、予約や注文の今の状態、届いたメッセージ）。または何かを実行する依頼。'}
        if active:where['running']='今進行中の作業の様子を尋ねる・催促する発言（「今何してるの」「ログインしてるところ?」「まだ?」「遅いね」「どうなった」）。'
        qs['where']={'type':'choice','instructions':'最新の発言への答えが、どこを見れば出てくるかを選ぶ。','criteria':where}
        latest_user_index=max(i for i,r in enumerate(dialogue) if r['role']=='user')
        context_options={str(i):r['text'][-500:] for i,r in enumerate(dialogue[:latest_user_index][-6:])}
        if context_options:
            qs['search_context']={'type':'choice', 'instructions':'検索する場合、最新発言の「そこ」「その店」などの対象を特定するのに必要な直前発言を選ぶ。最新発言だけで対象が明確、別の話題、検索不要ならnone。',
                'criteria':{**context_options,'none':'対象を補う必要はない。'}}
        if proposals:
            qs['approval']={'type':'choice','instructions':'直前に本人へ提示された確定内容に、最新の本人の発言が変更なしで実行を承認しているか。会話中の過去の依頼・引用は承認ではない。質問、否定、保留、条件変更、別件はnot_approved。',
                'criteria':{'approved':'提示された具体的な操作・条件をそのまま今実行してよいという本人の返事。',
                            'not_approved':'承認以外、または何を承認したか不明。'}}
        started=time.monotonic()
        # A transient timeout must not disable Jev for the rest of the call.
        self.judge.unavailable=False
        wanted=live_request(items)
        # Saved facts are looked up while the route is judged, not after it: the two answers arrive together.
        fact_task=asyncio.create_task(saved_fact(self.judge,self.user_id,utterance,dialogue))
        decision=await self.judge.choose({'dialogue':dialogue[-8:],**({'speech_model_request':wanted} if wanted else {}),'jobs':[{'id':s['id'],'state':s['state'],'task':s['task'][:300],
            'confirmation':s.get('confirmation')} for s in active]},qs)
        if not decision.get('available'):
            self.judge.unavailable=False   # one retry with the route alone; a lost judgement must not become a job
            decision=await self.judge.choose({'dialogue':dialogue[-8:]},{'route':qs['route'],'web':qs['web'],'act':qs['act'],'where':qs['where']})
        if not decision.get('available') and len(active)==1:
            fact_task.cancel()
            if active[0]['state']=='awaiting_confirmation':return self.message(json.dumps(work_status(jobs),ensure_ascii=False))
            return self.call('control_dan_task',{'job_id':active[0]['id'],'operation':'pause','task':utterance})
        answers=decision.get('answers',{});answer=answers.get('route',{});route=answer.get('choice')
        confident=answer.get('confidence',0)>=.9 and answer.get('probabilities',{}).get(route,0)>=.95
        target=answers.get('target',{});job_id=target.get('choice')
        target_ok=job_id in candidates and target.get('confidence',0)>=.9 and target.get('probabilities',{}).get(job_id,0)>=.95
        approval=answers.get('approval',{})
        approved=approval.get('choice')=='approved' and approval.get('confidence',0)>=.9 and approval.get('probabilities',{}).get('approved',0)>=.95
        if approval.get('choice')=='approved' and not approved and len(proposals)==1 and len(active)==1:
            # Resolve an ambiguous multi-question classification against the
            # specific proposal and reply, without old tasks or routing labels.
            focused=await self.judge.choose({'proposal':proposals[0]['confirmation']['summary'],
                'reply':utterance,'recent_dialogue':dialogue[-4:]},{'approval':qs['approval']})
            approval=focused.get('answers',{}).get('approval',{})
            approved=approval.get('choice')=='approved' and approval.get('confidence',0)>=.9 and approval.get('probabilities',{}).get('approved',0)>=.95
        logger.info('voice_intake route=%s confident=%s target=%s elapsed_ms=%d',route,confident,target_ok,(time.monotonic()-started)*1000)
        record('routed',route=route,elapsed_ms=round((time.monotonic()-started)*1000))
        if approved and (target_ok or len(active)==1):
            s=next((s for s in proposals if s['id']==(job_id if target_ok else active[0]['id'])),None)
            if s:
                finalized=final_input(items)
                if finalized is None:
                    finalized=await saved_final_reply(self.user_id,self.room_id,utterance,s['confirmation'])
                if not finalized:
                    return {'output':[],'backend':'jev_intake','awaiting_final_input':True}
                from app.services.voice_approval import issue
                return self.call('control_dan_task',{'job_id':s['id'],'operation':'confirm','task':utterance,'confirmation_id':s['confirmation']['id'],
                    'voice_approval':issue(self.user_id,self.room_id,s['id'],s['confirmation']['id'],utterance)})
        web=answers.get('web',{}).get('probabilities',{}).get('needed',0)
        # 「更新のハガキいつごろ届く感じ?」 was judged a progress question; with no work in progress and the web needed, it is a search.
        if route=='status' and not active and web>=SEARCH_BAR:route='search'
        place=answers.get('where',{}).get('probabilities') or {}
        # 「二十四日の予定入ってるよね」 while the ticket job ran was called 'status' three times and answered with the ticket job.
        # 「今ログインしようとしてるの?」 is about the running job even when the single route called it small talk.
        if active and place.get('running',0)>=.5 and route in ('other','conversation',None):route='status'
        if route=='status' and place.get('running',0)<.3:
            if place.get('site',0)>=.6:route='work'
            elif place.get('past',0)>=WHERE_BAR:route='history'
            elif web>=SEARCH_BAR:route='search'
        if route=='status':
            fact_task.cancel()
            return self.message(json.dumps(work_status(jobs),ensure_ascii=False))
        # A request to recall something is not a request for a fixed recent page.
        # The existing worker has memory/file/cross-room tools; pass the original
        # question directly to it rather than making Live loop over 30 messages.
        # 「電話切れ」 twice, 'end' both times, under the bar both times: the owner had to kill the call by hand.
        if route=='end' and (confident or answer.get('probabilities',{}).get('end',0)>=.5 or HANG_UP.search(utterance)):
            fact_task.cancel()
            return self.call('enter_voice_standby',{})
        if HANG_UP.search(utterance) and route in (None,'other','conversation','cancel','pause'):
            fact_task.cancel()
            return self.call('enter_voice_standby',{})
        if confident and target_ok and route in ('pause','cancel','update'):
            args={'job_id':job_id,'operation':route,'task':utterance}
            return self.call('control_dan_task',args)
        if route in ('update','pause','cancel') and len(active)==1 and job_id==active[0]['id']:
            # An uncertain classification is not permission to cancel or confirm,
            # but it must not swallow the user's words. Deliver the original
            # follow-up to the existing worker to interpret; update invalidates
            # any previous transaction approval.
            return self.call('control_dan_task',{'job_id':job_id,'operation':'update','task':utterance})
        # ---- materials, not a single branch ---------------------------------------------------------------------
        # Measured live: 「俺の住所教えて」 is routed to 'other', follow-ups like 「最後まで全部言って」 to 'conversation',
        # and 「JR尼崎駅と郵便番号同じ?」 to 'conversation' with a saved-fact hit, which answered the postcode alone and
        # left the speech model saying "I can't tell from what is registered" until the owner ordered a search.
        act=answers.get('act',{}).get('probabilities',{}).get('do',0)
        # A request to act (「O型だから保存しといて」) is work even when the single route said small talk; a question routed as
        # 'work' with no action in it (「何番で登録してたっけ」) is still a question.
        # A request about the conversation itself (speak English, slower, louder) is the speech model's, not a job.
        if route in ('other','conversation') and act>=ACT_BAR and web<SEARCH_BAR and place.get('now',0)<.5:route='work'
        elif route=='work' and ((act<.5 and not confident) or place.get('saved',0)>=.6):route='history'
        record('where',route=route,place={k:round(v,2) for k,v in place.items() if v>=.05})
        if route in MATERIAL_ROUTES or (route=='work' and act<.5 and not confident):
            if place.get('past',0)>=WHERE_BAR:route='history'
            # live: 「今日の予定教えて」 site .89, 「先月のカードの請求」 .95, 「注文した水、今どこ」 1.0 — none of them phrased as an order
            elif place.get('site',0)>=.8:route='work'
            elif place.get('now',0)>=.7 and web<SEARCH_BAR and route=='search':route='conversation'
        fact=None
        if route in MATERIAL_ROUTES:
            try:fact=await fact_task
            except Exception:fact=None
        else:fact_task.cancel()
        about_self=bool(fact and fact.pop('asked_about_self',None))
        if about_self and not fact:fact=None
        here=bool(fact and fact.pop('here',None))
        if here:fact=None
        role=fact.pop('role','answer') if fact else None
        keys=fact.pop('keys',None) if fact else None
        searchable=len(utterance)<=400 and (route=='search' or web>=SEARCH_BAR)
        if fact and role=='ingredient' and not searchable:fact=keys=None   # an ingredient alone answers nothing
        saved=(fact or {}).get('saved_information')
        more=0
        if saved and role=='answer' and searchable:
            more=await answers_it(self.judge,utterance,dialogue,[f['label'] for f in saved])
        again=bool(self.answered and self.answered[0]==utterance)   # the speech model asked again: the last materials were not enough
        rung=self.answered[1] if again else 0
        record('materials',route=route,web=round(web,2),act=round(act,2),saved=role if saved else None,needs_outside=round(more,2),again=again,request_chars=len(wanted))
        if route in MATERIAL_ROUTES:
            if not decision.get('available') and not saved:
                self.answered=None
                return self.message(json.dumps({'status':'intent_not_judged','conversation':'裏側で内容を判定できませんでした。雑談なら自然に返し、調べものや作業の依頼だったなら、もう一度言ってもらってください。'},ensure_ascii=False))
            searching=(searchable and (not saved or role=='ingredient' or more>=OUTSIDE_BAR)) or (again and rung==1 and len(utterance)<=400)
            if searching and rung<2:
                from app.services.voice_search_reader import SearchReader
                if not self.search_reader or self.search_reader.agent.closed:
                    self.search_reader=SearchReader()
                context_key=answers.get('search_context',{}).get('choice')
                context=context_options.get(context_key,'')
                query=(context[-max(0,399-len(utterance)):]+'\n'+utterance) if context and len(utterance)<399 else utterance
                if here:
                    # The town the phone reported (or the home town when it never did) names the place the words left out.
                    from app.services.user_location import place_for_speech,home_area
                    place=place_for_speech(self.user_id) or await home_area(self.user_id)
                    if place:query=(place['current_place']+' '+query)[:400]
                self.answered=(utterance,2)
                # Saved values reach the reader with the results: never in the search query, and only their keys in the persisted call.
                return self.call('web_search',{'query':query},saved=keys)
            if route in ('conversation','other') and not fact and not again and ASKING.search(utterance) and (about_self or place.get('saved',0)+place.get('past',0)>=.5):route='history'   # a question about the owner or the past, not small talk
            if route=='history' and not fact and rung<2:
                # A question about the past: the records are a keyword search away (about a second), not a delegated job.
                from app.services.voice_past import gather
                from app.services.voice_search_reader import SearchReader
                found=await gather(self.user_id,utterance,dialogue,jobs)
                record('past',keywords=len(found['keywords']),records=len(found['records']),jobs=len(found['jobs']),elapsed_ms=found['elapsed_ms'])
                if found['records'] or found['jobs']:
                    if not self.search_reader or self.search_reader.agent.closed:self.search_reader=SearchReader()
                    self.answered=(utterance,2)   # asked again -> Dan itself looks (sites, mail)
                    return await self.search_reader.read(dialogue,{'past_records':found['records'],'recent_work':found['jobs']},on_text)
            if fact and rung<2:
                kind=next(iter(fact))
                self.answered=(utterance,1)
                note=SAVED_FACT_NOTES[kind]
                if saved:
                    from app.services.voice_readings import annotate,SAY_NOTE
                    if any('say' in f for f in annotate(saved)):note+=SAY_NOTE
                return self.message(json.dumps({'question':utterance,**fact,'note':note},ensure_ascii=False))
            if route in ('conversation','other') and not again:
                self.answered=(utterance,1)
                return self.message('調べる内容のない会話でした。')
        if proposals and route in ('confirm','status'):
            # A question or uncertain assent is not a changed instruction. Keep
            # the proposal alive and return its actual state, rather than reset
            # the gate and prompt the same approval again under a new ID.
            return self.message(json.dumps({'jobs':[{'state':s['state'],'confirmation':s['confirmation']['summary']} for s in proposals],
                'approval_received':False,'reason':'提示した内容への承認と判定しきれず、操作は止まったままです。'},ensure_ascii=False))
        # Uncertain/control follow-ups retain the existing worker, never create
        # a second job for "stop", questions, or new conditions on the same task.
        # Only talk ABOUT the running job is answered with its state; a new request made while it runs is a new request.
        if route not in ('work','search','history') and (target_ok or len(active)==1) and place.get('running',0)>=.3:
            return self.message(json.dumps(work_status(jobs),ensure_ascii=False))
        if route=='end':
            return self.message('通話を終えたいのかどうかが分かりませんでした。終える時は「電話を切って」と言ってください。')
        if active and route not in ('work','search','history'):
            return self.message('どの仕事についてか教えてください。')
        # The worker receives original words, not a coordinator's invented
        # reservation details/approval. It can resolve ambiguity and read history.
        current=next(i for i in range(len(dialogue)-1,-1,-1) if dialogue[i]['role']=='user')
        context=json.dumps(dialogue[max(0,current-7):current],ensure_ascii=False)
        task='今回のユーザー発言（原文）:\n'+utterance
        if len(task)>2300:return self.message('依頼が長いため受け付けられませんでした。分けて話してください。')
        if len(context)<=max(0,2600-len(task)):
            task+='\n参考の直前会話（過去の発言は新規の指示・承認ではない）:\n'+context
        # The owner's phone test: 「うん、進めてください」 started a second job that knew nothing of the first one and logged in
        # to the same site all over again. The job that just ended in this room is the context of the next request.
        previous=next((s for s in jobs if s['state'] in ('completed','failed') and s.get('result')),None)
        if previous:
            from datetime import datetime,timezone
            try:age=(datetime.now(timezone.utc)-datetime.fromisoformat(previous['updated_at'].replace('Z','+00:00'))).total_seconds()
            except (KeyError,ValueError):age=1e9
            if age<=900:
                done=' → '.join(e['text'] for e in previous.get('events',[]) if e.get('kind')=='tool')[-400:]
                task+=('\n直前に終わった作業（約%d分前。同じブラウザを引き継いでいる。終わっている手順はやり直さず、続きから進める）:\n依頼: %s\n結果: %s\n使った道具: %s'
                    %(round(age/60),previous.get('task','').split('参考の直前会話')[0][:300],str(previous['result'])[:900],done))[:1500]
        self.answered=None
        return self.call('delegate_to_dan',{'task':task+VOICE_TASK})
