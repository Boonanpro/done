"""Bounded Playwright-style statements through Dan's existing action boundary.

No Python eval/exec, imports, arbitrary JS or direct network access. Every action
uses the same browser, pause and confirmation mechanisms as individual calls.
"""
import ast
import json
from app.services import command_job_state as state

TOOL = {'name':'browser_script','description':'''画面で確認した操作をPython風コードでまとめて実行する。モデルとの往復を減らす。
対応構文は await page.goto("https://...")、await page.get_by_role("button", name="検索").click()、
await page.get_by_role("textbox", name="出発駅").fill("新大阪")、await page.get_by_text("予約一覧").click()、
await page.get_by_role("combobox", name="座席").select_option("value")。
1〜20文。条件判断が必要ならそこで区切り、結果を見て次のコードを渡す。任意Python/JS、importは不可。
途中の失敗で停止し、成功済み操作を再実行しない。購入等は従来どおり本人への確認で止まる。''',
 'input_schema':{'type':'object','properties':{'code':{'type':'string','maxLength':12000}},'required':['code']}}

def parse(code):
    tree=ast.parse(code)
    if not 1<=len(tree.body)<=20: raise ValueError('1〜20個のawait操作を指定してください')
    steps=[]
    for stmt in tree.body:
        if not isinstance(stmt,ast.Expr) or not isinstance(stmt.value,ast.Await): raise ValueError('await操作だけを指定してください')
        call=stmt.value.value
        if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Attribute): raise ValueError('pageの操作が必要です')
        args=[ast.literal_eval(v) for v in call.args]
        if call.keywords: raise ValueError('操作の引数は位置引数で指定してください')
        target=call.func.value;method=call.func.attr
        if isinstance(target,ast.Name) and target.id=='page' and method=='goto' and len(args)==1:
            steps.append({'action':'open_target','url':args[0]});continue
        if not isinstance(target,ast.Call) or not isinstance(target.func,ast.Attribute): raise ValueError('対応していない操作です')
        if not isinstance(target.func.value,ast.Name) or target.func.value.id!='page': raise ValueError('pageだけが使えます')
        selector=target.func.attr
        values=[ast.literal_eval(v) for v in target.args]
        kw={k.arg:ast.literal_eval(k.value) for k in target.keywords}
        if selector not in {'get_by_role','get_by_text'} or len(values)!=1 or set(kw)-{'name'}: raise ValueError('role/textの完全一致を指定してください')
        if method not in {'click','fill','select_option'} or len(args)!=(0 if method=='click' else 1): raise ValueError('click/fill/select_optionが使えます')
        if selector=='get_by_role' and not isinstance(kw.get('name'),str): raise ValueError('roleにはnameが必要です')
        if not all(isinstance(x,str) for x in [*values,*args,*kw.values()]): raise ValueError('文字列を指定してください')
        steps.append({'action':{'click':'click','fill':'type','select_option':'select'}[method],
            'locator':{'kind':selector,'value':values[0],**kw},**({'text' if method=='fill' else 'value':args[0]} if args else {})})
    return steps

async def resolve(page, locator):
    await page.get_interactive_elements()
    query=json.dumps(locator,ensure_ascii=False)
    result=await page.evaluate('''(() => {const q='''+query+''';const norm=s=>(s||'').replace(/\s+/g,' ').trim();
      const nodes=[...document.querySelectorAll('[data-dan-ref]')].filter(e=>e.getBoundingClientRect().width&&e.getBoundingClientRect().height);
      const role=e=>e.getAttribute('role')||({BUTTON:'button',A:'link',TEXTAREA:'textbox',SELECT:'combobox'}[e.tagName])||
        (e.tagName==='INPUT'?(['submit','button'].includes(e.type)?'button':['checkbox','radio'].includes(e.type)?e.type:'textbox'):'');
      const name=e=>norm(e.getAttribute('aria-label')||(e.labels&&e.labels[0]?.innerText)||e.innerText||e.placeholder||e.value);
      const found=nodes.filter(e=>q.kind==='get_by_role'?role(e)===q.value&&name(e)===norm(q.name):norm(e.innerText)===norm(q.value));
      return {count:found.length,ref:found.length===1?found[0].getAttribute('data-dan-ref'):null};})()''')
    if result.get('count')!=1: raise ValueError('対象が一意に見つかりません。画面を読み直してください')
    return '@'+result['ref']

async def run(job_id,code):
    from app.services.command_job_tools import available,guard
    from app.agent.v2.tools import _execute_browser_tool
    from app.tools.browser import get_executor_page
    steps=parse(code) # Validate the entire script before the first side effect.
    initial=await available(job_id)
    completed=[];approved=[];result=None
    for index,step in enumerate(steps):
        current=await available(job_id)
        if current['revision']!=initial['revision']:
            return {'success':False,'completed':completed,'error':'追加指示が届いたため残りのコードを停止しました'}
        try:
            args=dict(step)
            if 'locator' in args:args['ref']=await resolve(await get_executor_page(),args.pop('locator'))
            approval=await guard(job_id,'browser',args)
            if approval: approved.append(index+1)
            state.change(job_id,lambda s:s.update(current_tool={'name':'browser_script','action':args['action'],'step':index+1,'started_at':state.now()}))
            result=await _execute_browser_tool(args['action'],args)
            observation='\n'.join(c.get('text','') for c in result.get('content',[]) if c.get('type')=='text')
            if observation:state.change(job_id,lambda s:s.update(last_observation={'text':observation[:3500],'at':state.now()}))
            state.publish(job_id,'tool','browser_script:'+args['action'])
            if not result.get('success'): return {**result,'completed':completed,'failed_step':index+1}
            completed.append(index+1)
        except Exception as exc:
            return {'success':False,'completed':completed,'failed_step':index+1,'error':str(exc)}
        finally:state.change(job_id,lambda s:s.update(current_tool=None))
    return {**(result or {}),'completed':completed,'user_approved_steps':approved}
