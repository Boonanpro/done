"""Question reply and transient notification recovery without external inference."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page(bypass_csp=True)
    page.goto('http://127.0.0.1:8015/api/v1/editor-assistant/page')
    page.evaluate('()=>{context={room_id:"test",content_id:"test"};window.requests=[];request=async(path,body)=>{requests.push({path,body});return {ok:true};};}')
    s={'jobs':[{'id':'j','status':'running','question':{'id':'q','job_id':'j','text':'どちらの素材を使いますか？'}}]}
    page.evaluate('(s)=>renderProductionStatus(s,context)',s)
    page.evaluate('()=>{window.sent=[];send=e=>sent.push(e);turn={turn_id:"t",context};}')
    page.evaluate('async()=>{await addContext({context:{selected:[{text:"unrelated caption"}],visible_targets:[{id:"v"}],production:{active_count:1}},mode:"voice"},epoch);}')
    assert page.evaluate('requests.length===0&&sent.length===1&&sent[0].item.role==="system"&&!JSON.stringify(sent).includes("unrelated caption")')
    page.evaluate('async()=>{await onEvent({type:"response.function_call_arguments.done",name:"answer_question",call_id:"call",arguments:JSON.stringify({question_id:"q",text:"右の素材で"})});}')
    assert page.evaluate('requests.some(r=>r.path.endsWith("/answer")&&r.body.job_id==="j"&&r.body.text==="右の素材で")')
    assert page.evaluate('pendingQuestion===null')
    # A server failure must keep a notification available for bounded retry.
    page.evaluate('()=>{activeNotice={job_id:"j",room_id:"test",content_id:"test"};handleResponseError({code:"server_error",message:"temporary"});}')
    assert page.evaluate('completionNotices.length===1&&completionNotices[0].retries===1&&!active')
    page.evaluate('()=>{activeNotice=completionNotices.shift();activeNotice.retries=2;handleResponseError({code:"server_error"});}')
    assert page.evaluate('completionNotices.length===0')
    browser.close()
print('PASS question answer returns to same job; notification retry is bounded')
