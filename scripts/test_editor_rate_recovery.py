"""Server-rate failure schedules a retry; a new utterance invalidates that retry."""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    result=page.evaluate('''async()=>{
      const sent=[];dc={readyState:'open',send:s=>sent.push(JSON.parse(s))};turn={mode:'text'};
      handleResponseError({code:'rate_limit_exceeded',message:'Please try again in 0.01s.'});
      const readable=document.getElementById('state').textContent.includes('再開');
      await delay(2200);
      const retried=sent.some(e=>e.type==='response.create');
      sent.length=0;
      handleResponseError({code:'rate_limit_exceeded',message:'Please try again in 0.01s.'});
      epoch++;await delay(2200);
      return {readable,retried,old_retry_canceled:sent.length===0};
    }''')
    assert all(result.values()),result
    print(result)
    browser.close()
