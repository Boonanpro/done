"""Collect attributable URL references; never download the video bodies.

Search group is discovery provenance, not a verified visual-style label.
"""
import concurrent.futures, datetime, json, math, re, sys, time
from pathlib import Path
import yt_dlp

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'scratch/reference-url-pilot'
GROUPS={
 'ai_launch':['OpenAI introducing model official','Anthropic introducing Claude official','Google Gemini introducing official'],
 'software_launch':['Introducing software launch film Notion Linear Figma','Slack Dropbox product launch official','日本 ソフトウェア サービス 紹介 公式'],
 'hardware_launch':['Apple introducing product film official','Sony introducing camera official','Samsung Galaxy official introduction'],
 'brand_film':['Nike brand film official','Patagonia brand film official','日本 ブランドムービー 公式'],
 'product_ad':['Apple commercial official','IKEA commercial official','日本 CM 公式 サントリー 資生堂'],
 'creator_ad':['UGC ad skincare product creator','Dollar Shave Club official commercial','Squatty Potty official commercial'],
 'documentary':['New York Times Op Docs short documentary','The New Yorker documentary short','NHK documentary short Japan'],
 'vlog':['Casey Neistat cinematic vlog','日常 vlog 料理 暮らし','cinematic silent vlog day in life'],
 'travel':['cinematic travel film Japan','Beautiful Destinations travel film official','JR東海 そうだ京都行こう CM 公式'],
 'music_video':['official music video animation','OK Go official music video','米津玄師 official music video'],
 'narrative_short':['Omeleto award winning short film','Short of the Week short film','日本 短編映画 公式'],
 'animation_short':['Blender Studio animated short film','Gobelins animated short film','Pixar SparkShorts official'],
 'motion_design':['BUCK motion design film','Ordinary Folk motion design','ManvsMachine design film'],
 'explainer':['Kurzgesagt official animation','TED Ed animated lesson','animated explainer film studio'],
 'science_education':['Veritasium science video','3Blue1Brown visual explanation','NHK for school 理科'],
 'food':['cinematic cooking film','Tasty recipe official','料理 レシピ 映像 クラシル'],
 'fashion':['CHANEL fashion film official','Dior fashion film official','UNIQLO LifeWear film official'],
 'sports':['Red Bull cinematic sports film','Nike sport campaign official','Adidas sport commercial official'],
 'social_impact':['UNICEF campaign film official','WWF campaign film official','ACジャパン CM 公式'],
 'title_sequence':['opening title sequence official','OFFF opening titles studio','映画 オープニング タイトル モーション'],
}
class Quiet:
 def debug(self,*a):pass
 def warning(self,*a):pass
 def error(self,*a):pass

def collect_one(task):
 group,index,query=task
 path=OUT/'searches'/f'{group}-{index}.json'
 if path.exists():return json.loads(path.read_text(encoding='utf8'))
 started=time.perf_counter()
 try:
  opts={'quiet':True,'logger':Quiet(),'extract_flat':'in_playlist','skip_download':True,'socket_timeout':20,'retries':1}
  data=yt_dlp.YoutubeDL(opts).extract_info('ytsearch20:'+query,download=False)
  rows=[]
  for r in data.get('entries',[]):
   if not r:continue
   rows.append({k:r.get(k) for k in ('id','title','url','channel','channel_id','duration','view_count','description','thumbnails')})
  result={'group':group,'query':query,'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'seconds':round(time.perf_counter()-started,2),'entries':rows}
 except Exception as exc:result={'group':group,'query':query,'error':type(exc).__name__,'entries':[]}
 path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
 print(group,index,len(result['entries']),flush=True)
 return result

def main():
 (OUT/'searches').mkdir(parents=True,exist_ok=True)
 tasks=[(g,n,q) for g,qs in GROUPS.items() for n,q in enumerate(qs)]
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(collect_one,tasks))
 candidates={}
 for result in results:
  for r in result['entries']:
   if not re.fullmatch(r'[\w-]{11}',r.get('id') or ''):continue
   ident=r['id']
   if ident not in candidates:candidates[ident]={**r,'discovery_groups':[],'discovery_queries':[],'retrieved_at':result['retrieved_at']}
   c=candidates[ident]
   if result['group'] not in c['discovery_groups']:c['discovery_groups'].append(result['group'])
   if result['query'] not in c['discovery_queries']:c['discovery_queries'].append(result['query'])
 (OUT/'candidates.json').write_text(json.dumps(list(candidates.values()),ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'queries':len(results),'unique':len(candidates),'failures':sum(bool(r.get('error')) for r in results)}),flush=True)

if __name__=='__main__':main()
