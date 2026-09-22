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
        if key=='references' and sheet['fields'][key]!=item:sheet['reference_agreed']=False
        sheet['fields'][key]=item
    if reference_agreed is not None:
        if not isinstance(reference_agreed,bool):raise ValueError('reference_agreed must be boolean')
        sheet['reference_agreed']=reference_agreed
    sheet['ready_for_draft']=sheet['reference_agreed'] and all(v['status']!='unknown' for v in sheet['fields'].values())
    return sheet

def tools():
    def tool(name,description,properties,required):
        return {'type':'function','name':name,'description':description,'strict':False,
                'parameters':{'type':'object','properties':properties,'required':required,'additionalProperties':False}}
    return [
        tool('get_consultation_state','現在の作品の相談シート・表示済み参考・実行状況を読む。再接続時や必要な時に使用。',{},[]),
        tool('update_consultation_sheet','会話で分かった内容を簡潔に整理して記録する。原文の貼付や推測は禁止。変わった項目だけ更新。unknown=未確認、undecided=相談の結果未定で進める、confirmed=決定。参考検索結果は採用ではない。',{
            'changes':{'type':'array','maxItems':8,'items':{'type':'object','properties':{
                'field':{'type':'string','enum':list(FIELDS)},'status':{'type':'string','enum':list(STATUSES)},'value':{'type':'string'}},'required':['field','status','value'],'additionalProperties':False}},
            'reference_agreed':{'type':'boolean','description':'ユーザーが参考の方向に同意した時true。方向変更で同意が失われたらfalse。'}},['changes']),
        tool('search_reference_library','Jevで既存の参考を検索し、実物を画面に提示する。採用済み参考は変更しない。',{
            'query':{'type':'string'},'scope':{'type':'string','enum':['work','component']}},['query','scope']),
        tool('control_reference','表示済みの参考を再表示、再生、一時停止する。',{
            'item_id':{'type':'string'},'action':{'type':'string','enum':['reveal','play','pause']}},['item_id','action']),
        tool('run_editor_task','制作担当に編集・生成・高度な調査を依頼する。ユーザーの要望と合意をそのまま伝える。シート完成だけで勝手に本番生成しない。',{'task':{'type':'string'}},['task']),
        {'type':'web_search'},
    ]

BACKEND_INSTRUCTIONS = '''音声会話のダンの判断と道具を担当します。自然に短く返答します。
制作相談シートはあなたがupdate_consultation_sheetで更新します。動画の種類、題材、公開先、目的、視聴者、尺、素材、採用した参考の8項目だけです。
会話で分かった情報を短い整理した文章にして、変わった項目を更新してください。題材と映像のテイスト、公開先と目的を混同しません。言い直しは該当項目を訂正し、矛盾しない内容は残します。未確認を未定と勝手に埋めません。
開始時・再接続時はget_consultation_stateで既存シートを読み、過去の会話から未記録の情報を整理できます。旧形式のメモは採用済みの事実と扱いません。
具体的な作品の相談になったら、全項目の回答を待たずsearch_reference_libraryで全体の参考を見せます。好みや否定を踏まえて再検索します。検索候補と採用済み参考を区別し、ユーザーが選ぶまではreferencesに記録しません。
参考の方向にユーザーが納得したらreference_agreedをtrueにします。全8項目がconfirmedまたは相談済みのundecidedになりready_for_draft=trueなら、自然に下書きへの移行を提案します。既に下書き作成を依頼されていればrun_editor_taskへ進みます。本番生成や出費の許可と混同しません。
雑談や質問は普通に答え、毎回シートを読み上げたり確認宣言したりしません。足りない項目を一律に全て質問せず、必要な順に聞きます。深い調査や制作はrun_editor_task、一般のWeb検索はweb_search、ライブラリ検索はJevの専用ツールです。'''
