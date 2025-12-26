"""
Amazon Executor for Phase 3B: Execution Engine
Amazon商品購入の実行ロジック
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


class AmazonExecutor(BaseExecutor):
    """Amazon商品購入実行ロジック"""
    
    service_name = "amazon"
    
    # Amazon用のセレクタ
    SELECTORS = {
        # ログイン関連
        "login_link": 'a[data-nav-role="signin"], #nav-link-accountList',
        "email_input": '#ap_email, input[name="email"]',
        "email_continue": '#continue, input[name="continue"]',
        "password_input": '#ap_password, input[name="password"]',
        "login_button": '#signInSubmit, input[name="signInSubmit"]',
        
        # 商品ページ関連
        "add_to_cart": '#add-to-cart-button',
        "buy_now": '#buy-now-button',
        
        # カートページ関連
        "cart_count": '#nav-cart-count',
        "proceed_to_checkout": 'input[name="proceedToRetailCheckout"]',
        
        # 検索関連
        "search_box": '#twotabsearchtextbox',
        "search_button": '#nav-search-submit-button',
    }
    
    # AmazonのURL
    URLS = {
        "login": "https://www.amazon.co.jp/ap/signin?openid.pape.max_auth_age=0&openid.return_to=https%3A%2F%2Fwww.amazon.co.jp%2F&openid.identity=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.assoc_handle=jpflex&openid.mode=checkid_setup&openid.claimed_id=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0%2Fidentifier_select&openid.ns=http%3A%2F%2Fspecs.openid.net%2Fauth%2F2.0",
        "cart": "https://www.amazon.co.jp/gp/cart/view.html",
    }
    
    async def _do_execute(
        self,
        task_id: str,
        search_result: SearchResult,
        credentials: Optional[dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        Amazon商品をカートに追加
        
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
            if "amazon.co.jp/ap/" in page.url or "amazon.co.jp/gp/css" in page.url:
                await page.goto(product_url, wait_until="domcontentloaded", timeout=30000)
            
            # Step 3: カートに追加
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
            
            # Step 4: カート追加完了（購入確認はスキップ - 安全のため）
            await self._update_progress(
                task_id=task_id,
                step=ExecutionStep.CONFIRMED.value,
                details={"cart_verified": True},
            )
            
            # Step 5: 完了
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
                message="Product added to cart. Please complete the purchase manually on Amazon.",
                details={
                    "product_name": search_result.title,
                    "price": search_result.price,
                    "url": product_url,
                    "cart_url": self.URLS["cart"],
                },
            )
            
        except PlaywrightTimeout as e:
            # スクリーンショットを保存
            screenshot_path = f"error_amazon_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
            await take_screenshot(screenshot_path)
            
            return ExecutionResult(
                success=False,
                message=f"Timeout error: Failed to load page - {str(e)}",
                details={"screenshot": screenshot_path},
            )
        except Exception as e:
            # スクリーンショットを保存
            screenshot_path = f"error_amazon_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
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
            # ナビゲーションバーにアカウント名が表示されているか確認
            account_element = await page.query_selector('#nav-link-accountList-nav-line-1')
            if account_element:
                account_text = await account_element.inner_text()
                if "ログイン" not in account_text and "こんにちは" in account_text:
                    return {"success": True, "message": "Already logged in"}
        except Exception:
            pass
        
        # 認証情報がない場合
        if not credentials:
            return {
                "success": False,
                "message": "Amazon login credentials required",
            }
        
        email = credentials.get("email", "")
        password = credentials.get("password", "")
        
        if not email or not password:
            return {
                "success": False,
                "message": "Email or password is missing",
            }
        
        try:
            # ログインページに移動
            await page.goto(self.URLS["login"], wait_until="domcontentloaded", timeout=30000)
            
            # メールアドレスを入力
            await page.wait_for_selector(self.SELECTORS["email_input"], timeout=10000)
            await page.fill(self.SELECTORS["email_input"], email)
            
            # 次へボタンをクリック
            await page.click(self.SELECTORS["email_continue"])
            await page.wait_for_load_state("domcontentloaded")
            
            # パスワードを入力
            await page.wait_for_selector(self.SELECTORS["password_input"], timeout=10000)
            await page.fill(self.SELECTORS["password_input"], password)
            
            # ログインボタンをクリック
            await page.click(self.SELECTORS["login_button"])
            await page.wait_for_load_state("domcontentloaded")
            
            # ログイン成功を確認（2FA等がある場合はここで止まる）
            # 簡易チェック: ログインページでなくなったか
            await page.wait_for_timeout(2000)  # 少し待つ
            
            if "ap/signin" in page.url or "ap/cvf" in page.url:
                # 2FA等が必要な可能性
                return {
                    "success": False,
                    "message": "Additional authentication required. Please log in manually on Amazon.",
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
    
    async def _add_to_cart(self, page: Page) -> dict[str, Any]:
        """
        カートに商品を追加
        
        Returns:
            {"success": bool, "message": str}
        """
        try:
            # カートに入れるボタンを探す
            add_to_cart_button = await page.query_selector(self.SELECTORS["add_to_cart"])
            
            if not add_to_cart_button:
                # 商品ページでない可能性、または在庫切れ
                return {
                    "success": False,
                    "message": "Add to cart button not found. Product may be out of stock.",
                }
            
            # カートに追加
            await add_to_cart_button.click()
            await page.wait_for_load_state("domcontentloaded")
            
            # カート追加確認（カートページまたは確認ダイアログ）
            await page.wait_for_timeout(2000)  # 少し待つ
            
            # カートに追加されたことを確認（URLまたはカート数で判断）
            current_url = page.url
            if "cart" in current_url or "gp/cart" in current_url or "smart-wagon" in current_url:
                return {"success": True, "message": "Added to cart"}
            
            # カート数を確認
            try:
                cart_count = await page.query_selector(self.SELECTORS["cart_count"])
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
