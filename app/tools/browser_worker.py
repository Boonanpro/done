#!/usr/bin/env python
"""
Browser Worker - Subprocess for Playwright operations
Runs in a separate process to avoid Windows asyncio issues
"""
import sys
import json
import os

from playwright.sync_api import sync_playwright


# グローバル変数
_playwright = None
_browser = None
_context = None
_page = None


def ensure_browser():
    """ブラウザを初期化"""
    global _playwright, _browser, _context, _page
    
    if _page is not None:
        return _page
    
    _playwright = sync_playwright().start()
    _browser = _playwright.chromium.launch(headless=False)
    
    user_data_dir = os.path.join(os.path.expanduser("~"), ".ai_secretary", "browser_data")
    os.makedirs(user_data_dir, exist_ok=True)
    
    _context = _browser.new_context(
        viewport={"width": 1280, "height": 720},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    )
    _page = _context.new_page()
    
    return _page


def cleanup():
    """ブラウザをクリーンアップ"""
    global _playwright, _browser, _context, _page
    
    if _page:
        _page.close()
        _page = None
    if _context:
        _context.close()
        _context = None
    if _browser:
        _browser.close()
        _browser = None
    if _playwright:
        _playwright.stop()
        _playwright = None


def handle_command(command: str, args: dict) -> dict:
    """コマンドを処理"""
    try:
        page = ensure_browser()
        
        if command == "goto":
            url = args.get("url", "")
            wait_until = args.get("wait_until", "domcontentloaded")
            timeout = args.get("timeout", 30000)
            page.goto(url, wait_until=wait_until, timeout=timeout)
            return {"success": True}
            
        elif command == "wait_for_load_state":
            state = args.get("state", "domcontentloaded")
            page.wait_for_load_state(state)
            return {"success": True}
            
        elif command == "query_selector":
            selector = args.get("selector", "")
            element = page.query_selector(selector)
            return {"success": True, "found": element is not None}
            
        elif command == "query_selector_all":
            selector = args.get("selector", "")
            elements = page.query_selector_all(selector)
            return {"success": True, "count": len(elements)}
            
        elif command == "fill":
            selector = args.get("selector", "")
            value = args.get("value", "")
            page.fill(selector, value)
            return {"success": True}
            
        elif command == "click":
            selector = args.get("selector", "")
            page.click(selector)
            return {"success": True}
            
        elif command == "get_url":
            return {"success": True, "url": page.url}
            
        elif command == "get_title":
            return {"success": True, "title": page.title()}
            
        elif command == "screenshot":
            path = args.get("path", "screenshot.png")
            full_page = args.get("full_page", True)
            page.screenshot(path=path, full_page=full_page)
            return {"success": True, "path": path}
            
        elif command == "evaluate":
            expression = args.get("expression", "")
            result = page.evaluate(expression)
            return {"success": True, "result": result}
            
        elif command == "text_content":
            selector = args.get("selector", "")
            element = page.query_selector(selector)
            if element:
                return {"success": True, "text": element.text_content()}
            return {"success": True, "text": None}
            
        elif command == "cleanup":
            cleanup()
            return {"success": True}
            
        else:
            return {"success": False, "error": f"Unknown command: {command}"}
            
    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    """メイン処理"""
    # 標準入力からコマンドを読み取る
    input_data = sys.stdin.read()
    
    try:
        data = json.loads(input_data)
        command = data.get("command", "")
        args = data.get("args", {})
        
        result = handle_command(command, args)
        
        # 結果を出力
        print(json.dumps(result))
        
    except Exception as e:
        print(json.dumps({"success": False, "error": str(e)}))
    finally:
        # 処理完了後にクリーンアップはしない（セッション維持のため）
        pass


if __name__ == "__main__":
    main()

