"""
Browser Session History

操作履歴のデータ構造。
browser-useのAgentHistoryListを参考に設計。
将来のスキル自動生成に必要な情報を保持。
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any, List
from enum import Enum


class ActionType(str, Enum):
    """アクションタイプ"""
    NAVIGATE = "navigate"
    CLICK = "click"
    TYPE = "type"
    SCROLL = "scroll"
    SCREENSHOT = "screenshot"
    WAIT = "wait"
    SELECT = "select"
    USER_ASSIST = "user_assist"  # ユーザー介入
    DONE = "done"  # タスク完了
    ERROR = "error"  # エラー


@dataclass
class BrowserStep:
    """
    1つの操作ステップ

    Attributes:
        index: ステップ番号（1始まり）
        action: アクションタイプ
        params: アクションパラメータ
        result: 実行結果
        screenshot_path: スクリーンショットの相対パス
        screenshot_base64: スクリーンショットのbase64（一時保持用）
        timestamp: 実行時刻
        duration_ms: 実行時間（ミリ秒）
        llm_reasoning: LLMの判断理由（デバッグ用）
    """
    index: int
    action: ActionType
    params: Dict[str, Any] = field(default_factory=dict)
    result: Dict[str, Any] = field(default_factory=dict)
    screenshot_path: Optional[str] = None
    screenshot_base64: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    duration_ms: Optional[int] = None
    llm_reasoning: Optional[str] = None
    page_url: Optional[str] = None
    decision_type: Optional[str] = None  # "selector" / "visual" / "direct" / "unknown"
    decision_reason: Optional[str] = None  # 判定理由の簡易メモ

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換（YAML出力用）"""
        data = {
            "index": self.index,
            "action": self.action.value if isinstance(self.action, ActionType) else self.action,
            "params": self.params,
            "result": self.result,
            "timestamp": self.timestamp.isoformat(),
        }

        if self.screenshot_path:
            data["screenshot"] = self.screenshot_path
        if self.duration_ms is not None:
            data["duration_ms"] = self.duration_ms
        if self.llm_reasoning:
            data["llm_reasoning"] = self.llm_reasoning
        if self.page_url:
            data["page_url"] = self.page_url
        if self.decision_type:
            data["decision_type"] = self.decision_type
        if self.decision_reason:
            data["decision_reason"] = self.decision_reason

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrowserStep":
        """辞書から復元"""
        action = data.get("action", "")
        try:
            action = ActionType(action)
        except ValueError:
            pass  # 文字列のまま

        return cls(
            index=data.get("index", 0),
            action=action,
            params=data.get("params", {}),
            result=data.get("result", {}),
            screenshot_path=data.get("screenshot"),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            duration_ms=data.get("duration_ms"),
            llm_reasoning=data.get("llm_reasoning"),
            page_url=data.get("page_url"),
            decision_type=data.get("decision_type"),
            decision_reason=data.get("decision_reason"),
        )


@dataclass
class BrowserEvent:
    """
    進行ログ（思考・計画・ステップ要約など）
    """
    index: int
    event_type: str  # "plan" / "thinking" / "step" / "note"
    message: str
    timestamp: datetime = field(default_factory=datetime.now)
    step_index: Optional[int] = None
    page_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "index": self.index,
            "type": self.event_type,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }
        if self.step_index is not None:
            data["step_index"] = self.step_index
        if self.page_url:
            data["page_url"] = self.page_url
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrowserEvent":
        return cls(
            index=data.get("index", 0),
            event_type=data.get("type", ""),
            message=data.get("message", ""),
            timestamp=datetime.fromisoformat(data["timestamp"]) if "timestamp" in data else datetime.now(),
            step_index=data.get("step_index"),
            page_url=data.get("page_url"),
        )


@dataclass
class ExtractedPatterns:
    """
    将来のスキル生成用に抽出されたパターン

    操作ログから自動抽出されるセレクタや操作パターン。
    Phase 2でスキル自動生成に使用。
    """
    search_box_selector: Optional[str] = None
    search_button_selector: Optional[str] = None
    product_selectors: List[str] = field(default_factory=list)
    add_to_cart_selector: Optional[str] = None
    checkout_selector: Optional[str] = None
    login_selectors: Dict[str, str] = field(default_factory=dict)

    # 汎用パターン
    form_selectors: Dict[str, str] = field(default_factory=dict)
    button_selectors: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換"""
        data = {}
        if self.search_box_selector:
            data["search_box_selector"] = self.search_box_selector
        if self.search_button_selector:
            data["search_button_selector"] = self.search_button_selector
        if self.product_selectors:
            data["product_selectors"] = self.product_selectors
        if self.add_to_cart_selector:
            data["add_to_cart_selector"] = self.add_to_cart_selector
        if self.checkout_selector:
            data["checkout_selector"] = self.checkout_selector
        if self.login_selectors:
            data["login_selectors"] = self.login_selectors
        if self.form_selectors:
            data["form_selectors"] = self.form_selectors
        if self.button_selectors:
            data["button_selectors"] = self.button_selectors
        return data


@dataclass
class BrowserSession:
    """
    ブラウザ操作セッション全体

    1つのタスク実行の全履歴を保持。
    """
    id: str
    task: str
    site: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    ended_at: Optional[datetime] = None
    success: bool = False
    error_message: Optional[str] = None

    steps: List[BrowserStep] = field(default_factory=list)
    events: List[BrowserEvent] = field(default_factory=list)
    extracted_patterns: ExtractedPatterns = field(default_factory=ExtractedPatterns)

    # メタデータ
    user_id: Optional[str] = None
    model_used: Optional[str] = None
    total_tokens: int = 0

    def add_step(self, step: BrowserStep) -> None:
        """ステップを追加"""
        self.steps.append(step)

    def add_event(self, event: BrowserEvent) -> None:
        """進行イベントを追加"""
        self.events.append(event)

    def end(self, success: bool, error_message: Optional[str] = None) -> None:
        """セッションを終了"""
        self.ended_at = datetime.now()
        self.success = success
        self.error_message = error_message

    def to_dict(self) -> Dict[str, Any]:
        """辞書形式に変換（YAML出力用）"""
        data = {
            "session": {
                "id": self.id,
                "task": self.task,
                "started_at": self.started_at.isoformat(),
                "success": self.success,
            },
            "steps": [step.to_dict() for step in self.steps],
        }

        if self.events:
            data["events"] = [event.to_dict() for event in self.events]

        if self.site:
            data["session"]["site"] = self.site
        if self.ended_at:
            data["session"]["ended_at"] = self.ended_at.isoformat()
        if self.error_message:
            data["session"]["error_message"] = self.error_message
        if self.user_id:
            data["session"]["user_id"] = self.user_id
        if self.model_used:
            data["session"]["model_used"] = self.model_used
        if self.total_tokens > 0:
            data["session"]["total_tokens"] = self.total_tokens

        # 抽出されたパターン
        patterns = self.extracted_patterns.to_dict()
        if patterns:
            data["extracted_patterns"] = patterns

        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BrowserSession":
        """辞書から復元"""
        session_data = data.get("session", {})

        session = cls(
            id=session_data.get("id", ""),
            task=session_data.get("task", ""),
            site=session_data.get("site"),
            started_at=datetime.fromisoformat(session_data["started_at"]) if "started_at" in session_data else datetime.now(),
            ended_at=datetime.fromisoformat(session_data["ended_at"]) if session_data.get("ended_at") else None,
            success=session_data.get("success", False),
            error_message=session_data.get("error_message"),
            user_id=session_data.get("user_id"),
            model_used=session_data.get("model_used"),
            total_tokens=session_data.get("total_tokens", 0),
        )

        # ステップを復元
        for step_data in data.get("steps", []):
            session.steps.append(BrowserStep.from_dict(step_data))

        # イベントを復元
        for event_data in data.get("events", []):
            session.events.append(BrowserEvent.from_dict(event_data))

        return session

    # ========================================
    # ヘルパーメソッド（browser-use風）
    # ========================================

    def urls(self) -> List[str]:
        """訪問したURL一覧"""
        urls = []
        for step in self.steps:
            if step.action == ActionType.NAVIGATE:
                url = step.params.get("url")
                if url:
                    urls.append(url)
        return urls

    def screenshot_paths(self) -> List[str]:
        """スクリーンショットのパス一覧"""
        return [s.screenshot_path for s in self.steps if s.screenshot_path]

    def action_names(self) -> List[str]:
        """実行したアクション名一覧"""
        return [
            s.action.value if isinstance(s.action, ActionType) else s.action
            for s in self.steps
        ]

    def errors(self) -> List[Dict[str, Any]]:
        """エラー一覧"""
        errors = []
        for step in self.steps:
            if not step.result.get("success", True):
                errors.append({
                    "index": step.index,
                    "action": step.action,
                    "error": step.result.get("error", "Unknown error"),
                })
        return errors

    def duration_seconds(self) -> Optional[float]:
        """セッションの実行時間（秒）"""
        if self.ended_at and self.started_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None
