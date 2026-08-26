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
from app.services.run_service import RunService
from app.models.project_schemas import AgentRunState

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
    """タイトルから絵文字アイコンを生成（Max定額CLI使用、失敗時はキーワードフォールバック）。

    同期関数（ブロッキング）。async から呼ぶ場合は
    `await asyncio.to_thread(generate_icon_for_title, title)` で。
    """
    try:
        # 従量APIは残高ゼロで死んでいるため、Max定額のCLIワンショットを使う
        from app.agent.cli_runner import run_oneshot_cli

        icon = (run_oneshot_cli(
            "次のプロジェクトタイトルに最も合う絵文字を1つだけ返してください。"
            "絵文字1文字のみを返し、説明や他のテキストは一切含めないでください。\n\n"
            f"タイトル: {title}",
            "haiku",
            30,
        ) or "").strip()
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
        if icon and len(icon) <= 4:
            return icon
        return _guess_icon(title)
    except Exception as e:
        logger.warning(f"Icon generation failed, using keyword fallback: {e}")
        return _guess_icon(title)


class ProjectService:
    """プロジェクト管理"""

    def __init__(self):
        self.supabase = get_supabase_client().client

    @staticmethod
    def _parse_timestamp(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    def _enrich_project_read_state(self, project: dict, user_id: str) -> dict:
        """Attach unread metadata for a project-backed chat room."""
        enriched = dict(project)
        room_id = enriched.get("room_id")
        enriched["unread_count"] = 0
        enriched["last_message_at"] = None
        enriched["last_message_preview"] = None
        if not room_id:
            return enriched

        try:
            member = (
                self.supabase.table("chat_room_members")
                .select("unread_count")
                .eq("room_id", room_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if member.data:
                enriched["unread_count"] = member.data[0].get("unread_count") or 0

            room = (
                self.supabase.table("chat_rooms")
                .select("last_message_at,updated_at,last_message_preview")
                .eq("id", room_id)
                .limit(1)
                .execute()
            )
            if room.data:
                enriched["last_message_at"] = room.data[0].get("last_message_at") or room.data[0].get("updated_at")
                enriched["last_message_preview"] = room.data[0].get("last_message_preview")
        except Exception as exc:
            logger.debug("Project unread enrichment skipped (project=%s): %s", enriched.get("id"), exc)
        return enriched

    def _enrich_projects_read_state(self, projects: list[dict], user_id: str) -> list[dict]:
        """Attach unread metadata for many projects without reading chat_messages."""
        enriched = []
        room_ids = [project.get("room_id") for project in projects if project.get("room_id")]
        if not room_ids:
            return [self._enrich_project_read_state(project, user_id) for project in projects]

        member_by_room: dict[str, dict] = {}
        latest_by_room: dict[str, str] = {}
        preview_by_room: dict[str, str] = {}

        try:
            members = (
                self.supabase.table("chat_room_members")
                .select("room_id,unread_count")
                .eq("user_id", user_id)
                .in_("room_id", room_ids)
                .execute()
            )
            member_by_room = {row["room_id"]: row for row in (members.data or [])}

            rooms = (
                self.supabase.table("chat_rooms")
                .select("id,last_message_at,updated_at,last_message_preview")
                .in_("id", room_ids)
                .execute()
            )
            latest_by_room = {
                row["id"]: row.get("last_message_at") or row.get("updated_at")
                for row in (rooms.data or [])
            }
            preview_by_room = {
                row["id"]: row.get("last_message_preview")
                for row in (rooms.data or [])
            }
        except Exception as exc:
            logger.debug("Batch project unread enrichment skipped: %s", exc)
            return [self._enrich_project_read_state(project, user_id) for project in projects]

        for project in projects:
            item = dict(project)
            room_id = item.get("room_id")
            item["unread_count"] = (member_by_room.get(room_id) or {}).get("unread_count") or 0
            item["last_message_at"] = latest_by_room.get(room_id)
            item["last_message_preview"] = preview_by_room.get(room_id)
            enriched.append(item)
        return enriched

    def _attach_active_run_state(self, projects: list[dict]) -> list[dict]:
        """一覧の各プロジェクトに has_active_run（ダンが今動いているか）を付ける。

        サイドバー/アプリのチャット一覧の「作業中」インジケーター用。
        state=='running' かつハートビート(updated_at)が生きている run がある
        プロジェクトだけ True。承認待ち・paused は「動いている」ではないので
        含めない。一覧の読み取りパスなので stale run の後始末（FAILED 更新）は
        ここでは行わない（開いた時の get_current_run が担当）。
        """
        ids = [p.get("id") for p in projects if p.get("id")]
        if not ids:
            return projects
        try:
            rows = (
                self.supabase.table("agent_runs")
                .select("project_id,state,updated_at,created_at")
                .in_("project_id", ids)
                .eq("state", AgentRunState.RUNNING.value)
                .is_("superseded_by_run_id", "null")
                .execute()
            )
            running = {
                row["project_id"]
                for row in (rows.data or [])
                if not RunService._is_run_stale(row)
            }
        except Exception as exc:
            logger.debug("Active-run enrichment skipped: %s", exc)
            running = set()
        for p in projects:
            p["has_active_run"] = p.get("id") in running
        return projects

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

        # アイコン: 作成時は即時のキーワード推定（LLMでブロックしない）。
        # 作成直後はタイトルが「新しいプロジェクト」等で確定していないことが多く、
        # 本番のアイコンはタイトル自動生成→update_project 時に LLM で付け直す。
        icon = _guess_icon(title)

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

        return self._enrich_project_read_state(result.data[0], user_id)

    async def get_project(self, project_id: str, user_id: str) -> Optional[dict]:
        """プロジェクトを取得（所有者チェック付き）"""
        # 同期 Supabase 呼び出しをイベントループの外で実行する。ここと
        # list_projects は一覧ポーリング・部屋切替・current-run が毎秒通る
        # ホットパスで、ループ上で .execute() を待つと全リクエストが直列化
        # していた（8本同時で 3s、単独 0.3s）。処理内容・戻り値は不変。
        return await asyncio.to_thread(self._get_project_sync, project_id, user_id)

    def _get_project_sync(self, project_id: str, user_id: str) -> Optional[dict]:
        result = (
            self.supabase.table("projects")
            .select("*")
            .eq("id", project_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return None
        return self._enrich_project_read_state(result.data[0], user_id)

    async def list_projects(
        self,
        user_id: str,
        status: Optional[str] = None,
    ) -> list[dict]:
        """ユーザーのプロジェクト一覧を取得"""
        # get_project と同じ理由でスレッドに逃がす（3〜4回のDB往復）。
        return await asyncio.to_thread(self._list_projects_sync, user_id, status)

    def _list_projects_sync(
        self,
        user_id: str,
        status: Optional[str] = None,
    ) -> list[dict]:
        query = (
            self.supabase.table("projects")
            .select("*")
            .eq("user_id", user_id)
        )
        if status:
            query = query.eq("status", status)

        result = query.order("updated_at", desc=True).execute()
        enriched = self._enrich_projects_read_state(result.data or [], user_id)
        enriched = self._attach_active_run_state(enriched)
        # LINE-style ordering: pinned items first (newer pins on top), then
        # the rest by activity. We do this in Python rather than SQL because
        # _enrich_projects_read_state already loads everything anyway.
        pinned = [p for p in enriched if p.get("pinned_at")]
        pinned.sort(key=lambda p: p["pinned_at"], reverse=True)
        unpinned = [p for p in enriched if not p.get("pinned_at")]
        unpinned.sort(
            key=lambda p: (
                p.get("last_message_at")
                or p.get("updated_at")
                or p.get("created_at")
                or ""
            ),
            reverse=True,
        )
        return pinned + unpinned

    async def update_project(
        self,
        project_id: str,
        user_id: str,
        **updates,
    ) -> Optional[dict]:
        """プロジェクトを更新"""
        # LINE-style pin: the convenience `pinned: bool` from PATCH becomes
        # a write to the `pinned_at` timestamp column.
        if "pinned" in updates:
            pinned = updates.pop("pinned")
            updates["pinned_at"] = (
                datetime.now(timezone.utc).isoformat() if pinned else None
            )

        # タイトル変更時はアイコンも LLM で付け直す（icon を明示指定していない場合のみ）。
        # フロントの「タイトル自動生成→update」フローに相乗りし、タイトルとアイコンが
        # 一緒に更新される。CLI 呼び出しはスレッドに逃がしてイベントループを塞がない。
        new_title = updates.get("title")
        if new_title and "icon" not in updates:
            try:
                updates["icon"] = await asyncio.to_thread(
                    generate_icon_for_title, new_title
                )
            except Exception:
                pass

        # icon/pin だけの更新では updated_at を据え置く（ソート順をいじらない）。
        # DBトリガーが常に updated_at を更新するため、元の値で上書きする。
        sort_neutral = bool(updates) and set(updates.keys()) <= {"icon", "pinned_at"}
        if sort_neutral:
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
        if not result.data:
            return None
        return self._enrich_project_read_state(result.data[0], user_id)

    async def delete_project(self, project_id: str, user_id: str) -> bool:
        """プロジェクトを削除"""
        # Capture the room before deleting so we can clear its unread state.
        # Deleting only the projects row leaves the chat_room + membership behind;
        # any unread on that orphaned room becomes a "phantom" the app can't show
        # or open (it's no longer a project) yet still fires pushes / inflates the
        # DB count. Zeroing unread on delete prevents that.
        room_id = None
        try:
            proj = (
                self.supabase.table("projects")
                .select("room_id")
                .eq("id", project_id)
                .eq("user_id", user_id)
                .execute()
            )
            if proj.data:
                room_id = proj.data[0].get("room_id")
        except Exception:
            pass

        result = (
            self.supabase.table("projects")
            .delete()
            .eq("id", project_id)
            .eq("user_id", user_id)
            .execute()
        )
        if result.data and room_id:
            try:
                self.supabase.table("chat_room_members").update(
                    {"unread_count": 0}
                ).eq("room_id", room_id).execute()
            except Exception:
                pass
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

    # ==================== Execution Events ====================

    async def save_execution_event(
        self,
        project_id: Optional[str],
        room_id: str,
        event_type: str,
        run_id: Optional[str] = None,
        turn_id: Optional[str] = None,
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
        if turn_id:
            normalized_metadata["turn_id"] = turn_id

        row = {
            "room_id": room_id,
            "run_id": run_id,
            "turn_id": turn_id,
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
