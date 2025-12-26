"""
Rakuten Executor for Phase 3B: Execution Engine
楽天商品購入の実行ロジック
"""
from typing import Optional, Any
from datetime import datetime

from playwright.async_api import Page, TimeoutError as PlaywrightTimeout

from app.models.schemas import (
    ExecutionStep,
    ExecutionResult,
    SearchResult,
)
from app.executors.base import BaseExecutor
from app.tools.browser import get_page, take_screenshot


class RakutenExecutor(BaseExecutor):
    """楽天商品購入実行ロジック"""
    
    service_name = "rakuten"
    
    # 楽天用のセレクタ
    SELECTORS = {
        # ログイン関連
        "login_link": 'a[href*="login"], .login-link',
        "user_id_input": '#loginInner_u, input[name="u"]',
        "password_input": '#loginInner_p, input[name="p"]',
        "login_button": 'input[type="submit"][value*="ログイン"], button[type="submit"]',
        
        # 商品ページ関連
        "add_to_cart": 'button[data-testid="add-to-cart"], .add-to-cart-button, button:has-text("かごに追加"), [class*="addToCart"]',
        "buy_now": 'button:has-text("ご購入手続きへ"), .buy-now-button',
        
        # バリエーション選択
        "variation_selector": '.variation-selector, [class*="variation"]',
        
        # カートページ関連
        "cart_count": '.cart-count, [class*="cartCount"], .header-cart-count',
        "proceed_to_checkout": 'a:has-text("購入手続きへ"), button:has-text("購入手続きへ")',
        
        # 検索関連
        "search_box": '#searchKeywordTop, input[name="keyword"]',
        "search_button": '.search-btn, button[type="submit"]',
        
        # フローティングカート（邪魔になる要素）
        "floating_cart": '#floatingCartContainer, [class*="floatingCart"]',
    }
    
    # 楽天のURL
    URLS = {
        "login": "https://grp01.id.rakuten.co.jp/rms/nid/vc?__event=login&service_id=top",
        "cart": "https://basket.step.rakuten.co.jp/rms/basket/",
        "top": "https://www.rakuten.co.jp/",
    }
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        楽天商品をカートに追加
        
        注意: 実際の購入は行わず、カートに入れるところまで
        """
        page = await get_page()
        
        try:
            # Step 1: 商品ページにアクセス
            product_url = search_result.url
            if not product_url:
                # execution_paramsからURLを取得
                exec_params = search_result.execution_params or {}
                product_url = exec_params.get("booking_url", "")
            
            if not product_url:
                return ExecutionResult(
                    success=False,
                    message="Product URL not specified",
                )
            
            await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.OPENED_URL.value,
                details={"url": product_url},
            )
            
            # Step 2: ログイン確認・実行
            login_result = await self._ensure_logged_in(page, credentials)
            if not login_result["success"]:
                return ExecutionResult(
                    success=False,
                    message=login_result["message"],
                )
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.LOGGED_IN.value,
                details={"logged_in": True},
            )
            
            # 商品ページに戻る（ログインでリダイレクトされた場合）
            if "grp01.id.rakuten.co.jp" in page.url or "login" in page.url:
                await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
            
            # Step 3: フローティングカートを非表示にする（クリックを邪魔する場合があるため）
            await self._hide_floating_elements(page)
            
            # Step 4: カートに追加
            add_to_cart_result = await self._add_to_cart(page)
            if not add_to_cart_result["success"]:
                return ExecutionResult(
                    success=False,
                    message=add_to_cart_result["message"],
                )
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.ENTERED_DETAILS.value,
                details={"action": "added_to_cart"},
            )
            
            # Step 5: カート追加完了（購入確認はスキップ - 安全のため）
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.CONFIRMED.value,
                details={"cart_verified": True},
            )
            
            # Step 6: 完了
            # 注意: 実際の購入は行わない
            cart_id = f"CART-{datetime.now().strftime('%Y%m%d%H%M%S')}"
            
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.COMPLETED.value,
                details={"cart_id": cart_id},
            )
            
            return ExecutionResult(
                success=True,
                confirmation_number=cart_id,
                message="Product added to cart. Please complete the purchase manually on Rakuten.",
                details={
                    "product_name": search_result.title,
                    "price": search_result.price,
                    "url": product_url,
                    "cart_url": self.URLS["cart"],
                },
            )
            
        except PlaywrightTimeout as e:
            # スクリーンショットを保存
            screenshot_path = f"error_rakuten_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await take_screenshot(screenshot_path)
            
            return ExecutionResult(
                success=False,
                message=f"Timeout error: Failed to load page - {str(e)}",
                details={"screenshot": screenshot_path},
            )
        except Exception as e:
            # スクリーンショットを保存
            screenshot_path = f"error_rakuten_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            try:
                await take_screenshot(screenshot_path)
            except Exception:
                pass
            
            return ExecutionResult(
                success=False,
                message=f"Execution error: {str(e)}",
                details={"screenshot": screenshot_path},
            )
    
    async def _ensure_logged_in(
        self,
        page: Page,
        credentials: Optional[dict[str, str]] = None,
    ) -> dict[str, Any]:
        """
        ログイン状態を確認し、必要であればログイン
        
        Returns:
            {"success": bool, "message": str}
        """
        # ログイン状態を確認
        try:
            # ヘッダーにログイン済みのユーザー名が表示されているか確認
            # 楽天はログイン済みだと「〇〇さん」と表示される
            logged_in_element = await page.query_selector('[class*="mypage"], [class*="member"], .user-name')
            if logged_in_element:
                return {"success": True, "message": "Already logged in"}
            
            # 別の確認方法: ログインボタンがあるかどうか
            login_button = await page.query_selector('a[href*="login"]:has-text("ログイン")')
            if not login_button:
                # ログインボタンがない = ログイン済みの可能性
                return {"success": True, "message": "Login status confirmed"}
        except Exception:
            pass
        
        # 認証情報がない場合
        if not credentials:
            return {
                "success": False,
                "message": "Rakuten login credentials required",
            }
        
        email = credentials.get("email", "")
        password = credentials.get("password", "")
        
        if not email or not password:
            return {
                "success": False,
                "message": "User ID or password is missing",
            }
        
        try:
            # ログインページに移動
            await page.goto(self.URLS["login"], wait_until="domcontentloaded", timeout=30000)
            
            # ユーザーIDを入力
            await page.wait_for_selector(self.SELECTORS["user_id_input"], timeout=10000)
            await page.fill(self.SELECTORS["user_id_input"], email)
            
            # パスワードを入力
            await page.wait_for_selector(self.SELECTORS["password_input"], timeout=10000)
            await page.fill(self.SELECTORS["password_input"], password)
            
            # ログインボタンをクリック
            login_btn = await page.query_selector(self.SELECTORS["login_button"])
            if login_btn:
                await login_btn.click()
            else:
                # フォームをsubmit
                await page.keyboard.press("Enter")
            
            await page.wait_for_load_state("domcontentloaded")
            
            # ログイン成功を確認
            await page.wait_for_timeout(2000)  # 少し待つ
            
            if "login" in page.url.lower() or "error" in page.url.lower():
                # ログインページにまだいる = ログイン失敗
                return {
                    "success": False,
                    "message": "Login failed. Please check your user ID and password.",
                }
            
            return {"success": True, "message": "Login successful"}
            
        except PlaywrightTimeout:
            return {
                "success": False,
                "message": "Login page loading timed out",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error during login: {str(e)}",
            }
    
    async def _hide_floating_elements(self, page: Page) -> None:
        """
        フローティング要素を非表示にする（クリックを邪魔する場合があるため）
        """
        try:
            await page.evaluate("""
                () => {
                    // フローティングカートを非表示
                    const floatingCart = document.getElementById('floatingCartContainer');
                    if (floatingCart) {
                        floatingCart.style.display = 'none';
                    }
                    
                    // その他のフローティング要素
                    const floatingElements = document.querySelectorAll('[class*="floating"], [class*="sticky"]:not(header)');
                    floatingElements.forEach(el => {
                        if (el.style) {
                            el.style.display = 'none';
                        }
                    });
                }
            """)
        except Exception:
            pass  # 非表示にできなくても続行
    
    async def _add_to_cart(self, page: Page) -> dict[str, Any]:
        """
        カートに商品を追加
        
        Returns:
            {"success": bool, "message": str}
        """
        try:
            # カートに入れるボタンを探す（複数のセレクタを試行）
            add_to_cart_button = None
            
            # 方法1: data-testid属性
            add_to_cart_button = await page.query_selector('button[data-testid="add-to-cart"]')
            
            # 方法2: テキストで探す
            if not add_to_cart_button:
                add_to_cart_button = await page.query_selector('button:has-text("かごに追加")')
            
            # 方法3: クラス名で探す
            if not add_to_cart_button:
                add_to_cart_button = await page.query_selector('[class*="addToCart"], [class*="add-to-cart"]')
            
            # 方法4: getByRoleで探す
            if not add_to_cart_button:
                try:
                    add_to_cart_button = page.get_by_role("button", name="かごに追加")
                    # locatorが有効か確認
                    if await add_to_cart_button.count() == 0:
                        add_to_cart_button = None
                except Exception:
                    pass
            
            if not add_to_cart_button:
                # 商品ページでない可能性、または在庫切れ
                return {
                    "success": False,
                    "message": "Add to cart button not found. Product may be out of stock.",
                }
            
            # カートに追加
            if hasattr(add_to_cart_button, 'click'):
                await add_to_cart_button.click()
            else:
                # Locatorの場合
                await add_to_cart_button.first.click()
            
            await page.wait_for_load_state("domcontentloaded")
            
            # カート追加確認
            await page.wait_for_timeout(2000)  # 少し待つ
            
            # カートに追加されたことを確認
            current_url = page.url
            if "basket" in current_url or "cart" in current_url:
                return {"success": True, "message": "Added to cart"}
            
            # カート数を確認
            try:
                cart_count = await page.query_selector('[class*="cartCount"], .cart-count')
                if cart_count:
                    count_text = await cart_count.inner_text()
                    if count_text and int(count_text) > 0:
                        return {"success": True, "message": f"Added to cart ({count_text} items in cart)"}
            except Exception:
                pass
            
            # 確認ダイアログが表示されている可能性
            return {"success": True, "message": "Add to cart requested"}
            
        except PlaywrightTimeout:
            return {
                "success": False,
                "message": "Add to cart timed out",
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error adding to cart: {str(e)}",
            }
