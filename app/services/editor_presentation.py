"""Mixed-media proposals; presenting never invokes a generation service."""
import copy,json,math,time,uuid
from urllib.parse import urlparse,urlencode
from app.services import timeline_draft as td

ITEM_SCHEMA={'type':'object','properties':{
 'title':{'type':'string'},'note':{'type':'string'},'url':{'type':'string'},'asset_id':{'type':'string'},'source_url':{'type':'string'},'reference_id':{'type':'string'},
 'kind':{'type':'string','enum':['video','image','audio','text','composition']},'text':{'type':'string'},
 'start':{'type':'number'},'end':{'type':'number'},
 'composition':{'type':'object','description':'{width,height,duration,background,layers:[{type:text|rect|image|video,text?,asset_id?,url?,x,y,width,height,start,end,fontSize?,color?,background?,borderRadius?,source_start?,keyframes?:[{offset,opacity?,x?,y?,scale?}]}]}. Positions/fonts in canvas pixels. Layers back to front. Keyframe offset 0..1, x/y pixel translation. Editable local animation; no generation API.'}},'required':['title','kind']}
DESCRIPTION='判断できる実物を大きく提示。元動画の区間・画像・音声はasset_idまたは確認済みURL。文字やロゴ案はtext、動く図解や素材の組合せはcomposition。noteは今回何を取り入れる案か。動画区間は実際に確認し、未確認の内容は断定しない。'

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
 if p.scheme!='https' or not p.hostname or p.username or p.password:raise ValueError('素材IDまたは公開HTTPS URLを指定してください')
 return url

def clean_composition(room,data):
 if not isinstance(data,dict):raise ValueError('compositionが必要です')
 out={'width':number(data.get('width'),1280,100,4096),'height':number(data.get('height'),720,100,4096),'duration':number(data.get('duration'),8,.1,600),'background':str(data.get('background','#15171b'))[:80],'layers':[]}
 layers=data.get('layers',[])
 if not isinstance(layers,list) or not 1<=len(layers)<=80:raise ValueError('layersは1〜80個です')
 for layer in layers:
  if not isinstance(layer,dict):raise ValueError('レイヤーはオブジェクトで指定してください')
  kind=layer.get('type','text')
  if kind not in ('text','rect','image','video'):raise ValueError('未対応のレイヤーです')
  c={'type':kind,'text':str(layer.get('text',''))[:3000]}
  for key,default,lo,hi in [('x',0,-8192,8192),('y',0,-8192,8192),('width',out['width'],1,8192),('height',out['height'],1,8192),('start',0,0,600),('end',out['duration'],0,600),('fontSize',48,1,500),('borderRadius',0,0,1000),('source_start',0,0,86400)]:c[key]=number(layer.get(key),default,lo,hi)
  if c['end']<=c['start'] or c['end']>out['duration']:raise ValueError('レイヤーの表示区間が不正です')
  for key,default in [('color','#fff'),('background','transparent'),('fontFamily','sans-serif'),('fontWeight','500'),('textAlign','center'),('objectFit','contain')]:c[key]=str(layer.get(key,default))[:100]
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

def present(room,content_id,items):
 if not isinstance(items,list) or not 1<=len(items)<=4:raise ValueError('提案は1〜4件です')
 clean=[]
 for item in items:
  if not isinstance(item,dict):raise ValueError('提案はオブジェクトで指定してください')
  kind=item.get('kind','video')
  if kind not in ('video','image','audio','text','composition'):raise ValueError('未対応の提案形式です')
  c={'id':uuid.uuid4().hex[:12],'title':str(item.get('title','提案'))[:120],'note':str(item.get('note',''))[:600],'kind':kind}
  if item.get('source_url'):c['source_url']=media_url(room,{'url':item['source_url']})
  if item.get('reference_id'):
   from app.services.editor_references import read
   read(room,content_id,str(item['reference_id']))
   c['reference_id']=str(item['reference_id'])
  if kind=='composition':c['composition']=clean_composition(room,item.get('composition'))
  elif kind=='text':c['text']=str(item.get('text',''))[:5000]
  else:
   c['url']=media_url(room,item)
   if item.get('asset_id'):c['asset_id']=str(item['asset_id'])
  start=number(item.get('start'),0,0,86400);end=number(item.get('end'),0,0,86400)
  if end and end<=start:raise ValueError('再生区間が不正です')
  c.update(start=start,end=end);clean.append(c)
 presentation={'id':uuid.uuid4().hex,'at':time.time(),'items':clean}
 with td.ContentsLock(room):
  contents=td._read_contents_raw(room);content=td._find_content(contents,content_id)
  if content is None:raise ValueError('作品が見つかりません')
  archive=content.setdefault('proposal_history',[]);archive.append(copy.deepcopy(presentation));content['proposal_history']=archive[-30:]
  content['presentation']=presentation;td._write_contents_raw(room,contents)
 return {'ok':True,'presentation':presentation,'view':{'mode':'single','active_id':clean[0]['id']},'note':'最初の案を大きく表示しました。他の案は番号付きタブで切り替え、並べて比べるボタンで比較できます。左右ではなく案の番号や名前で説明してください。タイムラインは変更していません。'}

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
