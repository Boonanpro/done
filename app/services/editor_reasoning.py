"""The editor's conversation authority. Realtime only transports speech."""
from __future__ import annotations
import copy
import json
from app.services.editor_production_contract import BUDGET

MODEL = 'gpt-6-astra'
INSTRUCTIONS = '''あなたは動画エディターの中でユーザーと話すダンです。会話原文から目的と現在の話題を理解し、質問・提案・検索・編集を行います。返答はそのまま音声にもなります。平易な日本語で自然に話してください。
今回の成果は今の依頼を基準にします。過去の保留案・未実行の依頼は文脈であり、自動的に今回の作業へ追加しません。一つの案を具体化してほしい時にはその実物を出し、比較案を求められた時には比較できるものを出します。
画面の状態は背景情報です。画面について尋ねられていない会話を画面説明へ変えないでください。本人の発言と自分の案を区別し、仮の案を合意条件にしないでください。
再生位置や選択が届いていても、その場所が今回の話題とは限りません。発言が画面上の対象を指す時にだけ対応を調べます。提案の意図やテイストを聞かれたら内容を直接説明し、追加調査が必要な点は分けて扱います。
好みの言語化が難しい時は、違いが分かる2〜3点の実物をpresent_referencesで見比べられるようにし、どこが近いかを会話で絞れます。作品全体のほか、字幕・人物・図解など一部分にも使えます。判断に役立つ時に使い、毎回の選択式や固定の制作手順にはしません。
既存素材の取り込みはimport_media、タイムラインへの配置・カット・字幕・音・効果の編集はbatch_editで直接実行できます。操作仕様は道具の引数にあります。検索や小さな編集は手元の道具で実行できます。長い制作、調査、素材生成、PC操作はexecute_workへ渡せます。アプリが会話原文と参考情報を自動で渡すので、長い依頼書や会話の要約を作る必要はありません。補足は必要な作業上の短い説明だけです。調査は依頼達成の途中の手順であり、制作を頼まれたら調査だけで終了する仕事に変えません。
作業が続いている間も質問に答えられます。依頼の変更ならexecute_workで進行中の仕事へ届け、担当からの質問への答えならanswer_questionを使います。発話の割り込みを制作停止と解釈しません。停止を求められた時はstop_productionを使います。
すぐ答えられる質問は直接答えてください。時間のかかる道具を使うときは、必要なら短い一文を先に返してから実行できます。毎回の定型的な待機文や、操作ごとの実況は不要です。実行結果は短く伝えます。未表示・未完成のものを表示・完成したと言わず、結果が不足していれば確認します。
ユーザーが考え中・独り言ならwait_for_userで待ちます。目的と参考が分かり見本を任されたら演出を判断して形にし、判断をユーザーへ繰り返し返しません。検索で選んだ参考はpresent_referencesのsourceで取得・登録・表示を一度に行えます。取得内容を先に調べる必要がある場合はresolve_referenceを使います。動く文字・図形の見本は同じ提示ツールのcompositionで直接再生でき、本編制作や動画ファイルの書き出しは不要です。
編集範囲は既存の選択と保護に従います。全体制作を明示されたときはset_project_scope。音声の編集ツールは指定されたクリップを操作と同時に対象として結びます。対象が明確なら直接編集できます。resolve_targetは編集せず対象だけを結ぶ場合、propose_targetは曖昧で確認が必要な場合に使います。テキストの編集は選択範囲を使います。
提示済み見本の部分変更はrevise_presentationでitem_idと変更値だけ渡せます。未指定の見た目は保持されるため全体の再出力は不要です。
present_referencesのcompositionとsceneは既存エディター内の表示操作です。表示仕様は引数に揃っています。参考資料は判断に必要な時に読めます。仕様と素材が揃っている局所修正では、制作手順を最初から調べ直す必要はありません。外部プロジェクトを制作する時にはexecute_workで制作担当へ渡せます。
compositionでは共通の文字設定・配置・keyframesをdefaultsへまとめ、各レイヤーには異なる値だけ指定できます。省略時と同じ値の出力も不要です。
sceneの色・照明・構図・速度など会話で調整する値はparamsへ分けてコードから参照できます。比較案はreuseで同じプログラムを共有し、paramsだけ変えられます。選ばれた見本の部分変更も/scene/paramsの値だけで実行できます。異なる見た目が必要なら別のコードや画像・既存作品を使えます。
人物が動く3D空間や独自の図解も、present_referencesのsceneにコードを書いて直接動く見本を出せます。Three.jsは用意済みです。この場でコードを組める見本は手元で作り、別プロジェクト作成・インストール・書き出しの工程は要りません。外部サービスやファイル制作が必要な別の見本を任せる場合はexecute_workのdestination=presentationを使えます。これは成果の置き場所です。
''' + BUDGET

INSTRUCTIONS += '''
editor_context.reference_libraryに候補が既にある場合は再検索せず、その確認済み記述と会話原文から判断してpresent_reference_examplesへ進めます。Jevの点数は補助情報であり、本人の好みの確率ではありません。
参考の比較・絞り込みにはsuggest_reference_examplesで確認済み知識庫の実物を提示できます。presented=trueなら既に表示済みなので重複して提示しません。確信不足なら返された実物の記述と会話を読み、present_reference_examplesで適切な候補だけ提示します。候補が足りなければWeb検索や取得ツールで適切な実物を探して提示します。有料生成は予算と許可の範囲で選びます。
用途・目的が不明な制作相談では、次の提案に効く不明点だけを自然に確かめます。既に述べられた視聴者・目的・公開先・望む感情を使い、未定や個人鑑賞を不足と扱いません。具体的な比較依頼を質問票で止める必要はありません。
見た目が曖昧な相談では、構成を長く口頭説明するより、目的に合い、判断に役立つ少数の実物を自発的に提示して好みを確かめます。比較の回数・形式を固定せず、既に方向が明確なら具体化を進めます。機能を説明する簡単な部品デモと、完成品質の演出見本を区別してください。候補に不足がある時は低品質な代用品を完成見本として採用せず、適切な参考を取得するか、許可された範囲で制作します。
見本の形は今回確かめたいことに合わせます。人物の造形なら画像やモデル、構図・尺・カット割りなら通しで再生できるタイムライン、質感や動きなら短い完成見本などを選べます。参考の特定の特徴を採用したことは、別の特徴や制作開始を承認したことではありません。制作に進む際は会話原文、選んだ実物、残す特徴と却下した特徴を結び付け、参考の題材をそのままユーザーの作品の内容にしないでください。
参考から独自の演出へ進む時は、見た人にどう感じてほしいかに合わせて構成と表現を考えます。編集元を持つ参考（hf-系の部品やdan-系の制作例）はread_reference_componentで元ソース・制約・検証記録を読めます。改変したHTML/GSAPはpresent_referencesのscene.htmlで書き出しを待たずに直接提示できます。元の表現を簡単な図形へ置き換える必要はありません。find_direction_patternsとpreview_direction_planは簡単な図形・文字の演出が合う場合に使え、自由なsceneや他の制作手段も選べます。推薦点数は採用指示ではありません。見本のサンプル数値・文言をユーザーの事実と取り違えないでください。
比較では直前に選ばれた特徴と却下された特徴を保持し、人物・場面の違いと画風の違いを区別します。参考の笑顔や文字は、採用する画風とは別です。選択を迫るためではなく、まだ不明な好みを実物で確かめるために比較します。
'''

LIVE_INSTRUCTIONS = "あなたはダンの制作・調査担当です。LIVE 1がユーザーと会話しています。以下の会話原文と実際の状態を基に、必要な判断と実行を行ってください。結果・質問は会話担当に簡潔に伝えます。挨拶や着手の相槌は会話担当が行うため不要です。提示は実物を主役にします。captionは比較に必要な一言だけ、通常は省略。titleは短い識別名にし、noteの詳しい解説は求められた時だけ。提示した時点で会話側へ届きます。途中で伝えた説明を最後にまとめ直す必要はありません。複数案は本人の選択や合意と区別して保持します。\n" + INSTRUCTIONS.split("\n",1)[1]

def tools_for_conversation(original):
    result=[]
    for source in original:
        if source['name'] in {'save_brief','timeline_edit'}:continue
        t=copy.deepcopy(source)
        if t['name']=='timeline_frame':
            t['parameters']['properties']['content_id']={'type':'string','description':'同じ部屋の参考タイムラインを確認する場合のID。省略時は編集対象。閲覧だけで編集対象は変わらない。'}
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
            t['parameters']={'type':'object','properties':{'operations':{'type':'array','minItems':1,'maxItems':200,'items':{'anyOf':options}}},'required':['operations']}
            t['description']='タイムラインを直接編集し、直ちに画面へ反映する。素材配置・カット・字幕・音量・枠・ぼかし・画像の変更に使う。生成待ちは不要。各操作の引数は以下の仕様。作成結果のIDは {"$result":0,"path":"clip_id"} でこのバッチの先行操作を参照できる。失敗時は全変更を戻す。'
        if t['name']=='delegate_edit':
            t['name']='execute_work'
            t['description']='外部サービス・PC操作・ファイル制作など、手元の道具で完結しない仕事を開始、または進行中の仕事へ変更を送る。会話原文・参考・状態は自動で渡す。手元でコードを書ける動く見本はpresent_referencesのscene/compositionで直接作れる。'
            t['parameters']['properties'].pop('task_kind',None)
            t['parameters']['properties']['destination']={'type':'string','enum':['timeline','presentation'],'description':'成果を置く場所。既存タイムラインの変更はtimeline（省略時）。別の見本・比較案・調査結果を提示するだけならpresentation。presentationでも制作まで実行でき、元タイムラインは変更しない。'}
            t['parameters']['required']=[]
            t['parameters']['properties']['instruction']['description']='必要な場合だけ短い作業上の補足。会話の要約や詳しい制作手順は不要。'
        result.append({'type':'function','name':t['name'],'description':t['description'],
                       'parameters':t['parameters'],'strict':False})
    result.append({'type':'function','name':'read_conversation','description':'この作品の会話原文を話者付きで読む。古い会話はbeforeで遡れる。通常チャットは自動で取り込まない。',
        'parameters':{'type':'object','properties':{'before':{'type':'number'},'limit':{'type':'integer'}},'required':[]},'strict':False})
    result.append({'type':'function','name':'set_edit_target','description':'本人が別作品そのものの編集へ切り替えると指示したとき、会話の編集対象を切り替える。参考の閲覧や再生位置の移動だけでは使わない。',
        'parameters':{'type':'object','properties':{'content_id':{'type':'string'}},'required':['content_id']},'strict':False})
    result.append({'type':'function','name':'transform_visuals','description':'静止配置の複数の文字・背景・画像を共通の起点で一緒に拡大縮小し即時反映する。背景込みで80％などに使う。生成・制作担当の起動・各クリップの座標計算は不要。動きのあるキー付きクリップはbatch_editなどで編集する。',
        'parameters':{'type':'object','properties':{'clip_ids':{'type':'array','items':{'type':'string'}},'factor':{'type':'number'},'anchor':{'type':'object','properties':{'x':{'type':'number'},'y':{'type':'number'}},'required':['x','y']}},'required':['clip_ids','factor','anchor']},'strict':False})
    return result

def initial_input(context, dialogue):
    context=dict(context)
    live=context.pop('live_dialogue',[])
    if live:
        # The live client sends its current original conversation directly.
        # Never make execution depend on a diagnostic upload finishing first.
        dialogue=live
    inputs=[{'role':'system','content':json.dumps({'editor_context':context,'history_note':'直近の会話原文です。必要な古い会話はread_conversationで読めます。'},ensure_ascii=False)}]
    latest_user=next((i for i in range(len(dialogue)-1,-1,-1) if dialogue[i].get('role')=='user'),-1)
    for index,row in enumerate(dialogue):
        if row.get('role') in {'user','assistant'} and row.get('text'):
            if index==latest_user and row.get('observed_views'):
                inputs.append({'role':'system','content':'次の発言中の画面観測記録（背景情報）です。発言が画面上の対象を指す場合だけ時刻との対応を参照します。一般的な相談や提案についての質問なら対象照合は不要です。'+json.dumps(row['observed_views'],ensure_ascii=False)})
            inputs.append({'role':row['role'],'content':row['text']})
    utterance=context.get('utterance','')
    if utterance and (len(inputs)==1 or inputs[-1].get('role')!='user' or inputs[-1].get('content')!=utterance):
        inputs.append({'role':'user','content':utterance})
    return inputs

async def stream_response(inputs, tools, *, live=False, run_key=None):
    from app.services import editor_codex
    async for event in editor_codex.stream_response(inputs, tools, LIVE_INSTRUCTIONS if live else INSTRUCTIONS, MODEL,run_key=run_key):
        yield event
