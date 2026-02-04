"""
Vision Helper for Dan

ダンがページ状態を理解するための視覚情報を提供。
失敗時にページ状態をキャプチャし、LLMが理解できる形式で返す。
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class PageVision:
    """ページの視覚情報"""
    title: str
    url: str
    main_text: str
    interactive_elements: List[Dict[str, Any]]
    element_count: int
    screenshot_base64: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "main_text": self.main_text[:500],  # 長すぎる場合は切り詰め
            "interactive_elements": self.interactive_elements[:30],  # 最大30要素
            "element_count": self.element_count,
            "has_screenshot": self.screenshot_base64 is not None,
        }

    def describe(self) -> str:
        """ダン向けのテキスト説明を生成"""
        lines = [
            f"【現在のページ状態】",
            f"タイトル: {self.title}",
            f"URL: {self.url}",
            f"",
            f"【インタラクティブ要素】({self.element_count}個検出)",
        ]

        # 重要な要素をグループ化
        buttons = [e for e in self.interactive_elements if e.get('role') == 'button' or e.get('tag') == 'button']
        inputs = [e for e in self.interactive_elements if e.get('tag') in ('input', 'textarea', 'select')]
        links = [e for e in self.interactive_elements if e.get('tag') == 'a' or e.get('role') == 'link']

        if buttons:
            lines.append(f"\nボタン ({len(buttons)}個):")
            for btn in buttons[:5]:
                text = btn.get('text', '')[:30] or '(テキストなし)'
                lines.append(f"  {btn['ref']}: {text}")

        if inputs:
            lines.append(f"\n入力欄 ({len(inputs)}個):")
            for inp in inputs[:5]:
                id_or_name = inp.get('id') or inp.get('name') or inp.get('type', 'unknown')
                lines.append(f"  {inp['ref']}: {id_or_name}")

        if links and len(lines) < 20:
            lines.append(f"\nリンク ({len(links)}個、先頭5件):")
            for link in links[:5]:
                text = link.get('text', '')[:30] or '(テキストなし)'
                lines.append(f"  {link['ref']}: {text}")

        return "\n".join(lines)


async def capture_page_vision(page, include_screenshot: bool = True) -> PageVision:
    """
    現在のページの視覚情報をキャプチャ

    Args:
        page: ExecutorPageProxy
        include_screenshot: スクリーンショットを含めるか

    Returns:
        PageVision: ページの視覚情報
    """
    try:
        # ページ状態を取得
        state = await page.get_page_state()

        # スクリーンショット（オプション）
        screenshot_base64 = None
        if include_screenshot:
            try:
                result = await page.screenshot_base64(full_page=False)
                screenshot_base64 = result.get("base64")
            except Exception as e:
                logger.warning(f"スクリーンショット取得エラー: {e}")

        return PageVision(
            title=state["summary"]["title"],
            url=state["summary"]["url"],
            main_text=state["summary"]["main_text"],
            interactive_elements=state["interactive_elements"],
            element_count=state["element_count"],
            screenshot_base64=screenshot_base64,
        )

    except Exception as e:
        logger.error(f"ページ視覚情報取得エラー: {e}")
        # 最低限の情報を返す
        return PageVision(
            title="取得エラー",
            url="",
            main_text=str(e),
            interactive_elements=[],
            element_count=0,
            screenshot_base64=None,
        )


def format_vision_for_llm(vision: PageVision, error_message: str = "") -> Dict[str, Any]:
    """
    LLM（ダン）向けに視覚情報をフォーマット

    Args:
        vision: ページ視覚情報
        error_message: エラーメッセージ（あれば）

    Returns:
        dict: LLMが理解できる形式の情報
    """
    result = {
        "error": error_message if error_message else None,
        "page_state": vision.to_dict(),
        "description": vision.describe(),
    }

    if vision.screenshot_base64:
        result["screenshot"] = {
            "base64": vision.screenshot_base64,
            "media_type": "image/png",
        }

    return result
