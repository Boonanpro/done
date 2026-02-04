"""
Browser Recorder

操作ログを記録し、YAMLファイルとして保存。
スクリーンショットも保存。
"""

import os
import uuid
import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

import yaml

from app.executors.visual.history import (
    BrowserSession,
    BrowserStep,
    BrowserEvent,
    ActionType,
    ExtractedPatterns,
)

logger = logging.getLogger(__name__)

# ログ保存先ディレクトリ
LOGS_DIR = Path(__file__).parent.parent.parent / "logs" / "browser"


class BrowserRecorder:
    """
    ブラウザ操作記録器

    操作をステップごとに記録し、YAMLファイルとして保存。
    スクリーンショットも自動保存。

    Usage:
        recorder = BrowserRecorder(user_id="user123")
        recorder.start_session("アマゾンで商品を購入")

        # 操作を記録
        recorder.add_step(
            action=ActionType.NAVIGATE,
            params={"url": "https://amazon.co.jp"},
            result={"success": True},
            screenshot_base64="...",
        )

        # セッション終了時に保存
        await recorder.save()
    """

    def __init__(
        self,
        user_id: Optional[str] = None,
        logs_dir: Optional[Path] = None,
    ):
        self.user_id = user_id
        self.logs_dir = logs_dir or LOGS_DIR
        self.session: Optional[BrowserSession] = None
        self._step_index = 0
        self._event_index = 0

        # ログディレクトリを確保
        self.logs_dir.mkdir(parents=True, exist_ok=True)

    def start_session(
        self,
        task: str,
        site: Optional[str] = None,
        model: Optional[str] = None,
    ) -> BrowserSession:
        """
        新しいセッションを開始

        Args:
            task: タスクの説明
            site: 対象サイト（例: "amazon.co.jp"）
            model: 使用するモデル

        Returns:
            BrowserSession: 新しいセッション
        """
        session_id = str(uuid.uuid4())[:8]

        self.session = BrowserSession(
            id=session_id,
            task=task,
            site=site,
            user_id=self.user_id,
            model_used=model,
        )
        self._step_index = 0
        self._event_index = 0

        logger.info(f"Started browser session: {session_id} - {task}")
        return self.session

    def add_step(
        self,
        action: ActionType,
        params: Dict[str, Any],
        result: Dict[str, Any],
        screenshot_base64: Optional[str] = None,
        llm_reasoning: Optional[str] = None,
        duration_ms: Optional[int] = None,
        page_url: Optional[str] = None,
        decision_type: Optional[str] = None,
        decision_reason: Optional[str] = None,
    ) -> BrowserStep:
        """
        操作ステップを追加

        Args:
            action: アクションタイプ
            params: アクションパラメータ
            result: 実行結果
            screenshot_base64: スクリーンショット（base64）
            llm_reasoning: LLMの判断理由
            duration_ms: 実行時間（ミリ秒）

        Returns:
            BrowserStep: 追加されたステップ
        """
        if not self.session:
            raise RuntimeError("Session not started. Call start_session() first.")

        self._step_index += 1

        step = BrowserStep(
            index=self._step_index,
            action=action,
            params=params,
            result=result,
            screenshot_base64=screenshot_base64,
            llm_reasoning=llm_reasoning,
            duration_ms=duration_ms,
            page_url=page_url,
            decision_type=decision_type,
            decision_reason=decision_reason,
        )

        self.session.add_step(step)

        # ログ出力
        action_name = action.value if isinstance(action, ActionType) else action
        success = result.get("success", True)
        status = "OK" if success else "FAIL"
        logger.info(f"Step {self._step_index}: {action_name} - {status}")

        return step

    def add_event(
        self,
        event_type: str,
        message: str,
        step_index: Optional[int] = None,
        page_url: Optional[str] = None,
    ) -> None:
        """進行イベントを追加"""
        if not self.session:
            return

        self._event_index += 1
        event = BrowserEvent(
            index=self._event_index,
            event_type=event_type,
            message=message,
            step_index=step_index,
            page_url=page_url,
        )
        self.session.add_event(event)

    def end_session(
        self,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        セッションを終了

        Args:
            success: 成功したか
            error_message: エラーメッセージ（失敗時）
        """
        if not self.session:
            return

        self.session.end(success=success, error_message=error_message)

        status = "SUCCESS" if success else "FAILED"
        logger.info(f"Session {self.session.id} ended: {status}")

    def update_extracted_patterns(self, patterns: ExtractedPatterns) -> None:
        """
        抽出されたパターンを更新

        Args:
            patterns: 抽出されたパターン
        """
        if self.session:
            self.session.extracted_patterns = patterns

    async def save(self) -> Optional[str]:
        """
        セッションをYAMLファイルとして保存

        Returns:
            保存先ファイルパス、または None
        """
        if not self.session:
            logger.warning("No session to save")
            return None

        # ファイル名を生成
        timestamp = self.session.started_at.strftime("%Y%m%d_%H%M%S")
        safe_task = self._sanitize_filename(self.session.task[:30])
        filename = f"{timestamp}_{safe_task}.yaml"

        # セッション用ディレクトリを作成
        session_dir = self.logs_dir / self.session.id
        session_dir.mkdir(parents=True, exist_ok=True)

        # スクリーンショットを保存
        await self._save_screenshots(session_dir)

        # YAMLファイルを保存
        filepath = session_dir / filename
        session_dict = self.session.to_dict()

        with open(filepath, "w", encoding="utf-8") as f:
            yaml.dump(
                session_dict,
                f,
                allow_unicode=True,
                default_flow_style=False,
                sort_keys=False,
            )

        logger.info(f"Session saved: {filepath}")
        return str(filepath)

    async def _save_screenshots(self, session_dir: Path) -> None:
        """
        スクリーンショットを保存

        Args:
            session_dir: セッションディレクトリ
        """
        screenshots_dir = session_dir / "screenshots"
        screenshots_dir.mkdir(exist_ok=True)

        for step in self.session.steps:
            if step.screenshot_base64:
                filename = f"step_{step.index:03d}.png"
                filepath = screenshots_dir / filename

                # base64をデコードして保存
                try:
                    image_data = base64.b64decode(step.screenshot_base64)
                    with open(filepath, "wb") as f:
                        f.write(image_data)

                    # パスを相対パスに更新
                    step.screenshot_path = f"screenshots/{filename}"
                    step.screenshot_base64 = None  # メモリ解放

                except Exception as e:
                    logger.error(f"Failed to save screenshot for step {step.index}: {e}")

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """ファイル名に使えない文字を除去"""
        # 改行をスペースに変換
        name = name.replace("\n", " ").replace("\r", " ")
        # 連続スペースを1つに
        while "  " in name:
            name = name.replace("  ", " ")
        # ファイルシステムで使えない文字を除去
        invalid_chars = '<>:"/\\|?*'
        for char in invalid_chars:
            name = name.replace(char, "_")
        return name.strip()

    @staticmethod
    def load(filepath: str) -> Optional[BrowserSession]:
        """
        YAMLファイルからセッションを復元

        Args:
            filepath: YAMLファイルパス

        Returns:
            BrowserSession、または None
        """
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)

            return BrowserSession.from_dict(data)

        except Exception as e:
            logger.error(f"Failed to load session from {filepath}: {e}")
            return None

    @classmethod
    def list_sessions(cls, logs_dir: Optional[Path] = None) -> list:
        """
        保存されているセッション一覧を取得

        Args:
            logs_dir: ログディレクトリ

        Returns:
            セッション情報のリスト
        """
        logs_dir = logs_dir or LOGS_DIR
        sessions = []

        if not logs_dir.exists():
            return sessions

        for session_dir in logs_dir.iterdir():
            if not session_dir.is_dir():
                continue

            # YAMLファイルを探す
            for yaml_file in session_dir.glob("*.yaml"):
                try:
                    with open(yaml_file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f)

                    session_info = data.get("session", {})
                    sessions.append({
                        "id": session_info.get("id"),
                        "task": session_info.get("task"),
                        "site": session_info.get("site"),
                        "started_at": session_info.get("started_at"),
                        "success": session_info.get("success"),
                        "filepath": str(yaml_file),
                    })

                except Exception as e:
                    logger.warning(f"Failed to read {yaml_file}: {e}")

        # 日時でソート（新しい順）
        sessions.sort(key=lambda x: x.get("started_at", ""), reverse=True)
        return sessions
