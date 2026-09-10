"""The editor's conversation authority. Realtime only transports speech."""
from __future__ import annotations
import copy
import json
from openai import AsyncOpenAI
from app.config import settings
from app.services.editor_production_contract import BUDGET

MODEL = 'gpt-6-astra'
INSTRUCTIONS = '''あなたは動画エディターの中でユーザーと話すダンです。会話原文から目的と現在の話題を理解し、質問・提案・検索・編集を行います。返答はそのまま音声にもなります。平易な日本語で自然に話してください。
画面の状態は背景情報です。画面について尋ねられていない会話を画面説明へ変えないでください。本人の発言と自分の案を区別し、仮の案を合意条件にしないでください。
既存素材の取り込みはimport_media、タイムラインへの配置・カット・字幕・音・効果の編集はbatch_editで直接実行できます。操作仕様は道具の引数にあります。検索や小さな編集は手元の道具で実行できます。長い制作、調査、素材生成、PC操作はexecute_workへ渡せます。アプリが会話原文と参考情報を自動で渡すので、長い依頼書や会話の要約を作る必要はありません。補足は必要な作業上の短い説明だけです。調査は依頼達成の途中の手順であり、制作を頼まれたら調査だけで終了する仕事に変えません。
作業が続いている間も質問に答えられます。依頼の変更ならexecute_workで進行中の仕事へ届け、担当からの質問への答えならanswer_questionを使います。発話の割り込みを制作停止と解釈しません。停止を求められた時はstop_productionを使います。
すぐ答えられる質問は直接答えてください。時間のかかる道具を使うときは、必要なら短い一文を先に返してから実行できます。毎回の定型的な待機文や、操作ごとの実況は不要です。実行結果は短く伝えます。未表示・未完成のものを表示・完成したと言わず、結果が不足していれば確認します。
ユーザーが考え中・独り言ならwait_for_userで待ちます。目的と参考が分かり見本を任されたら演出を判断して形にし、判断をユーザーへ繰り返し返しません。参考例は検索・取得してpresent_referencesで実物を見せます。
編集範囲は既存の選択と保護に従います。全体制作を明示されたときはset_project_scope。音声の編集ツールは指定されたクリップを操作と同時に対象として結びます。対象が明確なら直接編集できます。resolve_targetは編集せず対象だけを結ぶ場合、propose_targetは曖昧で確認が必要な場合に使います。テキストの編集は選択範囲を使います。
''' + BUDGET

def tools_for_conversation(original):
    result=[]
    for source in original:
        if source['name'] in {'save_brief','timeline_edit'}:continue
        t=copy.deepcopy(source)
        if t['name']=='batch_edit':
            from app.timeline_mcp_server import tool_definitions
            from app.services.timeline_live import FAST_OPS
            options=[]
            for spec in tool_definitions():
                if spec.name not in FAST_OPS:continue
                parameters=copy.deepcopy(spec.inputSchema)
                for key in ('clip_id','source_clip_id'):
                    if key in parameters.get('properties',{}):
                        parameters['properties'][key]={'anyOf':[parameters['properties'][key],{'type':'object','properties':{'$result':{'type':'integer','minimum':0},'path':{'type':'string'}},'required':['$result','path'],'additionalProperties':False}]}
                options.append({'type':'object','properties':{'op':{'type':'string','enum':[spec.name],'description':spec.description},'args':parameters},'required':['op','args']})
            t['parameters']={'type':'object','properties':{'operations':{'type':'array','minItems':1,'maxItems':20,'items':{'anyOf':options}}},'required':['operations']}
            t['description']='タイムラインを直接編集し、直ちに画面へ反映する。素材配置・カット・字幕・音量・枠・ぼかし・画像の変更に使う。生成待ちは不要。各操作の引数は以下の仕様。作成結果のIDは {"$result":0,"path":"clip_id"} でこのバッチの先行操作を参照できる。失敗時は全変更を戻す。'
        if t['name']=='delegate_edit':
            t['name']='execute_work'
            t['description']='依頼を達成する長い仕事を開始、または進行中の同じ仕事へ変更を送る。調査・接続・素材生成・制作・検品・表示まで必要な工程を続ける。会話原文・参考・状態はアプリが自動で渡す。'
            t['parameters']['properties'].pop('task_kind',None)
            t['parameters']['required']=[]
            t['parameters']['properties']['instruction']['description']='必要な場合だけ短い作業上の補足。会話の要約や詳しい制作手順は不要。'
        result.append({'type':'function','name':t['name'],'description':t['description'],
                       'parameters':t['parameters'],'strict':False})
    result.append({'type':'function','name':'read_conversation','description':'この作品の会話原文を話者付きで読む。古い会話はbeforeで遡れる。通常チャットは自動で取り込まない。',
        'parameters':{'type':'object','properties':{'before':{'type':'number'},'limit':{'type':'integer'}},'required':[]},'strict':False})
    return result

def initial_input(context, dialogue):
    inputs=[{'role':'system','content':json.dumps({'editor_context':context,'history_note':'直近の会話原文です。必要な古い会話はread_conversationで読めます。'},ensure_ascii=False)}]
    for row in dialogue:
        if row.get('role') in {'user','assistant'} and row.get('text'):
            inputs.append({'role':row['role'],'content':row['text']})
    utterance=context.get('utterance','')
    if utterance and (len(inputs)==1 or inputs[-1].get('role')!='user' or inputs[-1].get('content')!=utterance):
        inputs.append({'role':'user','content':utterance})
    return inputs

async def stream_response(inputs, tools):
    async with AsyncOpenAI(api_key=settings.OPENAI_API_KEY,timeout=120,max_retries=0) as client:
        stream=await client.responses.create(model=MODEL,instructions=INSTRUCTIONS,input=inputs,
            tools=tools,reasoning={'effort':'high'},max_output_tokens=4096,stream=True,store=False)
        async for event in stream:
            if event.type=='response.output_text.delta':yield {'type':'text','delta':event.delta}
            elif event.type=='response.completed':
                output=[{k:v for k,v in o.items() if k!='status'} for o in event.response.model_dump()['output']]
                yield {'type':'completed','output':output,'usage':event.response.usage.model_dump() if event.response.usage else None}
            elif event.type in {'response.failed','response.incomplete','error'}:
                raise RuntimeError('会話の応答を完了できませんでした: '+str(event)[:600])
