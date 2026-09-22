"""Exercise keyboard routing without a microphone, production job or user focus."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser=p.chromium.launch(headless=True)
    page=browser.new_page()
    page.add_init_script('window.commands=[];window.ipc={postMessage:s=>commands.push(s)};')
    page.goto('http://127.0.0.1:8000/api/v1/editor-assistant/page')
    field=page.locator('#input')
    field.click();page.keyboard.type('hello')
    page.keyboard.press('Space')
    assert field.input_value()=='hello'
    assert page.evaluate("commands.filter(x=>x==='toggle_play').length")==1
    assert page.evaluate("!commands.includes('text_keyboard')")
    page.keyboard.press('Shift+Space');page.keyboard.type('world')
    assert field.input_value()=='hello world'
    page.keyboard.insert_text('朝の雰囲気にして')
    assert field.input_value().endswith('朝の雰囲気にして')
    page.evaluate("document.querySelector('#input').dispatchEvent(new CompositionEvent('compositionstart',{bubbles:true}))")
    count=page.evaluate('commands.length')
    page.keyboard.press('Space')
    assert page.evaluate('commands.length')==count
    page.evaluate("document.querySelector('#input').dispatchEvent(new CompositionEvent('compositionend',{bubbles:true}))")
    page.keyboard.press('Shift+Enter');page.keyboard.type('next')
    assert field.input_value().endswith('\nnext')
    # Simulate pointer focus on every control without executing its action.
    for selector in ['#mic','#send','#scope','#undo','#disconnect']:
        page.locator(selector).focus()
        count=page.evaluate("commands.filter(x=>x==='toggle_play').length")
        page.keyboard.press('Space')
        assert page.evaluate("commands.filter(x=>x==='toggle_play').length")==count+1
    browser.close()
print('PASS text entry, transport Space in all controls, Shift+Space, IME guard, newline')
