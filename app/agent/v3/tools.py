"""
Tools - OpenClaw-style Direct Tool Definitions

LLMに直接渡すツール定義と実行ロジック。
シンプルに保つ：ツール定義 + 実行関数のみ。
"""

import asyncio
import base64
import logging
import subprocess
import shlex
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ============================================
# ツール定義（Anthropic Tool Use形式）
# ============================================

RESPOND_TO_USER_TOOL = {
    "name": "respond_to_user",
    "description": "ユーザーへの最終回答を出力する。タスク完了時や質問への回答時に使用。",
    "input_schema": {
        "type": "object",
        "properties": {
            "response": {
                "type": "string",
                "description": "ユーザーに表示する回答テキスト"
            }
        },
        "required": ["response"]
    }
}

BASH_TOOL = {
    "name": "bash",
    "description": """シェルコマンドを実行する。
ファイル操作、git、curl、ffmpeg等あらゆるコマンドを実行可能。
複雑なタスクはコマンドを組み合わせて解決する。

例:
- ファイル一覧: ls -la
- Git操作: git status, git commit -m "message"
- HTTP: curl -X GET https://api.example.com
- 音声変換: ffmpeg -i input.mp3 output.wav""",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "実行するシェルコマンド"
            },
            "working_dir": {
                "type": "string",
                "description": "作業ディレクトリ（省略時はカレント）"
            },
            "timeout": {
                "type": "integer",
                "description": "タイムアウト秒数（デフォルト: 60）"
            }
        },
        "required": ["command"]
    }
}

READ_FILE_TOOL = {
    "name": "read_file",
    "description": """ファイルの内容を読み込む。
テキストファイル、設定ファイル、コード等を読む。

例:
- path: "/path/to/file.txt"
- path: "config.json" """,
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "読み込むファイルのパス"
            },
            "encoding": {
                "type": "string",
                "description": "文字エンコーディング（デフォルト: utf-8）"
            }
        },
        "required": ["path"]
    }
}

WRITE_FILE_TOOL = {
    "name": "write_file",
    "description": """ファイルに内容を書き込む。
新規作成または上書き。ディレクトリが存在しない場合は自動作成。

例:
- path: "output.txt", content: "Hello World" """,
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "書き込むファイルのパス"
            },
            "content": {
                "type": "string",
                "description": "書き込む内容"
            },
            "encoding": {
                "type": "string",
                "description": "文字エンコーディング（デフォルト: utf-8）"
            }
        },
        "required": ["path", "content"]
    }
}

EDIT_FILE_TOOL = {
    "name": "edit_file",
    "description": """ファイルの一部を編集する（検索・置換）。
既存ファイルの特定部分を変更する場合に使用。

例:
- old_text: "function old()", new_text: "function new()" """,
    "input_schema": {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "編集するファイルのパス"
            },
            "old_text": {
                "type": "string",
                "description": "置換対象のテキスト（完全一致）"
            },
            "new_text": {
                "type": "string",
                "description": "置換後のテキスト"
            }
        },
        "required": ["path", "old_text", "new_text"]
    }
}

BROWSER_TOOL = {
    "name": "browser",
    "description": """ブラウザを操作する。
Webサイトの閲覧、フォーム入力、クリック、スクリーンショット取得が可能。

アクション:
- navigate: URLに移動
- click: セレクタをクリック
- type: テキストを入力
- screenshot: スクリーンショットを取得
- get_text: ページのテキストを取得
- get_html: HTMLを取得
- evaluate: JavaScriptを実行

例:
- action: "navigate", url: "https://google.com"
- action: "click", selector: "#submit-button"
- action: "type", selector: "input[name='q']", text: "検索ワード"
- action: "screenshot" """,
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["navigate", "click", "type", "screenshot", "get_text", "get_html", "evaluate", "scroll", "wait"],
                "description": "実行するアクション"
            },
            "url": {
                "type": "string",
                "description": "移動先URL（navigate時）"
            },
            "selector": {
                "type": "string",
                "description": "対象要素のCSSセレクタ（click, type時）"
            },
            "text": {
                "type": "string",
                "description": "入力するテキスト（type時）"
            },
            "script": {
                "type": "string",
                "description": "実行するJavaScript（evaluate時）"
            },
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "description": "スクロール方向（scroll時）"
            },
            "amount": {
                "type": "integer",
                "description": "スクロール量（ピクセル、scroll時）"
            },
            "seconds": {
                "type": "integer",
                "description": "待機秒数（wait時）"
            }
        },
        "required": ["action"]
    }
}

TAVILY_SEARCH_TOOL = {
    "name": "tavily_search",
    "description": """Web検索を実行して最新情報を取得する。
リアルタイムの情報（天気、価格、ニュース等）が必要な場合に使用。

例:
- query: "東京の天気"
- query: "Python 最新バージョン" """,
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "検索クエリ"
            },
            "search_depth": {
                "type": "string",
                "enum": ["basic", "advanced"],
                "description": "basic: 高速、advanced: 詳細（デフォルト: basic）"
            }
        },
        "required": ["query"]
    }
}

# 全ツール一覧
ALL_TOOLS = [
    RESPOND_TO_USER_TOOL,
    BASH_TOOL,
    READ_FILE_TOOL,
    WRITE_FILE_TOOL,
    EDIT_FILE_TOOL,
    BROWSER_TOOL,
    TAVILY_SEARCH_TOOL,
]


# ============================================
# ツール実行関数
# ============================================

class BrowserSession:
    """ブラウザセッション管理（シングルトン）"""
    _instance: Optional["BrowserSession"] = None
    _page = None
    _browser = None
    _context = None

    @classmethod
    async def get_instance(cls) -> "BrowserSession":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def get_page(self):
        """Playwrightページを取得（なければ起動）"""
        if self._page is None:
            from playwright.async_api import async_playwright

            playwright = await async_playwright().start()
            self._browser = await playwright.chromium.launch(headless=False)
            self._context = await self._browser.new_context(
                viewport={"width": 1280, "height": 720},
                locale="ja-JP",
            )
            self._page = await self._context.new_page()
        return self._page

    async def close(self):
        """ブラウザを閉じる"""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page = None
            BrowserSession._instance = None


async def execute_bash(command: str, working_dir: str = None, timeout: int = 60) -> Dict[str, Any]:
    """シェルコマンドを実行"""
    try:
        # Windowsの場合はshell=True、それ以外はshlex.split
        import platform
        is_windows = platform.system() == "Windows"

        result = subprocess.run(
            command if is_windows else shlex.split(command),
            shell=is_windows,
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"タイムアウト（{timeout}秒）"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def execute_read_file(path: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """ファイルを読み込む"""
    try:
        file_path = Path(path)
        if not file_path.exists():
            return {"success": False, "error": f"ファイルが存在しません: {path}"}

        content = file_path.read_text(encoding=encoding)
        return {
            "success": True,
            "content": content,
            "size": len(content),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def execute_write_file(path: str, content: str, encoding: str = "utf-8") -> Dict[str, Any]:
    """ファイルに書き込む"""
    try:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding=encoding)
        return {
            "success": True,
            "message": f"ファイルを書き込みました: {path}",
            "size": len(content),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def execute_edit_file(path: str, old_text: str, new_text: str) -> Dict[str, Any]:
    """ファイルを編集（検索・置換）"""
    try:
        file_path = Path(path)
        if not file_path.exists():
            return {"success": False, "error": f"ファイルが存在しません: {path}"}

        content = file_path.read_text(encoding="utf-8")
        if old_text not in content:
            return {"success": False, "error": "置換対象のテキストが見つかりません"}

        new_content = content.replace(old_text, new_text, 1)
        file_path.write_text(new_content, encoding="utf-8")

        return {
            "success": True,
            "message": f"ファイルを編集しました: {path}",
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


async def execute_browser(
    action: str,
    url: str = None,
    selector: str = None,
    text: str = None,
    script: str = None,
    direction: str = None,
    amount: int = None,
    seconds: int = None,
) -> Dict[str, Any]:
    """ブラウザを操作"""
    try:
        session = await BrowserSession.get_instance()
        page = await session.get_page()

        if action == "navigate":
            if not url:
                return {"success": False, "error": "URLが必要です"}
            await page.goto(url, wait_until="domcontentloaded")
            return {"success": True, "message": f"移動しました: {url}", "title": await page.title()}

        elif action == "click":
            if not selector:
                return {"success": False, "error": "セレクタが必要です"}
            await page.click(selector)
            return {"success": True, "message": f"クリックしました: {selector}"}

        elif action == "type":
            if not selector or text is None:
                return {"success": False, "error": "セレクタとテキストが必要です"}
            await page.fill(selector, text)
            return {"success": True, "message": f"入力しました: {selector}"}

        elif action == "screenshot":
            screenshot_bytes = await page.screenshot()
            screenshot_base64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            return {
                "success": True,
                "message": "スクリーンショットを取得しました",
                "screenshot_base64": screenshot_base64,
            }

        elif action == "get_text":
            text_content = await page.inner_text("body")
            return {"success": True, "text": text_content[:10000]}  # 10KB制限

        elif action == "get_html":
            html_content = await page.content()
            return {"success": True, "html": html_content[:50000]}  # 50KB制限

        elif action == "evaluate":
            if not script:
                return {"success": False, "error": "スクリプトが必要です"}
            result = await page.evaluate(script)
            return {"success": True, "result": result}

        elif action == "scroll":
            scroll_amount = amount or 500
            if direction == "up":
                scroll_amount = -scroll_amount
            await page.evaluate(f"window.scrollBy(0, {scroll_amount})")
            return {"success": True, "message": f"スクロールしました: {scroll_amount}px"}

        elif action == "wait":
            wait_seconds = seconds or 1
            await asyncio.sleep(wait_seconds)
            return {"success": True, "message": f"{wait_seconds}秒待機しました"}

        else:
            return {"success": False, "error": f"不明なアクション: {action}"}

    except Exception as e:
        return {"success": False, "error": str(e)}


async def execute_tavily_search(query: str, search_depth: str = "basic") -> Dict[str, Any]:
    """Web検索を実行"""
    try:
        from tavily import TavilyClient
        from app.config import settings

        client = TavilyClient(api_key=settings.TAVILY_API_KEY)
        response = client.search(query=query, search_depth=search_depth)

        results = []
        for r in response.get("results", [])[:5]:
            results.append({
                "title": r.get("title"),
                "url": r.get("url"),
                "content": r.get("content", "")[:500],
            })

        return {
            "success": True,
            "query": query,
            "results": results,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


# ツール名→実行関数のマッピング
TOOL_EXECUTORS = {
    "bash": execute_bash,
    "read_file": execute_read_file,
    "write_file": execute_write_file,
    "edit_file": execute_edit_file,
    "browser": execute_browser,
    "tavily_search": execute_tavily_search,
}


async def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """ツールを実行"""
    if tool_name == "respond_to_user":
        # respond_to_userは特別扱い（Runnerで処理）
        return {"success": True, "response": tool_input.get("response", "")}

    executor = TOOL_EXECUTORS.get(tool_name)
    if not executor:
        return {"success": False, "error": f"不明なツール: {tool_name}"}

    return await executor(**tool_input)
