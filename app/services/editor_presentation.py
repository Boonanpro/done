"""Mixed-media proposals; presenting never invokes a generation service."""
import asyncio,copy,json,math,time,uuid
from urllib.parse import urlparse,urlencode
from app.services import timeline_draft as td

ITEM_SCHEMA={'type':'object','properties':{
 'caption':{'type':'string','maxLength':60,'description':'比較に必要な場合だけ画面に添える短い一言。通常は省略。'},
 'title':{'type':'string','description':'会話で対象を識別する短い名前。'},'note':{'type':'string','description':'通常は省略。会話担当に必要な確認上の制約のみ。画面用の説明文は作らない。'},'url':{'type':'string'},'asset_id':{'type':'string'},'source_url':{'type':'string'},'reference_id':{'type':'string'},
 'source':{'type':'string','description':'検索で確認した公開URLや既存asset_id。指定すると実物の取得・参考登録・表示を一度で行う。先にresolve_referenceを呼ぶ必要はない。ページから画像のみ取得できた場合は実際の形式を返す。'},
 'kind':{'type':'string','enum':['video','image','audio','text','composition','scene','link','model']},'text':{'type':'string'},
 'scene':{'type':'object','properties':{'code':{'type':'string','maxLength':40000,'description':'JavaScript module body. THREE (r180) and stage (full-size div) provided. Build visuals then call setFrame(t=>{...}) to render at absolute seconds. Host handles autoplay/pause/seek/resize; do not start your own loop. stage.clientWidth/Height for aspect. DOM/CSS/Canvas/WebGL allowed. No external imports/network/parent access. Example: const r=new THREE.WebGLRenderer({antialias:true});stage.append(r.domElement); ... setFrame(t=>{r.setSize(stage.clientWidth,stage.clientHeight);mesh.rotation.y=t;r.render(scene,camera);});'},'duration':{'type':'number','minimum':0.1,'maximum':120},'width':{'type':'number'},'height':{'type':'number'},'description':{'type':'string','description':'会話担当に伝える見た目と動作の短い説明。画面には表示しない。'}},'required':['code','duration'],'description':'自由な3D人物・空間・図解・モーションを直接動かす見本。隔離プレビュー、書き出し不要。既存タイムラインには触れない。'},
 'revises':{'type':'string','description':'改訂元の提示item ID。元の案は履歴に残る。'},
 'start':{'type':'number'},'end':{'type':'number'},
 'composition':{'type':'object','description':'{width?,height?,duration?,background?,defaults?:{shared layer fields},layers:[{type?:text|rect|image|video,text?,asset_id?,url?,x?,y?,width?,height?,start?,end?,fontSize?,color?,background?,borderRadius?,source_start?,keyframes?:[{offset,opacity?,x?,y?,scale?}]}]}. Canvas defaults 1280x720,8s. Layer defaults text,x=y=start=0,width/height=canvas,end=duration,fontSize=48,color=#fff. defaults shares any layer fields; individual fields override. Omit unchanged defaults. Positions/fonts in pixels. Layers back to front. Keyframe offset 0..1, x/y translation. Direct local UI animation, not a HyperFrames project; no build/export/API.'}},'required':['title','kind']}
DESCRIPTION='ビジュアル履歴へ実物を追加。動く3D人物・空間・図解はsceneのコードで直接作れる。Three.jsは内蔵済み、ビルドや動画書き出し不要。2D文字・図形はcomposition。公開作品はsourceで取得・登録・表示を一度に実行。画像・動画・音声はasset_idか確認済みURL、文字はtext、Webページはlink、GLB/glTFはmodel。revisesで改訂元を示せる。'

ITEM_SCHEMA['properties']['composition']['description'] += ' Text layers also support letterSpacing (pixels), lineHeight (ratio), strokeWidth (pixels), strokeColor, textShadow (CSS), fontStyle. These remain editable values; real footage can be a video layer behind the text.'

# Scene programs can expose their own design controls. No genre-specific preset
# or fixed workflow: the author chooses what is parametrized for this artwork.
_scene_schema=ITEM_SCHEMA['properties']['scene']
_scene_schema['properties']['params']={'type':'object','description':'コードへparamsとして渡す任意のJSON。色・照明・人物・構図・速度等、後で変える値を分離。revise_presentationで/scene/params/キーだけ変えるとコードと他の値は保持される。'}
_scene_schema['properties']['reuse']={'description':'既存sceneのitem ID、または同じitems内の先行案の0始まり整数index。コードと既存paramsを再利用し、今回のparamsだけ上書きして別案にする。codeとの同時指定は不可。','anyOf':[{'type':'string'},{'type':'integer','minimum':0}]}
_scene_schema['required']=[]
_scene_schema['description']+=' codeを新規に書く場合はdurationも指定。比較案はreuseで先行案のコードを共有し、paramsで違いを指定できる。'
_scene_schema['properties']['html']={'type':'string','maxLength':160000,'description':'既存HTML/GSAP部品を改変した見本。codeと排他。固定サイズのdata-composition-idルートとwindow.__timelinesへのpaused timeline登録が必要。GSAPは内蔵、外部JS/画像/フォントは読み込まない。動画書き出し不要で直接再生。paramsはwindow.danParamsで読める。'}


async def resolve_and_present(room, content_id, items, is_current=lambda:True):
 """Eliminate a model round-trip between reference intake and display."""
 if not isinstance(items,list) or not 1<=len(items)<=4:
  raise ValueError('提案は1〜4件です')
 from app.services.editor_references import resolve
 started=time.perf_counter()
 async def prepare(item):
  if not isinstance(item,dict):raise ValueError('提案はオブジェクトで指定してください')
  if not item.get('source'):return item
  resolved=await asyncio.to_thread(resolve,room,content_id,item['source'])
  actual=resolved['item']
  # Never overwrite the actual media kind/URL with a model's guess.
  prepared={**actual,**{k:v for k,v in item.items() if k in ('title','note','caption','start','end','revises','source_url')}}
  if item.get('kind')!=actual.get('kind'):
   prepared['note']=actual.get('note','')+' '+str(item.get('note',''))
  return prepared
 prepared=await asyncio.gather(*(prepare(i) for i in items))
 resolved_ms=round((time.perf_counter()-started)*1000)
 if not is_current():return {'ok':False,'canceled':True}
 result=await asyncio.to_thread(present,room,content_id,prepared)
 result['timings']={'resolve_ms':resolved_ms,'total_ms':round((time.perf_counter()-started)*1000)}
 return result

REVISE_PROPERTIES={
 'item_id':{'type':'string','description':'変更元の提示item ID'},
 'changes':{'type':'array','minItems':1,'maxItems':80,'items':{'type':'object','properties':{
  'path':{'type':'string','description':'既存値のJSON Pointer。例 /composition/layers/0/text、/composition/layers/0/keyframes、/composition/background。配列末尾への追加は /composition/layers/- のように - を使う。'},
  'value':{'description':'置き換える値'},
  'find':{'type':'string','minLength':1,'description':'任意。文字列中のこの部分だけをvalueに置換する。HTML/CSS/JSの局所修正は全文を再出力せず、読んだ元コードの一意な断片を指定できる。'},
  'expected_count':{'type':'integer','minimum':1,'maximum':100,'description':'findの一致数。省略時1。異なる場合は変更を保存せずエラーを返す。'}},'required':['path','value'],'additionalProperties':False}}}
REVISE_DESCRIPTION='提示済み見本の指定値だけ変更して新しい案を表示する。元の案と未指定の値は保持。色・文言・動き等の修正に使い、全体を書き直す必要はない。配列全体の置換も可能。'

def revise(room,content_id,item_id,changes):
 if not isinstance(changes,list) or not 1<=len(changes)<=80:raise ValueError('changes must contain 1..80 replacements')
 with td.ContentsLock(room):
  content=td._find_content(td._read_contents_raw(room),content_id)
  if content is None:raise ValueError('Content not found')
  rows=content.get('proposal_history',[])+[content.get('presentation',{})]
  original=next((i for p in reversed(rows) for i in p.get('items',[]) if i.get('id')==item_id),None)
  if original is None:raise ValueError('Presentation item not found')
  item=copy.deepcopy(original)
 for change in changes:
  path=change.get('path','')
  if not isinstance(path,str) or not path.startswith('/'):raise ValueError('Expected JSON Pointer')
  parts=[p.replace('~1','/').replace('~0','~') for p in path[1:].split('/')]
  if parts[0] not in {'title','caption','text','start','end','composition','scene'}:raise ValueError('This field cannot be revised')
  target=item
  for part in parts[:-1]:
   if isinstance(target,list) and part.isdigit() and int(part)<len(target):target=target[int(part)]
   elif isinstance(target,dict) and part in target:target=target[part]
   else:raise ValueError('Revision path does not exist')
  key=parts[-1]
  if 'find' in change:
   if isinstance(target,dict):old=target.get(key)
   elif isinstance(target,list) and key.isdigit() and int(key)<len(target):old=target[int(key)]
   else:old=None
   find=change['find'];value=change['value'];expected=change.get('expected_count',1)
   if not isinstance(old,str) or not isinstance(find,str) or not find or not isinstance(value,str):raise ValueError('Text replacement requires existing text, nonempty find and text value')
   if type(expected) is not int or not 1<=expected<=100:raise ValueError('expected_count must be 1..100')
   if old.count(find)!=expected:raise ValueError(f'Text match count differs: expected {expected}, found {old.count(find)}')
   target[int(key) if isinstance(target,list) else key]=old.replace(find,value)
  elif isinstance(target,list) and key=='-':target.append(copy.deepcopy(change['value']))
  elif isinstance(target,list) and key.isdigit() and int(key)<len(target):target[int(key)]=copy.deepcopy(change['value'])
  elif isinstance(target,dict) and (key in target or (len(parts)==1 and key=='caption') or parts[:2]==['scene','params']):target[key]=copy.deepcopy(change['value'])
  else:raise ValueError('Revision path does not exist')
 item['revises']=item_id
 return present(room,content_id,[item])

def number(v,default,low,high):
 n=float(default if v is None else v)
 if not math.isfinite(n) or not low<=n<=high:raise ValueError('表示サイズ・時間が範囲外です')
 return n

def media_url(room,item):
 if item.get('asset_id'):
  aid=str(item['asset_id']);p=td._room_dir(room)/'assets.json'
  rows=json.loads(p.read_text(encoding='utf-8')) if p.exists() else []
  if not any(a.get('id')==aid for a in rows):raise ValueError('素材が見つかりません: '+aid)
  return '/api/v1/production-assets/media?'+urlencode({'room_id':room,'asset_id':aid,'variant':'original'})
 url=str(item.get('url',''));p=urlparse(url)
 if url.startswith('/api/v1/editor-assistant/reference-library/media/'):
  from app.services.editor_reference_library import media_path
  ident=url.removeprefix('/api/v1/editor-assistant/reference-library/media/')
  media_path(ident)
  return url
 if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('素材IDまたは公開HTTPS URLを指定してください')
 return url

def clean_composition(room,data):
 if not isinstance(data,dict):raise ValueError('compositionが必要です')
 out={'width':number(data.get('width'),1280,100,4096),'height':number(data.get('height'),720,100,4096),'duration':number(data.get('duration'),8,.1,600),'background':str(data.get('background','#15171b'))[:80],'layers':[]}
 layers=data.get('layers',[])
 defaults=data.get('defaults',{})
 if not isinstance(defaults,dict):raise ValueError('defaults must be an object')
 if not isinstance(layers,list) or not 1<=len(layers)<=80:raise ValueError('layersは1〜80個です')
 for layer in layers:
  if not isinstance(layer,dict):raise ValueError('レイヤーはオブジェクトで指定してください')
  layer={**defaults,**layer}
  kind=layer.get('type','text')
  if kind not in ('text','rect','image','video'):raise ValueError('未対応のレイヤーです')
  c={'type':kind,'text':str(layer.get('text',''))[:3000]}
  for key,default,lo,hi in [('x',0,-8192,8192),('y',0,-8192,8192),('width',out['width'],1,8192),('height',out['height'],1,8192),('start',0,0,600),('end',out['duration'],0,600),('fontSize',48,1,500),('borderRadius',0,0,1000),('source_start',0,0,86400)]:c[key]=number(layer.get(key),default,lo,hi)
  if c['end']<=c['start'] or c['end']>out['duration']:raise ValueError('レイヤーの表示区間が不正です')
  for key,default in [('color','#fff'),('background','transparent'),('fontFamily','sans-serif'),('fontWeight','500'),('textAlign','center'),('objectFit','contain')]:c[key]=str(layer.get(key,default))[:100]
  # Optional typography controls preserve existing default layouts. A reference
  # over real footage must not lose its tracking, leading or edge treatment.
  for key,lo,hi in [('letterSpacing',-20,100),('lineHeight',.5,3),('strokeWidth',0,20)]:
   if key in layer:c[key]=number(layer[key],0,lo,hi)
  for key in ('textShadow','strokeColor','fontStyle'):
   if key in layer:c[key]=str(layer[key])[:200]
  if kind in ('image','video'):
   c['url']=media_url(room,layer)
   if layer.get('asset_id'):c['asset_id']=str(layer['asset_id'])
  keys=layer.get('keyframes',[])
  if not isinstance(keys,list) or len(keys)>40:raise ValueError('キーフレームが多すぎます')
  c['keyframes']=[]
  for key in keys:
   if not isinstance(key,dict):raise ValueError('キーフレームはオブジェクトで指定してください')
   k={'offset':number(key.get('offset'),0,0,1)}
   for name,default,lo,hi in [('opacity',1,0,1),('x',0,-8192,8192),('y',0,-8192,8192),('scale',1,.01,20)]:
    if name in key:k[name]=number(key[name],default,lo,hi)
   c['keyframes'].append(k)
  c['keyframes'].sort(key=lambda k:k['offset']);out['layers'].append(c)
 return out

def present(room,content_id,items,*,author='dan',comparison_key=None):
 if comparison_key is not None and (not isinstance(comparison_key,str) or not 1<=len(comparison_key)<=160):
  raise ValueError('Invalid comparison key')
 if not isinstance(items,list) or not 1<=len(items)<=4:raise ValueError('提案は1〜4件です')
 clean=[]
 for item in items:
  if not isinstance(item,dict):raise ValueError('提案はオブジェクトで指定してください')
  kind=item.get('kind','video')
  if kind not in ('video','image','audio','text','composition','scene','link','model'):raise ValueError('未対応の提案形式です')
  c={'id':uuid.uuid4().hex[:12],'title':str(item.get('title','提案'))[:120],'note':str(item.get('note',''))[:600],'kind':kind}
  if item.get('caption'):c['caption']=str(item['caption']).strip()[:60]
  if item.get('revises'):c['revises']=str(item['revises'])[:100]
  if item.get('source_url'):c['source_url']=media_url(room,{'url':item['source_url']})
  if item.get('reference_id'):
   from app.services.editor_references import read
   read(room,content_id,str(item['reference_id']))
   c['reference_id']=str(item['reference_id'])
  if kind=='composition':c['composition']=clean_composition(room,item.get('composition'))
  elif kind=='scene':
   data=item.get('scene')
   if isinstance(data,dict) and 'reuse' in data:
    if 'code' in data or 'html' in data:raise ValueError('Use code/html or reuse, not both')
    ref=data['reuse'];base=None
    if isinstance(ref,int) and not isinstance(ref,bool) and 0<=ref<len(clean):base=clean[ref]
    elif isinstance(ref,str):
     with td.ContentsLock(room):
      source=td._find_content(td._read_contents_raw(room),content_id)
      if source:
       base=next((x for p in reversed(source.get('proposal_history',[])+[source.get('presentation',{})]) for x in p.get('items',[]) if x.get('id')==ref),None)
    if not base or base.get('kind')!='scene':raise ValueError('Scene reuse target not found')
    original=base['scene'];params=data.get('params',{})
    if not isinstance(params,dict):raise ValueError('scene.params must be an object')
    data={**copy.deepcopy(original),**data,'params':{**copy.deepcopy(original.get('params',{})),**params}}
   if not isinstance(data,dict) or ('code' in data)==('html' in data):raise ValueError('Choose exactly one of scene.code or scene.html')
   field='html' if 'html' in data else 'code';limit=160000 if field=='html' else 40000
   if not isinstance(data[field],str) or not 1<=len(data[field])<=limit:raise ValueError(f'scene.{field} must contain 1..{limit} characters')
   c['scene']={field:data[field],'duration':number(data.get('duration'),8,.1,120),'width':number(data.get('width'),1280,100,4096),'height':number(data.get('height'),720,100,4096),'description':str(data.get('description',''))[:800]}
   params=data.get('params',{})
   if not isinstance(params,dict) or len(json.dumps(params,ensure_ascii=False,allow_nan=False))>12000:raise ValueError('scene.params must be a JSON object up to 12000 characters')
   c['scene']['params']=copy.deepcopy(params)
  elif kind=='text':c['text']=str(item.get('text',''))[:5000]
  else:
   c['url']=media_url(room,item)
   if c['url'].startswith('/api/v1/editor-assistant/reference-library/media/'):
    c['library_id']=c['url'].rsplit('/',1)[-1]
   if item.get('asset_id'):c['asset_id']=str(item['asset_id'])
  start=number(item.get('start'),0,0,86400);end=number(item.get('end'),0,0,86400)
  if end and end<=start:raise ValueError('再生区間が不正です')
  if item.get('library_id'):
   from app.services.editor_reference_library import catalog
   known=any(r['id']==item['library_id'] for r in catalog())
   if not known and str(item['library_id']).startswith('yt-'):
    from app.services.reference_url_index import catalog as url_catalog, observations
    known=any(r['id']==item['library_id'] and r['url']==c.get('url') for r in url_catalog())
    if known and item['library_id'] in observations():c['observation_basis']='model_video_observation'
   if known:c['library_id']=item['library_id']
  c.update(start=start,end=end);clean.append(c)
 presentation={'id':uuid.uuid4().hex,'at':time.time(),'items':clean,'author':'user' if author=='user' else 'dan'}
 if comparison_key:
  import hashlib
  presentation['id']=hashlib.sha256((str(room)+'/'+str(content_id)+'/'+comparison_key).encode()).hexdigest()[:32]
  presentation['revision']=1
 with td.ContentsLock(room):
  contents=td._read_contents_raw(room);content=td._find_content(contents,content_id)
  if content is None:raise ValueError('作品が見つかりません')
  archive=content.setdefault('proposal_history',[])
  previous=next((i for i,p in enumerate(archive) if p['id']==presentation['id']),None)
  if previous is None:archive.append(copy.deepcopy(presentation))
  else:
   old_items={i.get('library_id'):i for i in archive[previous]['items'] if i.get('library_id')}
   for item in clean:
    if item.get('library_id') in old_items:item['id']=old_items[item['library_id']]['id']
   presentation['at']=archive[previous]['at'];presentation['revision']=archive[previous].get('revision',1)+1
   archive[previous]=copy.deepcopy(presentation)
  content['presentation']=presentation;td._write_contents_raw(room,contents)
 return {'ok':True,'presentation':presentation,'view':{'mode':'feed','active_id':clean[0]['id']},'note':'ビジュアル履歴に追加しました。以前の案もスクロールで見返せます。表示だけで採用や制作開始にはなりません。'}


def history(room,content_id,before=None,limit=12):
 with td.ContentsLock(room):
  content=td._find_content(td._read_contents_raw(room),content_id)
  if content is None:raise ValueError('作品が見つかりません')
  rows=list(content.get('proposal_history',[]))
  current=content.get('presentation')
  if current and not any(p['id']==current['id'] for p in rows):rows.append(current)
 if before is not None:rows=[p for p in rows if p['at']<float(before)]
 rows.sort(key=lambda p:p['at']);size=max(1,min(int(limit),30));page=rows[-size:]
 return {'presentations':page,'before':page[0]['at'] if len(rows)>size else None}

def choose(room,content_id,item_id,feedback=''):
 with td.ContentsLock(room):
  contents=td._read_contents_raw(room);content=td._find_content(contents,content_id)
  if content is None:raise ValueError('作品が見つかりません')
  history=content.get('proposal_history',[])+[content.get('presentation',{})]
  item=next((i for p in reversed(history) for i in p.get('items',[]) if i['id']==item_id),None)
  if not item:raise ValueError('提案が見つかりません')
  content['chosen_proposal']={'item':copy.deepcopy(item),'feedback':str(feedback)[:2000],'at':time.time()}
  td._write_contents_raw(room,contents)
 from app.services.editor_intent import notify_worker
 delivery=notify_worker(room,content_id,{'chosen_proposal':content['chosen_proposal']})
 return {'ok':True,'chosen_proposal':content['chosen_proposal'],'delivery':delivery,'note':'方向性を保存しました。この案を使って通しの下書きを作れます。'}
