"""
Visual Agent Actions

視覚エージェントが実行可能なアクション定義。
LLMが選択するアクションのスキーマと実行ロジック。
"""

import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from app.executors.visual.history import ActionType

logger = logging.getLogger(__name__)


@dataclass
class ActionResult:
    """アクション実行結果"""
    success: bool
    message: str = ""
    data: Dict[str, Any] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.data is None:
            self.data = {}

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "success": self.success,
            "message": self.message,
        }
        if self.data:
            result.update(self.data)
        if self.error:
            result["error"] = self.error
        return result


# ============================================
# アクション定義（LLMが選択するツール）
# ============================================

VISUAL_AGENT_ACTIONS = [
    {
        "name": "navigate",
        "description": "指定したURLに移動する",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "移動先のURL"
                }
            },
            "required": ["url"]
        }
    },
    {
        "name": "click",
        "description": "画面上の指定座標をクリックする",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "クリックするX座標（ピクセル）"
                },
                "y": {
                    "type": "number",
                    "description": "クリックするY座標（ピクセル）"
                },
                "description": {
                    "type": "string",
                    "description": "クリックする要素の説明（ログ用）"
                }
            },
            "required": ["x", "y"]
        }
    },
    {
        "name": "type",
        "description": "テキストを入力する。事前にclickで入力欄をクリックしてフォーカスを当てておくこと。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "入力するテキスト"
                },
                "clear_first": {
                    "type": "boolean",
                    "description": "入力前にフィールドをクリアするか（デフォルト: false）"
                },
                "press_enter": {
                    "type": "boolean",
                    "description": "入力後にEnterキーを押すか（デフォルト: false）"
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "press_key",
        "description": "キーボードのキーを押す（Escape、Tab、Enterなど）",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "押すキー（例: Escape, Tab, Enter, ArrowDown, ArrowUp, Backspace）"
                }
            },
            "required": ["key"]
        }
    },
    {
        "name": "scroll",
        "description": "ページをスクロールする",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "left", "right"],
                    "description": "スクロール方向"
                },
                "amount": {
                    "type": "number",
                    "description": "スクロール量（ピクセル、デフォルト: 500）"
                }
            },
            "required": ["direction"]
        }
    },
    {
        "name": "wait",
        "description": "指定した時間待機する、またはページの読み込みを待つ",
        "parameters": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "description": "待機秒数（デフォルト: 2）"
                },
                "for_navigation": {
                    "type": "boolean",
                    "description": "ページ遷移を待つか"
                }
            }
        }
    },
    {
        "name": "done",
        "description": "タスクが完了したことを報告する",
        "parameters": {
            "type": "object",
            "properties": {
                "success": {
                    "type": "boolean",
                    "description": "タスクが成功したか"
                },
                "message": {
                    "type": "string",
                    "description": "完了メッセージ（ユーザーに表示）"
                },
                "extracted_data": {
                    "type": "object",
                    "description": "抽出したデータ（価格、商品名など）"
                }
            },
            "required": ["success", "message"]
        }
    },
    {
        "name": "ask_user",
        "description": "ユーザーに確認や選択を求める。複数選択肢がある場合や、確認が必要な場合に使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "ユーザーへの質問"
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "選択肢（ある場合）"
                },
                "context": {
                    "type": "string",
                    "description": "質問の文脈（ログ用）"
                }
            },
            "required": ["question"]
        }
    },
    {
        "name": "go_back",
        "description": "ブラウザの戻るボタンを押す。前のページに戻りたい時に使用。",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "go_forward",
        "description": "ブラウザの進むボタンを押す。戻った後に再び先に進みたい時に使用。",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "refresh",
        "description": "ページを再読み込みする。ページが正しく表示されない時や、最新情報を取得したい時に使用。",
        "parameters": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "hover",
        "description": "指定座標にマウスを移動する（クリックはしない）。ドロップダウンメニューを表示させたい時などに使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {
                    "type": "number",
                    "description": "ホバーするX座標（ピクセル）"
                },
                "y": {
                    "type": "number",
                    "description": "ホバーするY座標（ピクセル）"
                },
                "description": {
                    "type": "string",
                    "description": "ホバーする要素の説明（ログ用）"
                }
            },
            "required": ["x", "y"]
        }
    },
    {
        "name": "run_script",
        "description": "スキルフォルダ内のPythonスクリプトを実行する。手順書で [SCRIPT: xxx.py] と指示された場合に使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "script_name": {
                    "type": "string",
                    "description": "実行するスクリプト名（例: fill_credentials.py）"
                },
                "skill_name": {
                    "type": "string",
                    "description": "スキル名（スクリプトの場所を特定するため）"
                },
                "args": {
                    "type": "object",
                    "description": "スクリプトに渡す引数"
                }
            },
            "required": ["script_name", "skill_name"]
        }
    },
    {
        "name": "read_manual",
        "description": "スキルのアクション手順書を読む。SKILL.md の目次を見て、必要なアクションの詳細を取得する場合に使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "action_name": {
                    "type": "string",
                    "description": "読みたいアクション名（例: 'login', 'search', 'add-to-cart'）"
                }
            },
            "required": ["action_name"]
        }
    },
]


class ActionExecutor:
    """
    アクション実行器

    VisualAgentから呼び出され、実際のブラウザ操作を実行。
    """

    def __init__(self, page, skill_name: Optional[str] = None):
        """
        Args:
            page: ExecutorPageProxy インスタンス
            skill_name: スキル名（read_manual で使用）
        """
        self.page = page
        self.skill_name = skill_name

    async def _validate_selectors(self, selectors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """セレクタ候補を軽く検証（件数・可視・有効）"""
        if not selectors:
            return []

        probes: List[Dict[str, Any]] = []
        for candidate in selectors:
            if not isinstance(candidate, dict):
                continue
            selector = candidate.get("selector")
            if not selector:
                continue

            probe = {
                "selector": selector,
                "type": candidate.get("type"),
                "reliability": candidate.get("reliability"),
            }
            try:
                locator = self.page.locator(selector)
                count = await locator.count()
                probe["match_count"] = count
                probe["unique"] = (count == 1)
                if count > 0:
                    probe["first_visible"] = await locator.first.is_visible()
                    try:
                        probe["first_enabled"] = await locator.first.is_enabled()
                    except Exception:
                        probe["first_enabled"] = None
                else:
                    probe["first_visible"] = False
                    probe["first_enabled"] = None
            except Exception as e:
                probe["error"] = str(e)

            probes.append(probe)

        return probes

    async def execute(
        self,
        action_name: str,
        params: Dict[str, Any],
    ) -> ActionResult:
        """
        アクションを実行

        Args:
            action_name: アクション名
            params: パラメータ

        Returns:
            ActionResult: 実行結果
        """
        # キャンセルチェック（キャンセルされていたらCancelledErrorを発生）
        from app.services.cancellation import CancellationRegistry
        CancellationRegistry.check_cancelled_raise()

        try:
            if action_name == "navigate":
                return await self._navigate(params)
            elif action_name == "click":
                return await self._click(params)
            elif action_name == "type":
                return await self._type(params)
            elif action_name == "press_key":
                return await self._press_key(params)
            elif action_name == "scroll":
                return await self._scroll(params)
            elif action_name == "wait":
                return await self._wait(params)
            elif action_name == "done":
                return await self._done(params)
            elif action_name == "ask_user":
                return await self._ask_user(params)
            elif action_name == "go_back":
                return await self._go_back(params)
            elif action_name == "go_forward":
                return await self._go_forward(params)
            elif action_name == "refresh":
                return await self._refresh(params)
            elif action_name == "hover":
                return await self._hover(params)
            elif action_name == "run_script":
                return await self._run_script(params)
            elif action_name == "read_manual":
                return await self._read_manual(params)
            else:
                return ActionResult(
                    success=False,
                    error=f"Unknown action: {action_name}"
                )

        except Exception as e:
            logger.error(f"Action {action_name} failed: {e}", exc_info=True)
            return ActionResult(
                success=False,
                error=str(e)
            )

    async def _navigate(self, params: Dict[str, Any]) -> ActionResult:
        """URLに移動"""
        url = params.get("url", "")
        if not url:
            return ActionResult(success=False, error="URL is required")

        await self.page.goto(url)
        await self.page.wait_for_timeout(3000)

        current_url = self.page.url
        return ActionResult(
            success=True,
            message=f"Navigated to {url}",
            data={"current_url": current_url}
        )

    async def _click(self, params: Dict[str, Any]) -> ActionResult:
        """指定座標をクリック（新しいタブが開いたら自動で切り替え）"""
        x = params.get("x")
        y = params.get("y")
        description = params.get("description", "element")

        if x is None or y is None:
            return ActionResult(
                success=False,
                error="x and y coordinates are required"
            )

        # クリック前に要素情報を取得（セレクタ抽出用）
        element_info = await self._get_element_info_at_point(int(x), int(y))

        selector_probes = []
        if element_info:
            selectors = element_info.get("selectors", [])
            selector_probes = await self._validate_selectors(selectors)

        # クリック前のタブ数を記録
        tab_info_before = await self.page.get_tab_count()
        tab_count_before = tab_info_before.get("count", 1)

        await self.page.mouse.click(float(x), float(y))
        await self.page.wait_for_timeout(3000)

        # 新しいタブが開いたかチェック
        tab_info_after = await self.page.get_tab_count()
        tab_count_after = tab_info_after.get("count", 1)
        new_tab_opened = tab_count_after > tab_count_before

        # 結果データを構築
        result_data = {
            "x": x,
            "y": y,
            "new_tab": new_tab_opened,
        }

        # 要素情報とセレクタを追加
        if element_info:
            result_data["element_info"] = element_info.get("element_info")
            selectors = element_info.get("selectors", [])
            result_data["selectors"] = selectors
            if selector_probes:
                result_data["selector_probes"] = selector_probes

        if new_tab_opened:
            # 新しいタブに切り替え
            switch_result = await self.page.switch_to_latest_tab()
            logger.info(f"New tab detected and switched: {switch_result.get('url')}")
            result_data["new_url"] = switch_result.get("url")
            return ActionResult(
                success=True,
                message=f"Clicked {description} (new tab opened and switched)",
                data=result_data
            )

        return ActionResult(
            success=True,
            message=f"Clicked {description}",
            data=result_data
        )

    async def _get_element_info_at_point(self, x: int, y: int) -> Optional[Dict[str, Any]]:
        """
        座標から要素情報とセレクタ候補を取得

        Args:
            x: X座標
            y: Y座標

        Returns:
            要素情報とセレクタ候補を含む辞書
        """
        try:
            result = await self.page.evaluate(f"""
            () => {{
                const elem = document.elementFromPoint({x}, {y});
                if (!elem) return null;

                // 基本情報
                const info = {{
                    tagName: elem.tagName.toLowerCase(),
                    id: elem.id || null,
                    className: (typeof elem.className === 'string') ? elem.className : null,
                    name: elem.getAttribute('name'),
                    type: elem.getAttribute('type'),
                    placeholder: elem.getAttribute('placeholder'),
                    role: elem.getAttribute('role'),
                    ariaLabel: elem.getAttribute('aria-label'),
                    dataTestId: elem.getAttribute('data-testid'),
                    textContent: (elem.textContent || '').trim().slice(0, 50),
                }};

                // セレクタ候補を生成（優先順位順）
                const selectors = [];

                // 1. ID（最高優先）
                if (elem.id) {{
                    selectors.push({{
                        selector: '#' + elem.id,
                        type: 'id',
                        reliability: 'high'
                    }});
                }}

                // 2. name属性
                if (elem.getAttribute('name')) {{
                    selectors.push({{
                        selector: elem.tagName.toLowerCase() + '[name="' + elem.getAttribute('name') + '"]',
                        type: 'name',
                        reliability: 'high'
                    }});
                }}

                // 3. data-testid
                if (elem.getAttribute('data-testid')) {{
                    selectors.push({{
                        selector: '[data-testid="' + elem.getAttribute('data-testid') + '"]',
                        type: 'data-testid',
                        reliability: 'high'
                    }});
                }}

                // 4. role + aria-label（Playwright locator形式）
                if (elem.getAttribute('role') && elem.getAttribute('aria-label')) {{
                    selectors.push({{
                        selector: 'role=' + elem.getAttribute('role') + '[name="' + elem.getAttribute('aria-label') + '"]',
                        type: 'role+aria',
                        reliability: 'medium'
                    }});
                }}

                // 4b. aria-label単体（roleがなくてもaria-labelがあれば使える）
                if (elem.getAttribute('aria-label') && !elem.getAttribute('role')) {{
                    selectors.push({{
                        selector: '[aria-label="' + elem.getAttribute('aria-label') + '"]',
                        type: 'aria-label',
                        reliability: 'medium'
                    }});
                }}

                // 5. placeholder
                if (elem.getAttribute('placeholder')) {{
                    selectors.push({{
                        selector: '[placeholder="' + elem.getAttribute('placeholder') + '"]',
                        type: 'placeholder',
                        reliability: 'medium'
                    }});
                }}

                // 6. class（最低優先、minifiedでなければ）
                if (info.className && info.className.trim()) {{
                    const classes = info.className.trim().split(/\\s+/).slice(0, 2);
                    // minified class（ランダムな文字列）を除外
                    const isMinified = classes.some(c => c.length > 20 || /^[a-z]{{1,3}}[A-Z]/.test(c));
                    if (!isMinified && classes.length > 0 && classes[0].length < 25) {{
                        selectors.push({{
                            selector: elem.tagName.toLowerCase() + '.' + classes.join('.'),
                            type: 'class',
                            reliability: 'low'
                        }});
                    }}
                }}

                return {{
                    element_info: info,
                    selectors: selectors
                }};
            }}
            """)
            return result
        except Exception as e:
            logger.warning(f"Failed to get element info at ({x}, {y}): {e}")
            return None

    async def _get_active_element_info(self) -> Optional[Dict[str, Any]]:
        """
        フォーカス中の要素情報とセレクタ候補を取得
        """
        try:
            result = await self.page.evaluate("""
            () => {
                const elem = document.activeElement;
                if (!elem) return null;

                const info = {
                    tagName: elem.tagName.toLowerCase(),
                    id: elem.id || null,
                    className: (typeof elem.className === 'string') ? elem.className : null,
                    name: elem.getAttribute('name'),
                    type: elem.getAttribute('type'),
                    placeholder: elem.getAttribute('placeholder'),
                    role: elem.getAttribute('role'),
                    ariaLabel: elem.getAttribute('aria-label'),
                    dataTestId: elem.getAttribute('data-testid'),
                    textContent: (elem.textContent || '').trim().slice(0, 50),
                };

                const selectors = [];

                if (elem.id) {
                    selectors.push({
                        selector: '#' + elem.id,
                        type: 'id',
                        reliability: 'high'
                    });
                }

                if (elem.getAttribute('name')) {
                    selectors.push({
                        selector: elem.tagName.toLowerCase() + '[name="' + elem.getAttribute('name') + '"]',
                        type: 'name',
                        reliability: 'high'
                    });
                }

                if (elem.getAttribute('data-testid')) {
                    selectors.push({
                        selector: '[data-testid="' + elem.getAttribute('data-testid') + '"]',
                        type: 'data-testid',
                        reliability: 'high'
                    });
                }

                if (elem.getAttribute('role') && elem.getAttribute('aria-label')) {
                    selectors.push({
                        selector: 'role=' + elem.getAttribute('role') + '[name="' + elem.getAttribute('aria-label') + '"]',
                        type: 'role+aria',
                        reliability: 'medium'
                    });
                }

                if (elem.getAttribute('aria-label') && !elem.getAttribute('role')) {
                    selectors.push({
                        selector: '[aria-label="' + elem.getAttribute('aria-label') + '"]',
                        type: 'aria-label',
                        reliability: 'medium'
                    });
                }

                if (elem.getAttribute('placeholder')) {
                    selectors.push({
                        selector: '[placeholder="' + elem.getAttribute('placeholder') + '"]',
                        type: 'placeholder',
                        reliability: 'medium'
                    });
                }

                if (elem.classList && elem.classList.length > 0) {
                    const classes = Array.from(elem.classList).slice(0, 3);
                    if (classes.length > 0) {
                        selectors.push({
                            selector: elem.tagName.toLowerCase() + '.' + classes.join('.'),
                            type: 'class',
                            reliability: 'low'
                        });
                    }
                }

                return {
                    element_info: info,
                    selectors: selectors
                };
            }
            """)
            return result
        except Exception as e:
            logger.warning(f"Failed to get active element info: {e}")
            return None

    async def _type(self, params: Dict[str, Any]) -> ActionResult:
        """テキストを入力（事前にclickでフォーカスを当てておくこと）"""
        text = params.get("text", "")
        clear_first = params.get("clear_first", False)  # デフォルトをFalseに変更
        press_enter = params.get("press_enter", False)

        if not text:
            return ActionResult(success=False, error="Text is required")

        try:
            # フォーカス要素の情報を取得（セレクタ抽出用）
            element_info = await self._get_active_element_info()

            # 既存のテキストをクリア（入力欄内のみ）
            if clear_first:
                # 入力欄の内容だけをクリアする安全な方法:
                # 1. End キーで末尾に移動
                # 2. Ctrl+Shift+Home で先頭まで選択
                # 3. Delete で削除
                # これにより、フォーカスが入力欄にない場合でもページ全体が選択されない
                await self.page.keyboard.press("End")
                await self.page.keyboard.press("Control+Shift+Home")
                await self.page.keyboard.press("Delete")
                await self.page.wait_for_timeout(100)

            # テキストを入力
            await self.page.keyboard.type(text, delay=50)
            logger.info(f"Typed {len(text)} chars via keyboard")

            if press_enter:
                await self.page.keyboard.press("Enter")
                await self.page.wait_for_timeout(1500)

            result_data = {"text_length": len(text), "press_enter": press_enter}
            if element_info:
                result_data["element_info"] = element_info.get("element_info")
                selectors = element_info.get("selectors", [])
                result_data["selectors"] = selectors
                selector_probes = await self._validate_selectors(selectors)
                if selector_probes:
                    result_data["selector_probes"] = selector_probes

            return ActionResult(
                success=True,
                message=f"Typed text ({len(text)} chars)",
                data=result_data
            )

        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Keyboard input failed: {e}"
            )

    async def _press_key(self, params: Dict[str, Any]) -> ActionResult:
        """キーを押す"""
        key = params.get("key", "")
        if not key:
            return ActionResult(success=False, error="Key is required")

        try:
            await self.page.keyboard.press(key)
            await self.page.wait_for_timeout(1000)

            return ActionResult(
                success=True,
                message=f"Pressed {key}",
                data={"key": key}
            )

        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Key press failed: {e}"
            )

    async def _scroll(self, params: Dict[str, Any]) -> ActionResult:
        """スクロール"""
        direction = params.get("direction", "down")
        amount = int(params.get("amount", 500))

        scroll_map = {
            "up": (0, -amount),
            "down": (0, amount),
            "left": (-amount, 0),
            "right": (amount, 0),
        }

        dx, dy = scroll_map.get(direction, (0, amount))
        await self.page.evaluate(f"window.scrollBy({dx}, {dy})")
        await self.page.wait_for_timeout(800)

        return ActionResult(
            success=True,
            message=f"Scrolled {direction} by {amount}px",
            data={"direction": direction, "amount": amount}
        )

    async def _wait(self, params: Dict[str, Any]) -> ActionResult:
        """待機"""
        seconds = float(params.get("seconds", 2))
        for_navigation = params.get("for_navigation", False)

        if for_navigation:
            await self.page.wait_for_load_state("domcontentloaded")
        else:
            await self.page.wait_for_timeout(int(seconds * 1000))

        return ActionResult(
            success=True,
            message=f"Waited {seconds}s",
            data={"seconds": seconds}
        )

    async def _done(self, params: Dict[str, Any]) -> ActionResult:
        """タスク完了"""
        success = params.get("success", True)
        message = params.get("message", "Task completed")
        extracted_data = params.get("extracted_data", {})

        return ActionResult(
            success=success,
            message=message,
            data={"extracted_data": extracted_data, "is_done": True}
        )

    async def _ask_user(self, params: Dict[str, Any]) -> ActionResult:
        """ユーザーに確認"""
        question = params.get("question", "")
        options = params.get("options", [])
        context = params.get("context", "")

        return ActionResult(
            success=True,
            message=question,
            data={
                "requires_user_input": True,
                "options": options,
                "context": context,
            }
        )

    async def _go_back(self, params: Dict[str, Any]) -> ActionResult:
        """ブラウザの戻るボタン"""
        try:
            result = await self.page.go_back()
            await self.page.wait_for_timeout(2000)
            current_url = self.page.url
            return ActionResult(
                success=True,
                message=f"Navigated back",
                data={"url": current_url}
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Go back failed: {e}"
            )

    async def _go_forward(self, params: Dict[str, Any]) -> ActionResult:
        """ブラウザの進むボタン"""
        try:
            result = await self.page.go_forward()
            await self.page.wait_for_timeout(2000)
            current_url = self.page.url
            return ActionResult(
                success=True,
                message=f"Navigated forward",
                data={"url": current_url}
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Go forward failed: {e}"
            )

    async def _refresh(self, params: Dict[str, Any]) -> ActionResult:
        """ページを再読み込み"""
        try:
            result = await self.page.reload()
            await self.page.wait_for_timeout(2000)
            current_url = self.page.url
            return ActionResult(
                success=True,
                message=f"Page refreshed",
                data={"url": current_url}
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Refresh failed: {e}"
            )

    async def _hover(self, params: Dict[str, Any]) -> ActionResult:
        """マウスホバー"""
        x = params.get("x")
        y = params.get("y")
        description = params.get("description", "element")

        if x is None or y is None:
            return ActionResult(
                success=False,
                error="x and y coordinates are required"
            )

        try:
            # ホバー前に要素情報を取得（セレクタ抽出用）
            element_info = await self._get_element_info_at_point(int(x), int(y))

            await self.page.mouse.move(float(x), float(y))
            await self.page.wait_for_timeout(1000)

            # 結果データを構築
            result_data = {"x": x, "y": y}
            if element_info:
                result_data["element_info"] = element_info.get("element_info")
                selectors = element_info.get("selectors", [])
                result_data["selectors"] = selectors
                selector_probes = await self._validate_selectors(selectors)
                if selector_probes:
                    result_data["selector_probes"] = selector_probes

            return ActionResult(
                success=True,
                message=f"Hovered over {description}",
                data=result_data
            )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"Hover failed: {e}"
            )

    async def _run_script(self, params: Dict[str, Any]) -> ActionResult:
        """
        スキルフォルダ内のPythonスクリプトを実行

        手順書に [SCRIPT: xxx.py] と指示された場合に使用。
        スキルフォルダ内の scripts/ ディレクトリにあるスクリプトのみ実行可能。

        Args:
            params:
                - script_name: スクリプト名（例: fill_credentials.py）
                - skill_name: スキル名（例: amazon）
                - args: スクリプトに渡す引数（dict）
        """
        import importlib.util
        from pathlib import Path

        script_name = params.get("script_name", "")
        skill_name = params.get("skill_name", "")
        args = params.get("args", {})

        if not script_name or not skill_name:
            return ActionResult(
                success=False,
                error="script_name と skill_name は必須です"
            )

        # スキルフォルダを特定
        skill_dirs = [
            Path(__file__).parent.parent.parent.parent / ".claude" / "skills",  # プロジェクトルート
        ]

        script_path = None
        for skill_dir in skill_dirs:
            candidate = skill_dir / skill_name / "scripts" / script_name
            if candidate.exists():
                script_path = candidate
                break

            # .py 拡張子なしで指定された場合
            if not script_name.endswith(".py"):
                candidate_py = skill_dir / skill_name / "scripts" / f"{script_name}.py"
                if candidate_py.exists():
                    script_path = candidate_py
                    break

        if not script_path:
            return ActionResult(
                success=False,
                error=f"スクリプトが見つかりません: {skill_name}/scripts/{script_name}",
                data={"searched_dirs": [str(d) for d in skill_dirs]}
            )

        # セキュリティチェック: スキルフォルダ外へのパス・トラバーサルを防ぐ
        try:
            resolved = script_path.resolve()
            is_in_skill_dir = any(
                str(resolved).startswith(str(d.resolve()))
                for d in skill_dirs
            )
            if not is_in_skill_dir:
                return ActionResult(
                    success=False,
                    error="セキュリティエラー: スキルフォルダ外のスクリプトは実行できません"
                )
        except Exception as e:
            return ActionResult(
                success=False,
                error=f"パス解決エラー: {e}"
            )

        # スクリプトを動的にロードして実行
        try:
            spec = importlib.util.spec_from_file_location(
                f"skill_script_{skill_name}_{script_name}",
                script_path
            )
            if spec is None or spec.loader is None:
                return ActionResult(
                    success=False,
                    error=f"スクリプトをロードできません: {script_path}"
                )

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # execute 関数を探して実行
            if hasattr(module, "execute"):
                # execute(page, args) の形式で呼び出し
                result = await module.execute(self.page, args)
                if isinstance(result, dict):
                    return ActionResult(
                        success=result.get("success", True),
                        message=result.get("message", "スクリプト実行完了"),
                        data=result
                    )
                return ActionResult(
                    success=True,
                    message="スクリプト実行完了",
                    data={"result": result}
                )
            else:
                return ActionResult(
                    success=False,
                    error=f"スクリプトに execute 関数がありません: {script_path}"
                )

        except Exception as e:
            logger.error(f"Script execution failed: {e}", exc_info=True)
            return ActionResult(
                success=False,
                error=f"スクリプト実行エラー: {e}"
            )

    async def _read_manual(self, params: Dict[str, Any]) -> ActionResult:
        """
        スキルのアクション手順書を読む

        SKILL.md の目次を見て、必要なアクションの詳細を取得する場合に使用。

        Args:
            params:
                - action_name: 読みたいアクション名（例: 'login', 'search'）
        """
        from pathlib import Path

        action_name = params.get("action_name", "")

        if not action_name:
            return ActionResult(
                success=False,
                error="action_name は必須です"
            )

        if not self.skill_name:
            return ActionResult(
                success=False,
                error="skill_name が設定されていません。visual_browse で skill_name を指定してください。"
            )

        # スキルフォルダを特定
        skill_dirs = [
            Path(__file__).parent.parent.parent.parent / ".claude" / "skills",
        ]

        manual_path = None
        for skill_dir in skill_dirs:
            candidate = skill_dir / self.skill_name / "actions" / f"{action_name}.md"
            if candidate.exists():
                manual_path = candidate
                break

        if not manual_path:
            return ActionResult(
                success=False,
                error=f"手順書が見つかりません: {self.skill_name}/actions/{action_name}.md",
                data={"searched_dirs": [str(d) for d in skill_dirs]}
            )

        # 手順書を読み込み
        try:
            content = manual_path.read_text(encoding="utf-8")
            return ActionResult(
                success=True,
                message=f"{action_name} の手順書を読み込みました",
                data={
                    "action_name": action_name,
                    "manual_content": content,
                }
            )
        except Exception as e:
            logger.error(f"Failed to read manual: {e}", exc_info=True)
            return ActionResult(
                success=False,
                error=f"手順書の読み込みエラー: {e}"
            )


def get_action_type(action_name: str) -> ActionType:
    """アクション名からActionTypeを取得"""
    action_map = {
        "navigate": ActionType.NAVIGATE,
        "click": ActionType.CLICK,
        "type": ActionType.TYPE,
        "scroll": ActionType.SCROLL,
        "wait": ActionType.WAIT,
        "done": ActionType.DONE,
        "ask_user": ActionType.USER_ASSIST,
        "go_back": ActionType.NAVIGATE,
        "go_forward": ActionType.NAVIGATE,
        "refresh": ActionType.NAVIGATE,
        "hover": ActionType.CLICK,
        "run_script": ActionType.CLICK,  # スクリプト実行はCLICK扱い（副作用あり）
        "read_manual": ActionType.WAIT,  # 手順書読み込みは副作用なし
    }
    return action_map.get(action_name, ActionType.ERROR)
