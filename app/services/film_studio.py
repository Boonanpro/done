"""Conversation-led film preparation demo; separate from the production editor."""
import asyncio
import os
import json
import time
from copy import deepcopy
from app.services import timeline_draft as td, editor_film_plan as film, editor_presentation as visual
from app.services.editor_consultation_sheet import tools as consultation_tools

ROOM=os.environ.get('DAN_FILM_STUDIO_ROOM','film-studio-demo-v1')
CONTENT='two-minute-film'
USER='2582a188-ff24-4a4f-b989-6063034d90b2'

INSTRUCTIONS='''あなたはダン。ユーザーが監督として、2分の映画を本番生成に渡せるところまで一緒に詰める制作相手です。日本語で自然に短く会話します。
既存の8項目は出発点です。展開が不明なら、考えている展開があるか尋ね、未定ならあなたから提案します。自分の案は提案でありユーザーの採用ではありません。物語と登場人物の役割を一緒に考え、必要になった人物・場所・物の見た目を画像で示します。一度に全問を聞かず、判断が進む提案をします。
物語の相談・保存にはupdate_film_plan。場面IDを維持し、変更箇所だけ保存。文字だけの場面説明を映像の代用品として並べて終わらせません。必要な時はgenerate_lookで完成見た目や絵コンテ画像を実際に作る。画像は生成なので時間がかかります。既存画像の修正はrevisesを渡し、同一人物・場所の画像をreference_asset_idsで引き継ぎます。画像モデルはサーバーがJevで選びます。
配置・カメラ・時間の相談にはshow_consultation_visualのsceneを使えます。Three.jsは利用可能。codeはstage、THREE、params、setFrame(fn)を使い、fn(t)で実際に時間に応じて動くこと。人物は粗い立体でよい。カメラ・配置・動作の変更値はparamsへ分離。既存の実物変更はrevise_consultation_visualで差分変更。動作のない静止3Dを動くコンテと言いません。完成画像と粗い3Dは別の役割です。
画像・3Dは該当場面のvisual_idsに結び付けます。人物など複数場面に共通する画像も再利用。今の選択場面は発言の参考であり、全発言の対象と決めつけません。get_visualで既存案の元データを読めます。showの保存成功とユーザー画面の描画成功は別。get_stateのdisplayedで確認できます。
場面のaction/dialogue/camera/sound/durationを会話で具体化します。下書きはユーザーと反復して仕上げるもの。全2分を勝手に埋めたり、一度の相槌で全案採用にしません。次に決めると有効なことはあなたから提案します。
生成準備が整った場面はsave_recipeに、渡すモデル、生成プロンプト、画像ID、動きのID、音、未決事項を保存。本番動画生成の道具はありません。save_recipeは保存だけで、実行や完成ではありません。未知のAPI対応を断定しません。
このデモでは音声入力とテキスト指示が同じ制作状態を更新します。原文と会話文脈を読み、分類の宣言や『今は制作として扱いません』等は言わず、質問には直接答えます。ツール結果に基づいて報告します。'''

def fn(name,description,props,required):
    return {'type':'function','name':name,'description':description,'strict':False,
            'parameters':{'type':'object','properties':props,'required':required,'additionalProperties':False}}

def tools():
    selected={'update_film_plan','show_consultation_visual','revise_consultation_visual'}
    return [t for t in consultation_tools() if t.get('name') in selected]+[
        fn('get_state','現在の条件・物語・場面・画像・会話を必要な時に読む。',{},[]),
        fn('get_visual','指定画像やsceneの詳細・変更用のコードとparamsを読む。',{'item_id':{'type':'string'}},['item_id']),
        fn('search_references','Jevで既存作品の参考を探して提示する。新しい作品の絵はgenerate_lookを使う。',{'query':{'type':'string'}},['query']),
        fn('generate_look','完成見た目または絵コンテの画像を生成・修正し画面へ提示。動画は生成しない。',{
            'prompt':{'type':'string','maxLength':12000},'title':{'type':'string'},
            'reference_asset_ids':{'type':'array','items':{'type':'string'},'maxItems':4},
            'revises':{'type':'string'},'scene_id':{'type':'string'}},['prompt','title']),
        fn('save_recipe','場面ごとの本番生成に渡す仕様を保存。未決事項を明示する。',{
            'scene_id':{'type':'string'},'model':{'type':'string'},'prompt':{'type':'string'},
            'visual_ids':{'type':'array','items':{'type':'string'}},'audio':{'type':'string'},
            'unresolved':{'type':'array','items':{'type':'string'}}},['scene_id','model','prompt','visual_ids','audio','unresolved'])]

def initialize(room=ROOM):
    root=td._room_dir(room);root.mkdir(parents=True,exist_ok=True)
    if (root/'contents.json').exists():return
    sheet={'動画の種類':'映画','題材':'27歳の男が空飛ぶ車を開発する物語。現実的で泥臭いエンジニアリングとして描く。',
           '公開先':'YouTube','作る目的':'チャンネル登録者の増加と収益につなげる。','想定する視聴者':'映画好きな人、YouTubeで映画を見たい人。',
           '尺':'2分（今回の会話で2時間から変更）','使いたい素材':'撮影素材なし。AIで素材を生成したい。',
           '参考として選んだ作品':'Hidden Figuresが比較候補では近い。最終採用は未定。'}
    td._write_contents_raw(room,[{'id':CONTENT,'title':'空飛ぶ車の映画・2分','sheet':sheet,
        'film_plan':film.empty(),'studio_dialogue':[],'recipes':{},'timeline':{'format':'16:9','sequence':{'format':'16:9','duration':0,'tracks':[]}}}])

def content(room=ROOM):
    initialize(room)
    return td._find_content(td._read_contents_raw(room),CONTENT)

def mutate(callback,room=ROOM):
    with td.ContentsLock(room):
        rows=td._read_contents_raw(room);c=td._find_content(rows,CONTENT);callback(c);td._write_contents_raw(room,rows)

def dialogue(role,text,room=ROOM):
    if text.strip():mutate(lambda c:c['studio_dialogue'].append({'role':role,'text':text,'at':time.time()}),room)

def invalidate_recipes(room,scene_ids=None,visual_id=None):
    def invalidate(c):
        for sid,recipe in c.get('recipes',{}).items():
            if scene_ids is None or sid in scene_ids or visual_id in recipe.get('visual_ids',[]):
                recipe['needs_review']=True
    mutate(invalidate,room)

def state(room=ROOM):
    c=content(room);items={i['id']:i for p in c.get('proposal_history',[]) for i in p.get('items',[])}
    return {'sheet':c['sheet'],'film_plan':c['film_plan'],'items':items,'recipes':c.get('recipes',{}),
            'dialogue':c['studio_dialogue'],'look_frames':[{k:r.get(k) for k in ('item_id','asset_id','revises','requested_model')} for r in c.get('look_frames',[])]}

def context(room=ROOM):
    s=state(room)
    s['items']={k:{a:v for a,v in i.items() if a not in ('scene','composition')} for k,i in s['items'].items()}
    s['dialogue']=s['dialogue'][-30:]
    return s

async def image_route(prompt,revises):
    from app.services.editor_jev import judge,confident
    result=await judge(USER,{'request':prompt,'editing_existing':bool(revises)}, {'model':{
        'type':'choice','instructions':'Choose among supported image tools. Use gpt-image-2 unless a 2.5 specialization is useful. Never choose a video model.',
        'criteria':{'gpt-image-2':'General high quality still image or storyboard',
                    'gpt-image-2.5-flare':'New finished look image',
                    'gpt-image-2.5-sunburst':'Precise revision of an existing finished look'}}},timeout=2)
    chosen=confident(result.get('answers',{}).get('model'),{'gpt-image-2','gpt-image-2.5-flare','gpt-image-2.5-sunburst'})
    return chosen or 'gpt-image-2',{'selected_by':'jev' if chosen else 'configured_default','reason':result.get('reason'),'answers':result.get('answers')}

async def execute(name,args,room=ROOM):
    if name=='get_state':return context(room)
    if name=='search_references':
        from app.services.reference_url_index import search
        found=await search(USER,args['query'],routing='genres',dialogue=content(room)['studio_dialogue'][-20:],embedded=True,limit=3)
        rows=found.get('results',[])
        if not rows:return {'ok':False,'error':'適合する参考が見つかりませんでした','available':found.get('available')}
        shown=visual.present(room,CONTENT,[{'kind':'video','title':r['title'],'url':r['url'],'source_url':r['url'],'start':r.get('start') or 0,'end':r.get('end') or 0} for r in rows])
        return {**shown,'search_ms':found['elapsed_ms']}
    if name=='get_visual':
        item=state(room)['items'].get(args['item_id'])
        if not item:raise ValueError('この作品の見本が見つかりません')
        return item
    if name=='update_film_plan':
        plan=film.update(room,CONTENT,**args)
        changes=args['changes'];ids=None if any(c['op'] in ('story','order') for c in changes) else {c.get('id') for c in changes if c['op'] in ('scene','remove_scene')}
        invalidate_recipes(room,ids)
        return {'film_plan':plan}
    if name=='show_consultation_visual':return await visual.resolve_and_present(room,CONTENT,args['items'])
    if name=='revise_consultation_visual':
        result=visual.revise(room,CONTENT,**args);new=result['presentation']['items'][0]['id']
        film.link_visual_revision(room,CONTENT,args['item_id'],new)
        invalidate_recipes(room,set(),args['item_id']);return result
    if name=='generate_look':
        from app.services.editor_look_frame import generate
        args=deepcopy(args);sid=args.pop('scene_id',None)
        if sid and not any(s['id']==sid for s in film.read(room,CONTENT)['scenes']):raise ValueError('場面IDがありません。先に場面を保存してください')
        model,routing=await image_route(args['prompt'],args.get('revises'))
        result=await asyncio.to_thread(generate,room,CONTENT,model=model,**args)
        if sid:
            plan=film.read(room,CONTENT);s=next(s for s in plan['scenes'] if s['id']==sid)
            ids=[i for i in s['visual_ids'] if i!=args.get('revises')]+[result['presentation']['items'][0]['id']]
            film.update(room,CONTENT,plan['revision'],[{'op':'scene','id':sid,'visual_ids':ids}],'相談中の見た目を画像化（採用は未確認）')
        invalidate_recipes(room,{sid} if sid else set(),args.get('revises'))
        result['routing']=routing;return result
    if name=='save_recipe':
        s=state(room)
        if not any(x['id']==args['scene_id'] for x in s['film_plan']['scenes']):raise ValueError('場面がありません')
        if any(i not in s['items'] for i in args['visual_ids']):raise ValueError('実在する見本IDを指定してください')
        saved={**deepcopy(args),'needs_review':False,'saved_plan_revision':s['film_plan']['revision']}
        mutate(lambda c:c['recipes'].update({args['scene_id']:saved}),room)
        return {'ok':True,'saved':args,'executed':False}
    raise ValueError('未対応の道具です')

LABELS={'get_state':'相談内容を読み込んでいます','get_visual':'見本を確認しています','update_film_plan':'物語・場面を更新しています',
        'search_references':'参考作品をライブラリから探しています',
        'show_consultation_visual':'動きや構図の見本を作っています','revise_consultation_visual':'指定部分を変更しています',
        'generate_look':'完成イメージを画像にしています','save_recipe':'生成用の仕様を保存しています'}
