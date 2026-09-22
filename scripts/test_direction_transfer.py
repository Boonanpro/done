"""Real Jev recommendation, Astra CLI planning, native editor rendering. No voice."""
import asyncio,json,os,re,sys,time,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from app.services import editor_direction_library as lib
OUT=ROOT/'scratch/direction-transfer';OUT.mkdir(parents=True,exist_ok=True)
CASES=[
 ('inquiry-calm','問い合わせ案内。伝える情報は車種・年式・写真・症状・連絡先の5つ。','初めてでも自分にできそうだと安心し、必要な情報を揃えて相談したくなる。落ち着いて具体的に。'),
 ('inquiry-curious','問い合わせ案内。伝える情報は車種・年式・写真・症状・連絡先の5つ。','なぜやり取りが何度も続くのか気になり、五つを揃える意味を発見する。最初から答えを全部並べない。'),
 ('cafe-calm','喫茶「余白」。仕事帰りに、ひとりでも気兼ねなく一息つける場所。','疲れた人がほっとして、帰りに寄りたくなる。大げさに煽らず、余韻を持たせる。'),
 ('cafe-energy','喫茶「余白」。仕事帰りに、ひとりでも気兼ねなく一息つける場所。','日常から気分を切り替える小さな楽しみに気づく。軽やかでテンポのある発見。'),
 ('memo-clarity','メモの整理。思いつきを書き、関連するものをまとめ、次にやることを一つ選ぶ。','難しくなさそうで、進め方が分かる。順番を落ち着いて理解できる。'),
 ('memo-discovery','メモの整理。思いつきを書き、関連するものをまとめ、次にやることを一つ選ぶ。','散らかった思いつきが、次の一歩になる発見の気持ちよさを感じる。手順の羅列ではなく変化を見せる。'),
]

async def create(name, facts, purpose):
 from app.services.editor_codex import CodexTurn
 start=time.perf_counter()
 recommendation=await lib.search('2582a188-ff24-4a4f-b989-6063034d90b2',purpose,[{'role':'user','text':facts+'\n'+purpose}])
 owner=CodexTurn();config=Path.home()/'.codex/config.toml'
 names=re.findall(r'^\[mcp_servers\.([^\].]+)\]',config.read_text(encoding='utf-8'),re.M)
 try:
  await owner.start([{'role':'user','content':json.dumps({'facts':facts,'purpose':purpose,'available_patterns':recommendation['patterns'],'schema':lib.PLAN_SCHEMA},ensure_ascii=False)}],[],
   '日本語の12秒の短いモーショングラフィックを構成する。3〜5場面、合計12秒。場面ごとの長さは目的に合わせて決める。目的に合う演出を選ぶ。点数は参考であり必ず最大点を使う必要はない。事実や数字を足さない。色替えだけでなく順序・画面・間を演出する。テキストは簡潔で自然。文字だけで動くため実写を再現したと主張しない。schemaに合うplan JSONだけ返す。',
   'gpt-6-astra',config_overrides={'features.shell_tool':False,'features.fast_mode':True,'service_tier':'fast','model_reasoning_effort':'medium','project_doc_max_bytes':0,'skills.max_context_tokens':1,'mcp_servers':{n.strip('"'):{'enabled':False} for n in names}})
  output=''
  async def receive():
   nonlocal output
   while True:
    e=await owner.receive();method=e.get('method');p=e.get('params',{})
    if method=='item/agentMessage/delta':output+=p['delta']
    elif method=='turn/completed':
     if p['turn']['status']!='completed':raise RuntimeError('Planning failed')
     return
    elif method=='process/closed':raise RuntimeError('CLI closed')
    elif 'id' in e and method:owner.send({'id':e['id'],'error':{'code':-32601,'message':'No tools'}})
  await asyncio.wait_for(receive(),90)
  if output.startswith('```'):output=output.split('```')[1].removeprefix('json').strip()
  (OUT/(name+'-model-output.txt')).write_text(output,encoding='utf-8')
  plan=lib.validate(json.loads(output))
  assert abs(sum(b['duration'] for b in plan['beats'])-12)<.01
  result={'case':name,'facts':facts,'purpose':purpose,'recommendation':recommendation,'plan':plan,'planning_ms':round((time.perf_counter()-start)*1000)}
  (OUT/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'case':name,'planning_ms':result['planning_ms'],'patterns':[b['pattern'] for b in plan['beats']] }),flush=True)
 finally:owner.close()

async def main():
 for row in CASES:
  if not (OUT/(row[0]+'.json')).exists():await create(*row)

if __name__=='__main__':asyncio.run(main())
