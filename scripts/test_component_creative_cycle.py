"""Isolated source-based creative trial through the actual subscription CLI.

Does not touch user rooms. Audio transport is not covered by this test.
"""
import asyncio, json, re, sys, time, hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / 'scratch/component-creative-cycle'
OUT.mkdir(parents=True, exist_ok=True)
BRIEF = 'Danの10秒の紹介映像。頭の中の映像を、会話しながら形にできることを伝える。プロンプトを書けない人が、自分でも作れそうと感じる。架空の機能や数字を実績として足さない。'

async def ask(name, payload, instruction, timeout=240):
    from app.services.editor_codex import CodexTurn
    owner = CodexTurn()
    config = Path.home() / '.codex/config.toml'
    names = re.findall(r'^\[mcp_servers\.([^\].]+)\]', config.read_text(encoding='utf-8'), re.M)
    started = time.perf_counter()
    output = ''
    try:
        await owner.start([{'role':'user','content':json.dumps(payload,ensure_ascii=False)}], [], instruction,
            'gpt-6-astra', config_overrides={'features.shell_tool':False,'features.fast_mode':True,
            'service_tier':'fast','model_reasoning_effort':'medium','project_doc_max_bytes':0,
            'skills.max_context_tokens':1,'mcp_servers':{n.strip('"'):{'enabled':False} for n in names}})
        async def receive():
            nonlocal output
            while True:
                e=await owner.receive();method=e.get('method');p=e.get('params',{})
                if method=='item/agentMessage/delta':output+=p['delta']
                elif method=='turn/completed':
                    if p['turn']['status']!='completed':raise RuntimeError(str(p['turn']))
                    return
                elif method=='process/closed':raise RuntimeError('CLI closed')
                elif 'id' in e and method:owner.send({'id':e['id'],'error':{'code':-32601,'message':'No tools in isolated trial'}})
        await asyncio.wait_for(receive(),timeout)
        elapsed=round((time.perf_counter()-started)*1000)
        if output.startswith('```'):output=output.split('```')[1].removeprefix('json').removeprefix('html').strip()
        (OUT/(name+'-response.txt')).write_text(output,encoding='utf-8')
        (OUT/(name+'-request.json')).write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
        (OUT/(name+'-timing.json')).write_text(json.dumps({'ms':elapsed,'model':'gpt-6-astra','transport':'subscription_cli','effort':'medium','fast':True}))
        print(json.dumps({'stage':name,'ms':elapsed}),flush=True)
        return output
    finally:owner.close()

async def plan():
    from app.services.editor_component_library import read
    rows=json.loads((ROOT/'docs/component-library.json').read_text(encoding='utf-8'))
    payload={'brief':BRIEF,'components':[{k:r.get(k) for k in ('id','title','description','family')} for r in rows]}
    response=await ask('plan',payload,
        '商業映像のディレクターとして、同じ目的を達成する、演出原理が異なる3案を提案する。日本語。'
        '既存部品の実装を改変して制作する。色替え・文言替えだけの3案にしない。10秒で伝わる簡潔さと読みやすさ。'
        '画像や人物生成はこの試験では不要。独自の内容を元実装で演出する。各案1〜2部品を選ぶ。'
        'JSONのみ {"directions":[{"id":"a","title":"短い名前","intent":"体験","visual":"見た目と動きの具体像","components":["hf-..."],"beats":[{"start":0,"end":3,"content":"..."}]}]}')
    plan=json.loads(response);assert len(plan['directions'])==3
    for d in plan['directions']:
        for ident in d['components']:read(ident)
    (OUT/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')

async def build():
    import shutil
    from app.services.editor_component_library import read
    shutil.copyfile(ROOT/'scratch/component-expansion/adapted/gsap.min.js',OUT/'gsap.min.js')
    plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
    for d in plan['directions']:
        path=OUT/(d['id']+'.html')
        if path.exists():continue
        sources=[]
        for ident in d['components']:
            entry=read(ident)
            for f in entry['files']:
                if f['file'].endswith('.html'):
                    source=read(ident,f['file'])
                    sources.append({'id':ident,'source_url':entry['source_url'],'file':f['file'],'source':source['source']})
        html=await ask('build-'+d['id'],{'brief':BRIEF,'direction':d,'sources':sources},
            '選んだ部品の実装を再利用・改変し、独自の完成品質を目指す10秒のモーショングラフィックHTMLを作る。'
            '元実装の特徴的なDOM/CSS/動きの仕組みを実際に活用し、単純な6種類の図形へ置き換えない。'
            '部品のサンプル文言やダミーデータは目的に適した内容に変更。原動画・スクショ・MP4の埋め込み禁止。'
            '日本語の見やすい文字組、強弱、余白、抑揚。過度な装飾や毎場面同じ配置を避ける。'
            '自己完結HTMLのみ。1920x1080の固定サイズ。Yu Gothic/Meiryo等ローカルフォント。'
            '依存はローカルgsap.min.jsだけ。他の外部画像・JS・フォントを使わない。必要なグラフィックはSVG/HTMLで。'
            'ルートdata-composition-id="sample" data-width="1920" data-height="1080" data-duration="10"。'
            'window.__timelines.sample = gsap.timeline({paused:true})を一つ登録。全ての時点にseek可能。'
            'Math.random, clocks, GSAP callbacksによるDOM変化, CSS animation, repeat:-1は禁止。'
            '修正のため最終メッセージのテキストをHTML中でid="closing-copy"の要素に置く。'
            '再生UIや自動再生は入れない。最終場面は9.99秒まで見える。最後の文字を切らない。')
        match=re.search(r'<!doctype html>.*?</html>',html,re.I|re.S)
        if match:html=match.group(0)
        assert '<html' in html and '__timelines' in html
        path.write_text(html,encoding='utf-8')
        (OUT/(d['id']+'-provenance.json')).write_text(json.dumps({'components':[
            {'id':s['id'],'url':s['source_url'],'sha256':hashlib.sha256(s['source'].encode()).hexdigest()} for s in sources]},indent=2))

async def improve():
    plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
    (OUT/'initial-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    rows=json.loads((ROOT/'docs/component-library.json').read_text(encoding='utf-8'))
    response=await ask('differentiate',{'brief':BRIEF,'plan':plan,'feedback':'AもBも円と文字が中心で見た目の幅が足りない。Bは別の表現へ。余白のある落ち着いた演出は保ち、画面やカードに奥行きのある立体的な構図を使って、会話から映像が具体化することを見せたい。AとCは維持。','components':[{k:r.get(k) for k in ('id','title','description')} for r in rows]},
        '既存の3案のBだけを改訂する。部品の特徴的な見た目を活かす。JSONでBのdirectionだけ返す。id,title,intent,visual,components,beats。10秒。')
    revised=json.loads(response);assert revised['id']=='b'
    plan['directions'][1]=revised
    (OUT/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
    (OUT/'b-initial.html').write_text((OUT/'b.html').read_text(encoding='utf-8'),encoding='utf-8')
    (OUT/'b.html').unlink()
    await build()

async def converse():
    from app.services.editor_jev import rank_candidates
    plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
    candidates=[{'id':d['id'],'title':d['title'],'description':d['visual'],'beats':d['beats']} for d in plan['directions']]
    # Desired direction is held by the evaluator, not sent as an answer label.
    cases=[('図で順番を説明するより、作れないかもって気持ちが軽くなる感じがいい。文字が大きく出るやつが近い。','c'),
           ('何を言うとどう変わるか、順を追って分かる方がいい。カード同士が線でつながるやつ。','a'),
           ('説明図や文字だけより、画面が手前に立ち上がってくる方。奥行きがあって、でも落ち着いているのがいい。','b')]
    results=[]
    for query,expected in cases:
        r=await rank_candidates('2582a188-ff24-4a4f-b989-6063034d90b2',[BRIEF,query],candidates)
        actual=candidates[r['order'][0]]['id'] if r and r['order'] else None
        results.append({'request':query,'expected':expected,'actual':actual,'pass':actual==expected,'result':r})
    (OUT/'narrowing.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    history=[{'role':'user','text':BRIEF},{'role':'assistant','text':'3つの動く見本を提示しました。'},
             {'role':'user','text':cases[0][0]}]
    response=await ask('conversation',{'conversation':history,'visible_examples':candidates},
        '制作の相談相手として自然な日本語で短く答える。表示済みの実物のどこが要望に合うかを具体的に捉える。'
        '決められない場合は見た目で答えられる比較を1つ聞く。工程の分類や制作中かどうかは説明しない。'
        'テスト接続のためJSON {"say":"発話","selected_id":"該当IDまたはnull","question":"必要な時だけ質問、なければnull"}のみ。')
    answer=json.loads(response);assert answer['selected_id']=='c',answer
    history.append({'role':'assistant','text':answer['say']})
    history.append({'role':'user','text':'最後の言葉だけ「うまく言えなくても、大丈夫。」にして。途中の見た目や動きはそのままで。'})
    response=await ask('revision',{'conversation':history,'selected':candidates[2],'scene':{'params':{'closing':'話しながら、映像に。'}}},
        '原文の変更指示を解釈し、必要最小限のrevise_presentationのchangesを返す。'
        'JSON {"say":"短い自然な返答","changes":[{"path":"JSON Pointer","value":"値"}]}のみ。')
    revision=json.loads(response)
    assert revision['changes']==[{'path':'/scene/params/closing','value':'うまく言えなくても、大丈夫。'}],revision
    (OUT/'conversation.json').write_text(json.dumps({'history':history,'selection':answer,'revision':revision},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'narrowing_passed':sum(r['pass'] for r in results),'cases':len(results)}),flush=True)

async def clarify():
    plan=json.loads((OUT/'plan.json').read_text(encoding='utf-8'))
    response=await ask('clarification',{'brief':BRIEF,'visible_examples':plan['directions'],'conversation':[{'role':'user','text':'まだ決められないな。どれが好きか自分でもよく分からない。少しずつ比べながら決めたい。'}]},
        '映像制作の相談相手として、いま見えている実物を比較して好みを絞れる短い質問をひとつする。専門用語で指定を要求しない。比較対象を2つにする。採用や制作を勝手に決めない。JSON {"say":"自然な短い質問","compare_ids":["ID","ID"],"selected_id":null}だけ返す。')
    result=json.loads(response)
    assert len(set(result['compare_ids']))==2 and result['selected_id'] is None
    assert set(result['compare_ids'])<=set(d['id'] for d in plan['directions'])
    (OUT/'clarification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':
    asyncio.run({'plan':plan,'build':build,'improve':improve,'converse':converse,'clarify':clarify}[sys.argv[1]]())
