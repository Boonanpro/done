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
    # contentはstrまたはList[ContentBlock]（Vision API対応）
    messages: List[Dict[str, Any]] = field(default_factory=list)

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
        self.updated_at = datetime.now(timezone.utc)

    def add_user_message_with_images(
        self,
        text: str,
        images: List[Dict[str, Any]],
    ) -> None:
        """
        画像を含むユーザーメッセージを追加（Vision API対応）

        Args:
            text: テキストコンテンツ
            images: 画像コンテンツのリスト（Anthropic Vision API形式）
                   例: [{"type": "image", "source": {"type": "base64", ...}}]
        """
        if not images:
            # 画像がなければ通常のメッセージとして追加
            self.add_user_message(text)
            return

        # 画像 + テキストのcontent blocks形式
        content_blocks = []

        # 画像を先に追加（LLMが画像を見てからテキストを読む）
        for img in images:
            content_blocks.append(img)

        # テキストを追加
        content_blocks.append({
            "type": "text",
            "text": text,
        })

        self.messages.append({
            "role": "user",
            "content": content_blocks,
        })
        self.updated_at = datetime.now(timezone.utc)

    def add_assistant_message(self, content: str) -> None:
        """アシスタントメッセージを追加"""
        self.messages.append({
            "role": "assistant",
            "content": content
        })
        self.updated_at = datetime.now(timezone.utc)

    def add_assistant_message_from_blocks(self, blocks: List[Dict[str, Any]]) -> None:
        """Gemini応答をAnthropic形式ブロックとして保存"""
        self.messages.append({"role": "assistant", "content": blocks})
        self.updated_at = datetime.now(timezone.utc)

    def add_assistant_message_from_response(self, response: Any) -> None:
        """
        Anthropic Message responseからアシスタントメッセージを追加（Native Tool Use対応）

        Args:
            response: anthropic.types.Message オブジェクト
        """
        # content blocksをそのまま保存（text, tool_use, server_tool_use, web_search_tool_result を含む）
        content_blocks = []
        for block in response.content:
            if block.type == "thinking":
                content_blocks.append({
                    "type": "thinking",
                    "thinking": block.thinking,
                    "signature": getattr(block, 'signature', ''),
                })
            elif block.type == "text":
                content_blocks.append({
                    "type": "text",
                    "text": block.text,
                })
            elif block.type == "tool_use":
                content_blocks.append({
                    "type": "tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
            elif block.type == "server_tool_use":
                content_blocks.append({
                    "type": "server_tool_use",
                    "id": block.id,
                    "name": block.name,
                    "input": block.input if hasattr(block, 'input') else {},
                })
            elif block.type == "web_search_tool_result":
                content_blocks.append({
                    "type": "web_search_tool_result",
                    "tool_use_id": block.tool_use_id,
                    "content": block.content if hasattr(block, 'content') else [],
                })

        self.messages.append({
            "role": "assistant",
            "content": content_blocks,
        })
        self.updated_at = datetime.now(timezone.utc)

    def add_tool_result(
        self,
        tool_use_id: str,
        content: str,
        images: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """
        ツール実行結果を追加（Native Tool Use対応）

        Args:
            tool_use_id: ツール呼び出しID
            content: ツール実行結果のテキスト
            images: 画像コンテンツ（Vision API用）
        """
        if images:
            # 画像を含む場合はcontent blocks形式
            result_content = []
            for img in images:
                result_content.append(img)
            result_content.append({
                "type": "text",
                "text": content,
            })
        else:
            result_content = content

        # Ensure one tool_result per tool_use_id by replacing existing content if present.
        for msg in self.messages:
            if msg.get("role") != "user":
                continue
            blocks = msg.get("content")
            if not isinstance(blocks, list):
                continue
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    if block.get("tool_use_id") == tool_use_id:
                        block["content"] = result_content
                        self.updated_at = datetime.now(timezone.utc)
                        return

        self.messages.append({
            "role": "user",
            "content": [{
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result_content,
            }],
        })
        self.updated_at = datetime.now(timezone.utc)

    def add_reasoning_step(self, step: str) -> None:
        """推論ステップを追加（ナレーション用）"""
        self.reasoning_steps.append(step)

    def clear_reasoning_steps(self) -> None:
        """推論ステップをクリア（次のターン用）"""
        self.reasoning_steps = []

    def get_messages_for_llm(self) -> List[Dict[str, Any]]:
        """LLMに渡すメッセージ配列を取得（壊れたペアを自動修復）"""
        return self._sanitize_tool_pairs(self.messages.copy())

    @staticmethod
    def _sanitize_tool_pairs(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        操作(tool_use)と結果(tool_result)のペアが壊れている場合に修復する。

        - 結果だけあって操作がない → その結果を除去
        - 操作だけあって結果がない → ダミーの結果を挿入
        """
        # Pass 1: 全assistantメッセージからtool_use IDを収集
        tool_use_ids = set()
        for msg in messages:
            if msg.get("role") != "assistant":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        tool_use_ids.add(block.get("id"))

        # Pass 2: 全userメッセージからtool_result IDを収集
        tool_result_ids = set()
        for msg in messages:
            if msg.get("role") != "user":
                continue
            content = msg.get("content", "")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        tool_result_ids.add(block.get("tool_use_id"))

        # 孤立した結果（操作が見つからない）のID
        orphaned_results = tool_result_ids - tool_use_ids
        # 孤立した操作（結果が見つからない）のID
        orphaned_uses = tool_use_ids - tool_result_ids

        if not orphaned_results and not orphaned_uses:
            return messages

        result = []
        for msg in messages:
            content = msg.get("content", "")

            # userメッセージ: 孤立した結果を除去
            if msg.get("role") == "user" and isinstance(content, list):
                filtered = [
                    block for block in content
                    if not (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") in orphaned_results
                    )
                ]
                if filtered:
                    result.append({"role": "user", "content": filtered})
                # filteredが空なら（結果だけのメッセージだった場合）メッセージごと除去
                continue

            # assistantメッセージの後にダミー結果を挿入する必要があるかチェック
            result.append(msg)

            if msg.get("role") == "assistant" and isinstance(content, list):
                needs_dummy = []
                for block in content:
                    if (isinstance(block, dict)
                            and block.get("type") == "tool_use"
                            and block.get("id") in orphaned_uses):
                        needs_dummy.append(block["id"])

                if needs_dummy:
                    dummy_blocks = [
                        {
                            "type": "tool_result",
                            "tool_use_id": tid,
                            "content": "[操作が中断されました]",
                        }
                        for tid in needs_dummy
                    ]
                    result.append({"role": "user", "content": dummy_blocks})

        return result

    def estimate_token_count(self) -> int:
        """
        メッセージのトークン数を推定

        簡易推定: 日本語は1文字≒1-2トークン、英語は1単語≒1トークン
        正確ではないが、閾値判定には十分
        """
        total_chars = 0
        for msg in self.messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total_chars += len(content)
            elif isinstance(content, list):
                # content blocks形式
                for block in content:
                    if isinstance(block, dict):
                        if block.get("type") == "text":
                            total_chars += len(block.get("text", ""))
                        elif block.get("type") == "tool_use":
                            # tool inputも含める
                            total_chars += len(json.dumps(block.get("input", {})))
                        elif block.get("type") == "tool_result":
                            result = block.get("content", "")
                            if isinstance(result, str):
                                total_chars += len(result)
                            elif isinstance(result, list):
                                for r in result:
                                    if isinstance(r, dict) and r.get("type") == "text":
                                        total_chars += len(r.get("text", ""))
        # 日本語中心なので、文字数 ≒ トークン数として扱う
        return total_chars

    def compact(self, summary: str, keep_recent: int = 10) -> int:
        """
        古いメッセージを削除し、要約で置き換える

        Args:
            summary: 削除されるメッセージの要約
            keep_recent: 残す最新メッセージ数

        Returns:
            削除されたメッセージ数
        """
        if len(self.messages) <= keep_recent:
            return 0

        # 最新のkeep_recent件を残す
        recent_messages = self.messages[-keep_recent:]

        # 先頭に孤立した操作結果（対応する操作が削除済み）が残っていたら除去
        while recent_messages:
            msg = recent_messages[0]
            content = msg.get("content", "")
            has_orphan = False
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        has_orphan = True
                        break
            if has_orphan:
                recent_messages.pop(0)
            else:
                break

        # 要約メッセージを先頭に挿入
        summary_message = {
            "role": "user",
            "content": f"[会話の要約]\n{summary}\n\n---\n以下は最近の会話です。"
        }

        to_remove = len(self.messages) - len(recent_messages)

        # 新しいメッセージ配列を構築
        self.messages = [summary_message] + recent_messages
        self.updated_at = datetime.now(timezone.utc)

        return to_remove

    def set_context(self, key: str, value: Any) -> None:
        """コンテキストに値を設定"""
        self.context[key] = value
        self.updated_at = datetime.now(timezone.utc)

    def get_context(self, key: str, default: Any = None) -> Any:
        """コンテキストから値を取得"""
        return self.context.get(key, default)

    def transition_to(self, new_state: State) -> None:
        """状態を遷移"""
        self.current_state = new_state
        self.updated_at = datetime.now(timezone.utc)

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

        # 注: メッセージの整合性修復はSessionStore.get_or_createで行う
        # （修復時にDBも更新する必要があるため）

        return session

    def _repair_messages(self) -> None:
        """
        メッセージ配列の整合性を修復

        Claude APIの要件:
        - tool_useを含むassistantメッセージの後には、必ずtool_resultが必要
        - userメッセージが連続してはいけない（user→assistant→user→...の交互）
        - この要件を満たさないメッセージを修復する

        エラー発生時やキャンセル時にセッションが不整合な状態で残った場合の自動復旧用。
        """
        import logging
        logger = logging.getLogger(__name__)

        repaired = False
        max_iterations = 10  # 無限ループ防止

        for _ in range(max_iterations):
            if not self.messages:
                break

            last_msg = self.messages[-1]

            # 最後がassistantメッセージでtool_useを含んでいる場合
            if last_msg.get("role") == "assistant":
                content = last_msg.get("content", [])
                if isinstance(content, list):
                    has_tool_use = any(
                        block.get("type") == "tool_use"
                        for block in content
                        if isinstance(block, dict)
                    )
                    if has_tool_use:
                        # tool_resultがないので削除
                        logger.warning(
                            f"[Session._repair_messages] Removing incomplete assistant message "
                            f"(tool_use without tool_result) from session {self.session_id}"
                        )
                        self.messages.pop()
                        repaired = True
                        continue  # 再度チェック

            # 最後がuserメッセージの場合（キャンセル等でAI回答がない）
            # → ダミーのassistantメッセージを挿入してペアを完成させる
            if last_msg.get("role") == "user":
                logger.warning(
                    f"[Session._repair_messages] Trailing user message without assistant response "
                    f"in session {self.session_id}, inserting interrupted marker"
                )
                self.messages.append({
                    "role": "assistant",
                    "content": "（中断されました）"
                })
                repaired = True
                # 挿入後は再チェック不要（assistantで終わっている）

            # 問題なければ終了
            break

        if repaired:
            logger.info(
                f"[Session._repair_messages] Session {self.session_id} repaired, "
                f"now has {len(self.messages)} messages"
            )


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

    def invalidate_cache(self, session_id: str, user_id: str) -> None:
        """
        キャッシュを無効化（エラー発生時の復旧用）

        メモリ上のセッションが不整合な状態になった場合に呼び出す。
        次回のget_or_createでDBから最後に正常保存された状態を読み込む。
        """
        key = self._make_key(session_id, user_id)
        if key in self._cache:
            del self._cache[key]

    async def get_or_create(self, session_id: str, user_id: str) -> Session:
        """セッションを取得または作成"""
        import logging
        logger = logging.getLogger(__name__)

        key = self._make_key(session_id, user_id)

        # キャッシュにあれば返す（キャンセル等で不整合になった場合も常に修復）
        if key in self._cache:
            session = self._cache[key]
            original_count = len(session.messages)
            session._repair_messages()
            if len(session.messages) != original_count:
                logger.info(
                    f"[SessionStore] Repaired cached session {session_id}: "
                    f"{original_count} -> {len(session.messages)} messages"
                )
            return session

        # DBから取得を試みる
        session = await self._load_from_db(session_id, user_id)

        if session is None:
            # 新規作成
            session = Session(session_id=session_id, user_id=user_id)
        else:
            # ★★★ メッセージの整合性を修復 ★★★
            original_count = len(session.messages)
            session._repair_messages()

            # 修復があった場合はDBも更新
            if len(session.messages) != original_count:
                logger.info(
                    f"[SessionStore] Session {session_id} repaired: "
                    f"{original_count} -> {len(session.messages)} messages. Saving to DB."
                )
                await self._save_to_db(session)

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
                "updated_at": datetime.now(timezone.utc).isoformat(),
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
