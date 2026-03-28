"""
Project Service - プロジェクト管理のビジネスロジック
"""
from typing import Optional
from datetime import datetime, timezone
import asyncio
import uuid
import logging

from app.services.supabase_client import get_supabase_client
from app.services.execution_events import normalize_event_type

logger = logging.getLogger(__name__)


_KEYWORD_ICONS = {
    'HP': '🌐', 'ホームページ': '🌐', 'サイト': '🌐', 'Web': '🌐', 'web': '🌐',
    '野球': '⚾', 'スポーツ': '⚾',
    '営業': '💼', 'セールス': '💼', 'B2B': '💼', 'b2b': '💼',
    'ダッシュボード': '📊', 'dashboard': '📊', '管理': '📊',
    '動画': '🎬', 'ビデオ': '🎬', 'Vlog': '🎬', 'Studio': '🎬',
    '提案': '📝', '企画': '📝', '計画': '📝',
    'note': '📮', '記事': '📮', '投稿': '📮', 'ブログ': '📮',
    'デザイン': '🎨', 'ロゴ': '🎨', 'UI': '🎨',
    'アプリ': '📱', 'モバイル': '📱', 'PWA': '📱',
    'AI': '🤖', '自動化': '🤖', 'bot': '🤖',
    '税': '💰', '会計': '💰', '請求': '💰',
    'メール': '📮', 'LINE': '💬', 'チャット': '💬',
    'カレンダー': '📅', '予約': '📅',
    '研究': '🔬', '分析': '🔬',
    '教育': '🎓', '学習': '🎓',
    '写真': '📷', '音楽': '🎵',
    '建設': '🏗️', '工事': '🏗️',
    '不動産': '🏠', '住宅': '🏠',
}


def _guess_icon(title: str) -> str:
    """キーワードベースで絵文字を推定（フォールバック用）"""
    for keyword, emoji in _KEYWORD_ICONS.items():
        if keyword in title:
            return emoji
    return "📁"


def generate_icon_for_title(title: str) -> str:
    """タイトルから絵文字アイコンを生成（Haiku使用、失敗時はキーワードフォールバック）"""
    try:
        import anthropic
        from app.config import settings

        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=10,
            messages=[{
                "role": "user",
                "content": (
                    "以下のプロジェクトタイトルに最も合う絵文字を1つだけ返してください。"
                    "絵文字のみを返し、他のテキストは一切含めないでください。\n\n"
                    f"タイトル: {title}"
                ),
            }],
        )
        icon = resp.content[0].text.strip()
        import re
        emoji_match = re.search(
            r'[\U0001F300-\U0001FAD6\U0001FA70-\U0001FAFF\U00002702-\U000027B0'
            r'\U0000FE00-\U0000FE0F\U0001F900-\U0001F9FF\U0001F600-\U0001F64F'
            r'\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002600-\U000026FF'
            r'\U0000200D\U00002B50\U000023F0-\U000023FA\U0000231A-\U0000231B'
            r'\U00002934-\U00002935\U000025AA-\U000025FE\U00002B05-\U00002B07'
            r'\U00002B1B-\U00002B1C\U00003030\U0000303D\U00003297\U00003299]+',
            icon
        )
        if emoji_match:
            return emoji_match.group(0)
        if len(icon) <= 4:
            return icon
        return _guess_icon(title)
    except Exception as e:
        logger.warning(f"Icon generation failed, using keyword fallback: {e}")
        return _guess_icon(title)


class ProjectService:
    """プロジェクト管理"""

    def __init__(self):
        self.supabase = get_supabase_client().client

    # ==================== Projects ====================

    async def create_project(
        self,
        user_id: str,
        title: str,
        description: Optional[str] = None,
        origin_room_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """プロジェクトを作成し、専用チャットルームも作る"""
        project_id = str(uuid.uuid4())
        room_id = None

        # プロジェクト専用チャットルームを作成
        room_result = self.supabase.table("chat_rooms").insert({
            "name": title,
            "type": "project",
        }).execute()

        if room_result.data:
            room_id = room_result.data[0]["id"]
            # ルームメンバーに追加
            self.supabase.table("chat_room_members").insert({
                "room_id": room_id,
                "user_id": user_id,
                "role": "owner",
            }).execute()

        # アイコン自動生成
        icon = generate_icon_for_title(title)

        # プロジェクトを作成
        insert_data = {
            "id": project_id,
            "user_id": user_id,
            "title": title,
            "description": description,
            "status": "planning",
            "room_id": room_id,
            "origin_room_id": origin_room_id,
            "icon": icon,
        }
        if metadata:
            insert_data["metadata"] = metadata

        result = self.supabase.table("projects").insert(insert_data).execute()

        if not result.data:
            raise ValueError("Failed to create project")

        return result.data[0]

    async def get_project(self, project_id: str, user_id: str) -> Optional[dict]:
        """プロジェクトを取得（所有者チェック付き）"""
        result = (
            self.supabase.table("projects")
            .select("*")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def list_projects(
        self,
        user_id: str,
        status: Optional[str] = None,
    ) -> list[dict]:
        """ユーザーのプロジェクト一覧を取得"""
        query = (
            self.supabase.table("projects")
            .select("*")
            .eq("user_id", user_id)
        )
        if status:
            query = query.eq("status", status)

        result = query.order("updated_at", desc=True).execute()
        return result.data or []

    async def update_project(
        self,
        project_id: str,
        user_id: str,
        **updates,
    ) -> Optional[dict]:
        """プロジェクトを更新"""
        # iconのみの更新ではupdated_atを変更しない（ソート順を維持）
        # DBトリガーが常にupdated_atを更新するため、元の値で上書きする
        icon_only = set(updates.keys()) == {"icon"}
        if icon_only:
            current = self.supabase.table("projects").select("updated_at").eq("id", project_id).execute()
            if current.data:
                updates["updated_at"] = current.data[0]["updated_at"]
        else:
            updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = (
            self.supabase.table("projects")
            .update(updates)
            .eq("id", project_id)
            .eq("user_id", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    async def delete_project(self, project_id: str, user_id: str) -> bool:
        """プロジェクトを削除"""
        result = (
            self.supabase.table("projects")
            .delete()
            .eq("id", project_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(result.data)

    async def get_project_by_room_id(self, room_id: str) -> Optional[dict]:
        """room_idからプロジェクトを取得（runner.pyのコンテキスト注入用）"""
        result = (
            self.supabase.table("projects")
            .select("*")
            .eq("room_id", room_id)
            .execute()
        )
        return result.data[0] if result.data else None

    # ==================== Proposals ====================

    async def create_proposal(
        self,
        project_id: str,
        content: str,
        proposal_type: str = "plan",
        steps: Optional[list] = None,
        run_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """プロジェクトに提案を作成"""
        # 既存のpending提案をsupersededに
        self.supabase.table("project_proposals").update({
            "status": "superseded",
        }).eq("project_id", project_id).eq("status", "pending").execute()

        insert_data = {
            "project_id": project_id,
            "run_id": run_id,
            "content": content,
            "proposal_type": proposal_type,
            "steps": steps or [],
            "status": "pending",
        }
        if metadata:
            insert_data["metadata"] = metadata

        result = self.supabase.table("project_proposals").insert(insert_data).execute()

        if not result.data:
            raise ValueError("Failed to create proposal")

        # プロジェクトステータスをproposedに
        self.supabase.table("projects").update({
            "status": "proposed",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", project_id).execute()

        return result.data[0]

    async def get_proposals(self, project_id: str) -> list[dict]:
        """プロジェクトの提案一覧"""
        result = (
            self.supabase.table("project_proposals")
            .select("*")
            .eq("project_id", project_id)
            .order("created_at", desc=True)
            .execute()
        )
        return result.data or []

    async def approve_proposal(self, proposal_id: str, project_id: str) -> Optional[dict]:
        """提案を承認"""
        result = (
            self.supabase.table("project_proposals")
            .update({
                "status": "approved",
                "approved_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", proposal_id)
            .eq("project_id", project_id)
            .eq("status", "pending")
            .execute()
        )

        if result.data:
            # プロジェクトステータスをapprovedに
            self.supabase.table("projects").update({
                "status": "approved",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", project_id).execute()

        return result.data[0] if result.data else None

    async def update_step_status(
        self,
        proposal_id: str,
        step_number: Optional[int],
        status: str,
    ) -> None:
        """
        提案のステップ状況を更新。

        step_number=None → 全ステップ更新
        step_number=N → 特定ステップ更新
        """
        # 現在のproposalを取得
        result = (
            self.supabase.table("project_proposals")
            .select("steps")
            .eq("id", proposal_id)
            .execute()
        )
        if not result.data:
            return

        steps = result.data[0].get("steps") or []
        if not steps:
            return

        if step_number is None:
            # 全ステップを更新
            for step in steps:
                step["status"] = status
        else:
            # 特定ステップを更新
            for step in steps:
                if step.get("step_number") == step_number:
                    step["status"] = status
                    break

        self.supabase.table("project_proposals").update({
            "steps": steps,
        }).eq("id", proposal_id).execute()

    async def reject_proposal(self, proposal_id: str, project_id: str) -> Optional[dict]:
        """提案を却下"""
        result = (
            self.supabase.table("project_proposals")
            .update({"status": "rejected"})
            .eq("id", proposal_id)
            .eq("project_id", project_id)
            .eq("status", "pending")
            .execute()
        )

        if result.data:
            # プロジェクトステータスをplanningに戻す
            self.supabase.table("projects").update({
                "status": "planning",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", project_id).execute()

        return result.data[0] if result.data else None

    async def supersede_proposal(self, proposal_id: str, project_id: str) -> Optional[dict]:
        """Replace a pending proposal when a newer run takes over."""
        result = (
            self.supabase.table("project_proposals")
            .update({"status": "superseded"})
            .eq("id", proposal_id)
            .eq("project_id", project_id)
            .eq("status", "pending")
            .execute()
        )
        return result.data[0] if result.data else None

    # ==================== Execution Events ====================

    async def save_execution_event(
        self,
        project_id: Optional[str],
        room_id: str,
        event_type: str,
        run_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        tool_label: Optional[str] = None,
        content: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        """実行イベントを記録（プロジェクト・通常チャット両対応）"""
        normalized_type, original_type = normalize_event_type(event_type)
        normalized_metadata = dict(metadata or {})
        if original_type is not None and original_type != normalized_type:
            normalized_metadata["original_event_type"] = original_type

        row = {
            "room_id": room_id,
            "run_id": run_id,
            "event_type": normalized_type,
            "tool_name": tool_name,
            "tool_label": tool_label,
            "content": content,
            "metadata": normalized_metadata,
        }
        if project_id:
            row["project_id"] = project_id
        # NOTE: supabase-py の .execute() は同期HTTPコール。SSE内で呼ばれるため別スレッドで実行。
        query = self.supabase.table("execution_events").insert(row)
        result = await asyncio.to_thread(query.execute)
        return result.data[0] if result.data else {}

    async def get_execution_events(
        self,
        project_id: str,
        limit: int = 100,
        after: Optional[str] = None,
        since_seq: Optional[int] = None,
        run_id: Optional[str] = None,
    ) -> list[dict]:
        """プロジェクトの実行イベント一覧を取得"""
        query = (
            self.supabase.table("execution_events")
            .select("*")
            .eq("project_id", project_id)
        )
        if run_id:
            query = query.eq("run_id", run_id)
        if since_seq is not None:
            query = query.gt("seq", since_seq)
        elif after:
            query = query.gt("created_at", after)
        result = query.order("created_at", desc=True).limit(limit).execute()
        return list(reversed(result.data or []))

    async def get_execution_events_by_room(
        self,
        room_id: str,
        limit: int = 100,
        since_seq: Optional[int] = None,
        current_only: bool = False,
    ) -> list[dict]:
        """room_idで実行イベント一覧を取得（通常チャット用）

        current_only=True: 最後のdoneイベント以降のみ返す（現在の実行分のみ）
        """
        if current_only and since_seq is None:
            # 最後のdoneイベントのseqを取得
            done_query = (
                self.supabase.table("execution_events")
                .select("seq")
                .eq("room_id", room_id)
                .eq("event_type", "done")
                .order("seq", desc=True)
                .limit(1)
            )
            done_result = done_query.execute()
            if done_result.data:
                since_seq = done_result.data[0]["seq"]

        query = (
            self.supabase.table("execution_events")
            .select("*")
            .eq("room_id", room_id)
        )
        if since_seq is not None:
            query = query.gt("seq", since_seq)
        result = query.order("seq", desc=False).limit(limit).execute()
        return result.data or []
