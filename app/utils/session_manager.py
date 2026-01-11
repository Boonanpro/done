"""
ブラウザセッション管理

Cookieを保存・復元してログイン状態を維持
"""
import os
import json
from pathlib import Path
from typing import Optional
from playwright.async_api import BrowserContext, Browser


class SessionManager:
    """セッション管理クラス"""

    def __init__(self, service_name: str):
        """
        Args:
            service_name: サービス名（例: "smartex"）
        """
        self.service_name = service_name
        self.session_dir = Path("sessions")
        self.session_dir.mkdir(exist_ok=True)
        self.session_file = self.session_dir / f"{service_name}_session.json"

    def has_session(self) -> bool:
        """既存のセッションがあるかチェック"""
        return self.session_file.exists()

    async def create_context(
        self,
        browser: Browser,
        viewport: Optional[dict] = None,
        locale: str = "ja-JP",
    ) -> BrowserContext:
        """
        ブラウザコンテキストを作成（既存セッションがあれば復元）

        Args:
            browser: Playwrightブラウザインスタンス
            viewport: ビューポート設定
            locale: ロケール

        Returns:
            BrowserContext
        """
        viewport = viewport or {"width": 1280, "height": 720}

        if self.has_session():
            print(f"[SESSION] 既存セッションを復元: {self.session_file}")
            try:
                context = await browser.new_context(
                    viewport=viewport,
                    locale=locale,
                    storage_state=str(self.session_file),
                )
                return context
            except Exception as e:
                print(f"[SESSION] セッション復元失敗: {e}")
                print(f"[SESSION] 新規セッションを作成します")

        # 新規セッション作成
        print(f"[SESSION] 新規セッションを作成")
        context = await browser.new_context(
            viewport=viewport,
            locale=locale,
        )
        return context

    async def save_session(self, context: BrowserContext):
        """
        セッションを保存（Cookie・ストレージ状態）

        Args:
            context: Playwrightブラウザコンテキスト
        """
        try:
            await context.storage_state(path=str(self.session_file))
            print(f"[SESSION] セッションを保存: {self.session_file}")
        except Exception as e:
            print(f"[SESSION] セッション保存失敗: {e}")

    def delete_session(self):
        """セッションを削除"""
        if self.session_file.exists():
            self.session_file.unlink()
            print(f"[SESSION] セッションを削除: {self.session_file}")

    def get_session_info(self) -> Optional[dict]:
        """セッション情報を取得"""
        if not self.has_session():
            return None

        try:
            with open(self.session_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            cookies = data.get('cookies', [])
            origins = data.get('origins', [])

            return {
                "file": str(self.session_file),
                "cookies": len(cookies),
                "origins": len(origins),
            }
        except Exception:
            return None
