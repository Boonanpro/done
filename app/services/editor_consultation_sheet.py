"""Eight-field consultation sheet. Written by Live's Responses tools, never Jev."""
from copy import deepcopy

FIELDS = {'video_type':'動画の種類','subject':'題材','platform':'公開先','purpose':'作る目的',
          'audience':'想定する視聴者','duration':'尺','materials':'使いたい素材','references':'参考として選んだ作品'}
STATUSES = ('unknown','undecided','confirmed')

def empty():
    return {'version':3,'fields':{key:{'status':'unknown','value':''} for key in FIELDS},
            'reference_agreed':False,'ready_for_draft':False}

def update(previous, changes, reference_agreed=None):
    sheet=empty()
    if isinstance(previous,dict) and previous.get('version')==3:
        for key in FIELDS:
            value=previous.get('fields',{}).get(key,{})
            if value.get('status') in STATUSES and isinstance(value.get('value'),str):
                sheet['fields'][key]=deepcopy(value)
        sheet['reference_agreed']=previous.get('reference_agreed') is True
    if not isinstance(changes,list) or len(changes)>8:raise ValueError('changes must contain at most eight fields')
    for change in changes:
        key=change.get('field');status=change.get('status');value=change.get('value')
        if key not in FIELDS or status not in STATUSES or not isinstance(value,str) or len(value)>2000:
            raise ValueError('Invalid consultation field, status or value')
        value=value.strip()
        if status!='unknown' and not value:raise ValueError('A decided or deferred field needs a concise description')
        item={'status':status,'value':value if status!='unknown' else ''}
        if key=='references':
            ids=change.get('reference_ids',sheet['fields'][key].get('reference_ids',[]))
            if not isinstance(ids,list) or len(ids)>8 or any(not isinstance(i,str) or len(i)>200 for i in ids):
                raise ValueError('Invalid reference identities')
            item['reference_ids']=list(dict.fromkeys(ids)) if status!='unknown' else []
        if key=='references' and sheet['fields'][key]!=item:sheet['reference_agreed']=False
        sheet['fields'][key]=item
    if reference_agreed is not None:
        if not isinstance(reference_agreed,bool):raise ValueError('reference_agreed must be boolean')
        sheet['reference_agreed']=reference_agreed
    sheet['ready_for_draft']=sheet['reference_agreed'] and all(v['status']!='unknown' for v in sheet['fields'].values())
    return sheet

def tools():
    from app.services.editor_presentation import ITEM_SCHEMA
    from app.services.editor_presentation import REVISE_PROPERTIES
    from app.services.editor_film_plan import tools as film_tools
    def tool(name,description,properties,required):
        return {'type':'function','name':name,'description':description,'strict':False,
                'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}
    return film_tools() + [
        tool('revise_consultation_visual','提示した実物の指定箇所だけ変更する。場面のparamsなどを差分更新し、それ以外を保持。',REVISE_PROPERTIES,['item_id','changes']),
        tool('show_consultation_visual','Show a sketch, layout, short working motion sample, spatial camera study or story flow immediately. Use composition for animated text/shapes/images, scene for spatial motion. No production job or render. Use only when these editable primitives meet the decision need; this is not the full voiced timeline V-conte.',{
            'items':{'type':'array','minItems':1,'maxItems':4,'items':ITEM_SCHEMA}},['items']),
        tool('get_consultation_state','現在の作品の相談シート・表示済み参考・実行状況を読む。再接続時や必要な時に使用。',{},[]),
        tool('update_consultation_sheet','会話で分かった内容を簡潔に整理して記録する。原文の貼付や推測は禁止。変わった項目だけ更新。unknown=未確認、undecided=相談の結果未定で進める、confirmed=決定。参考検索結果は採用ではない。',{
            'changes':{'type':'array','maxItems':8,'items':{'type':'object','properties':{
                'field':{'type':'string','enum':list(FIELDS)},'status':{'type':'string','enum':list(STATUSES)},'value':{'type':'string'},'reference_ids':{'type':'array','items':{'type':'string'},'maxItems':8,'description':'IDs of the displayed references chosen by the user. Replace when direction changes.'}},'required':['field','status','value'],'additionalProperties':False}},
            'reference_agreed':{'type':'boolean','description':'ユーザーが参考の方向に同意した時true。方向変更で同意が失われたらfalse。'}},['changes']),
        tool('search_reference_library','Jevで既存の参考を検索し、実物を画面に提示する。採用済み参考は変更しない。',{
            'query':{'type':'string'},'scope':{'type':'string','enum':['work','component']},
            'refinement':{'type':'object','description':'When refining: preserve accepted traits and identify the remaining difference. Omit on initial exploration.',
                'properties':{'keep':{'type':'array','items':{'type':'string'}},
                              'change':{'type':'array','items':{'type':'string'}},
                              'next_axis':{'type':'string'}},'additionalProperties':False}},['query','scope']),
        tool('control_reference','表示済みの参考を再表示、再生、一時停止する。',{
            'item_id':{'type':'string'},'action':{'type':'string','enum':['reveal','play','pause']}},['item_id','action']),
        tool('run_editor_task','制作担当に編集・生成・高度な調査を依頼する。ユーザーの要望と合意をそのまま伝える。シート完成だけで勝手に本番生成しない。',{'task':{'type':'string'},'artifact':{'type':'string','enum':['look_frame','vconte','other'],'description':'Use look_frame for an image showing the actual finished appearance, or its revision; vconte for a full-length voiced animatic; other for editing or research.'}},['task']),
        {'type':'web_search'},
    ]

BACKEND_INSTRUCTIONS = '''音声会話のダンの判断と道具を担当します。自然に短く返答します。
制作相談シートはあなたがupdate_consultation_sheetで更新します。動画の種類、題材、公開先、目的、視聴者、尺、素材、採用した参考の8項目だけです。
会話で分かった情報を短い整理した文章にして、変わった項目を更新してください。題材と映像のテイスト、公開先と目的を混同しません。言い直しは該当項目を訂正し、矛盾しない内容は残します。未確認を未定と勝手に埋めません。「使いたい素材はない」もconfirmedの回答です。undecidedは後で決めると相談した項目に使います。
この通話で最初に依頼を受けたらget_consultation_stateで既存シートを読み、過去の会話から未記録の情報も整理します。その後は更新結果のシートを使い、不明な時だけ読み直します。旧形式のメモは採用済みの事実と扱いません。
新しい条件・回答・訂正・参考への同意は、今回の依頼内でupdate_consultation_sheetを実行して保存します。「記録する」と返答するだけでは保存されません。質問された項目以外の情報も同じ発言にあればまとめて更新します。単なる相槌は新しい決定として扱いません。
具体的な作品の相談になったら、全項目の回答を待たずsearch_reference_libraryで全体の参考を見せます。好みや否定を踏まえて再検索します。検索候補と採用済み参考を区別し、ユーザーが選ぶまではreferencesに記録しません。
参考の方向にユーザーが納得したらreference_agreedをtrueにします。全8項目がconfirmedまたは相談済みのundecidedになりready_for_draft=trueなら、今回の作品を具体化する次の案を提案します。映画・物語では制作案を引き継ぎ、展開や見た目を相談します。シート完成を長編生成の開始条件にはしません。本番生成や出費の許可と混同しません。
相談の更新を終えたら、音声側に次の具体的な質問か提案を短く返します。まず作りたいものと用途をつかみ、近い全体の参考を見せて方向を絞ります。方向が決まっても未確認項目があれば、それを具体的に聞きます。聞く順番は会話に合わせてあなたが選び、「どこから埋めたいですか」と進行を任せません。十分そろった時は更新結果のproduction_handoffに従い、ユーザーが催促する前に次の制作相談を始めます。既に分かった内容や一緒に未定で進めると決めた項目は聞き直しません。
雑談や質問は普通に答え、毎回シートを読み上げたり確認宣言したりしません。足りない項目を一律に全て質問せず、必要な順に聞きます。深い調査や制作はrun_editor_task、一般のWeb検索はweb_search、ライブラリ検索はJevの専用ツールです。'''

BACKEND_INSTRUCTIONS += """
Keep each sheet field to a short phrase or sentence without repeating details across fields. Preserve essential constraints. video_type holds format, subject holds this video's message, materials holds media and availability, references holds only meaningful deviations from the reference. Store displayed item IDs in reference_ids.
The sheet describes THIS video. Keep future channel plans in conversation history, not as requirements for this work, unless they change a concrete decision in this video. Purpose describes the intended viewer outcome, not merely launching a channel. Do not pack a proposed scene sequence into the subject field.
When proposing a scene sequence, composition, camera idea or character that is hard to judge from words, use show_consultation_visual to make a simple visible sketch while discussing it. Prefer concise editable composition layers for a flow diagram or layout; use a scene when spatial motion matters. A sketch is not evidence of an existing reference video's style. Keep references and proposed designs distinct, do not invent source images or URLs. No generated-media purchase or production delegation is needed for a simple visual explanation. Do not visualize greetings or every utterance. After showing it, ask about the meaningful difference, not whether to fill another form field.
A relative preference such as 'the second is closer' is not necessarily agreement to make it. Understand the remaining differences and search for examples that resolve those differences. No mandatory number of comparisons or numeric confidence. Set reference_agreed only when the conversation supports proceeding in that direction; reset when direction changes.
When the user clarifies visual or narrative preferences after examples were shown, consider whether those examples actually demonstrate the newly requested properties. If not, use search_reference_library with refinement.keep, refinement.change and refinement.next_axis grounded in their words. Do not substitute a verbal description for a missing visual example or search again without a meaningful difference to resolve. Do not invent a mismatch merely to fill these optional fields. A request to repeat or replay uses control_reference, not another search.
For a finished-look image use run_editor_task with artifact=look_frame. Revisions carry the displayed original item ID and requested changes. Preserve accepted appearance in subsequent production. Do not stop at acknowledging the final answer.
"""

from app.services.editor_first_artifact import GUIDANCE, CONSULTATION_GUIDANCE
BACKEND_INSTRUCTIONS += '\n' + GUIDANCE + CONSULTATION_GUIDANCE
from app.services.editor_film_plan import INSTRUCTIONS as FILM_INSTRUCTIONS
BACKEND_INSTRUCTIONS += '\n' + FILM_INSTRUCTIONS

from app.services.editor_production_handoff import GUIDANCE as HANDOFF_GUIDANCE
BACKEND_INSTRUCTIONS += "\n" + HANDOFF_GUIDANCE
