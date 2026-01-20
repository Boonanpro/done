"""
Session - 会話セッション管理

ChatGPTと同様に、Messages配列で会話の文脈を維持する。
LLMは自分が何を言ったかを覚えている。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from datetime import datetime, timezone
import json


def _parse_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """ISO形式のdatetime文字列をパース（Supabaseの形式に対応）

    Supabaseはマイクロ秒が5桁の場合がある（例: 2026-01-15T12:50:21.69659+00:00）
    Python標準のfromisoformatは6桁を期待するため、調整が必要
    """
    if not dt_str:
        return None
    try:
        # まず標準的なパースを試みる
        dt_str = dt_str.replace("Z", "+00:00")
        return datetime.fromisoformat(dt_str)
    except ValueError:
        # マイクロ秒の桁数問題に対応
        try:
            # タイムゾーン部分を分離
            if '+' in dt_str:
                main_part, tz_part = dt_str.rsplit('+', 1)
                tz_part = '+' + tz_part
            elif dt_str.endswith('Z'):
                main_part = dt_str[:-1]
                tz_part = '+00:00'
            else:
                main_part = dt_str
                tz_part = ''

            # マイクロ秒部分を6桁に調整
            if '.' in main_part:
                date_time, microsec = main_part.rsplit('.', 1)
                # 6桁になるようパディングまたはトリミング
                microsec = microsec.ljust(6, '0')[:6]
                main_part = f"{date_time}.{microsec}"

            return datetime.fromisoformat(main_part + tz_part)
        except Exception:
            # それでも失敗したら現在時刻を返す
            return datetime.now(timezone.utc)


class State(str, Enum):
    """エージェントの状態"""
    INTAKE = "intake"      # 要望を理解
    PLAN = "plan"          # 計画を立てる
    RESEARCH = "research"  # 情報収集
    PROPOSE = "propose"    # 提案
    CONFIRM = "confirm"    # 承認確認
    EXECUTE = "execute"    # 実行
    VERIFY = "verify"      # 結果確認
    REPORT = "report"      # 報告
    CHAT = "chat"          # 雑談モード
    DEVELOP = "develop"    # 自己修正モード（Self-Healing）


@dataclass
class Session:
    """
    会話セッション

    Messages配列を中心に管理。
    状態遷移はLLMの出力から検出し、コードは追従するだけ。
    """

    session_id: str
    user_id: str

    # 会話履歴（これが全て）
    messages: List[Dict[str, str]] = field(default_factory=list)

    # 現在の状態
    current_state: State = State.INTAKE

    # 推論ステップ（ナレーション用）
    reasoning_steps: List[str] = field(default_factory=list)

    # コンテキスト（状態間で引き継ぐデータ）
    context: Dict[str, Any] = field(default_factory=dict)

    # タイムスタンプ
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def add_user_message(self, content: str) -> None:
        """ユーザーメッセージを追加"""
        self.messages.append({
            "role": "user",
            "content": content
        })
        self.updated_at = datetime.utcnow()

    def add_assistant_message(self, content: str) -> None:
        """アシスタントメッセージを追加"""
        self.messages.append({
            "role": "assistant",
            "content": content
        })
        self.updated_at = datetime.utcnow()

    def add_reasoning_step(self, step: str) -> None:
        """推論ステップを追加（ナレーション用）"""
        self.reasoning_steps.append(step)

    def clear_reasoning_steps(self) -> None:
        """推論ステップをクリア（次のターン用）"""
        self.reasoning_steps = []

    def get_messages_for_llm(self) -> List[Dict[str, str]]:
        """LLMに渡すメッセージ配列を取得"""
        return self.messages.copy()

    def set_context(self, key: str, value: Any) -> None:
        """コンテキストに値を設定"""
        self.context[key] = value
        self.updated_at = datetime.utcnow()

    def get_context(self, key: str, default: Any = None) -> Any:
        """コンテキストから値を取得"""
        return self.context.get(key, default)

    def transition_to(self, new_state: State) -> None:
        """状態を遷移"""
        self.current_state = new_state
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """辞書に変換（永続化用）"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "messages": self.messages,
            "current_state": self.current_state.value,
            "reasoning_steps": self.reasoning_steps,
            "context": self.context,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """辞書から復元"""
        session = cls(
            session_id=data["session_id"],
            user_id=data["user_id"],
        )
        session.messages = data.get("messages", [])
        session.current_state = State(data.get("current_state", "intake"))
        session.reasoning_steps = data.get("reasoning_steps", [])
        session.context = data.get("context", {})

        if data.get("created_at"):
            parsed = _parse_datetime(data["created_at"])
            if parsed:
                session.created_at = parsed
        if data.get("updated_at"):
            parsed = _parse_datetime(data["updated_at"])
            if parsed:
                session.updated_at = parsed

        return session


class SessionStore:
    """
    セッションストア（メモリ + 永続化）

    メモリにキャッシュしつつ、DBにも保存する。
    """

    def __init__(self):
        self._cache: Dict[str, Session] = {}

    def _make_key(self, session_id: str, user_id: str) -> str:
        """キャッシュキーを生成"""
        return f"{user_id}:{session_id}"

    async def get_or_create(self, session_id: str, user_id: str) -> Session:
        """セッションを取得または作成"""
        key = self._make_key(session_id, user_id)

        # キャッシュにあれば返す
        if key in self._cache:
            return self._cache[key]

        # DBから取得を試みる
        session = await self._load_from_db(session_id, user_id)

        if session is None:
            # 新規作成
            session = Session(session_id=session_id, user_id=user_id)

        # キャッシュに保存
        self._cache[key] = session
        return session

    async def save(self, session: Session) -> bool:
        """セッションを保存"""
        key = self._make_key(session.session_id, session.user_id)

        # キャッシュを更新
        self._cache[key] = session

        # DBにも保存
        return await self._save_to_db(session)

    async def _load_from_db(self, session_id: str, user_id: str) -> Optional[Session]:
        """DBからセッションを読み込み"""
        try:
            from app.services.supabase_client import get_supabase_client
            supabase = get_supabase_client().client

            result = supabase.table("agent_sessions_v2").select("*").eq(
                "session_id", session_id
            ).eq("user_id", user_id).limit(1).execute()

            if result.data and len(result.data) > 0:
                data = result.data[0]
                return Session.from_dict({
                    "session_id": data["session_id"],
                    "user_id": data["user_id"],
                    "messages": data.get("messages", []),
                    "current_state": data.get("current_state", "intake"),
                    "reasoning_steps": data.get("reasoning_steps", []),
                    "context": data.get("context", {}),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                })
            return None
        except Exception as e:
            # テーブルがない場合などはNoneを返す
            print(f"[SessionStore] DB load failed (this is OK if table doesn't exist): {e}")
            return None

    async def _save_to_db(self, session: Session) -> bool:
        """DBにセッションを保存"""
        try:
            from app.services.supabase_client import get_supabase_client
            supabase = get_supabase_client().client

            data = {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "messages": session.messages,
                "current_state": session.current_state.value,
                "reasoning_steps": session.reasoning_steps,
                "context": session.context,
                "updated_at": datetime.utcnow().isoformat(),
            }

            # upsert
            supabase.table("agent_sessions_v2").upsert(
                data,
                on_conflict="session_id,user_id"
            ).execute()

            return True
        except Exception as e:
            print(f"[SessionStore] DB save failed: {e}")
            return False


# シングルトンインスタンス
_session_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    """SessionStoreのシングルトンインスタンスを取得"""
    global _session_store
    if _session_store is None:
        _session_store = SessionStore()
    return _session_store
