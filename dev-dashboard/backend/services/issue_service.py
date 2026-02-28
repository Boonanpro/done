"""
Issue Service - イシュー関連のビジネスロジック
"""
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from app.services.supabase_client import get_supabase_client


class IssueService:
    """イシューサービス"""

    def __init__(self):
        wrapper = get_supabase_client()
        self.client = wrapper.client

    async def get_issues(
        self,
        status: Optional[str] = None,
        site: Optional[str] = None,
        issue_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> Dict[str, Any]:
        """
        イシュー一覧を取得

        Args:
            status: ステータスでフィルタ
            site: サイト（service_name）でフィルタ
            issue_type: イシュータイプでフィルタ
            limit: 取得件数
            offset: オフセット
            sort_by: ソートカラム
            sort_order: ソート順序

        Returns:
            {"issues": [...], "total": int, "has_more": bool}
        """
        # ベースクエリ
        query = self.client.table("issues").select(
            "id, issue_type, status, priority, original_wish, "
            "service_type, service_name, page_url, error_message, "
            "screenshots, html_snapshot_path, fallback_action, "
            "created_at, last_occurred_at",
            count="exact"
        )

        # フィルタ適用
        if status:
            query = query.eq("status", status)
        if site:
            query = query.eq("service_name", site)
        if issue_type:
            query = query.eq("issue_type", issue_type)

        # ソート
        query = query.order(sort_by, desc=(sort_order == "desc"))

        # ページネーション
        query = query.range(offset, offset + limit - 1)

        result = query.execute()

        total = result.count if result.count else 0
        issues = result.data or []

        return {
            "issues": issues,
            "total": total,
            "has_more": offset + len(issues) < total,
        }

    async def get_issue(self, issue_id: str) -> Optional[Dict[str, Any]]:
        """
        イシュー詳細を取得

        Args:
            issue_id: イシューID

        Returns:
            イシュー詳細（occurrences含む）
        """
        # イシュー本体を取得
        result = self.client.table("issues").select("*").eq("id", issue_id).execute()

        if not result.data:
            return None

        issue = result.data[0]

        # occurrencesを取得
        occurrences_result = self.client.table("issue_occurrences").select(
            "*"
        ).eq("issue_id", issue_id).order("occurred_at", desc=True).limit(20).execute()

        issue["occurrences"] = occurrences_result.data or []

        return issue

    async def update_issue(
        self,
        issue_id: str,
        status: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        イシューを更新

        Args:
            issue_id: イシューID
            status: 新しいステータス

        Returns:
            更新後のイシュー
        """
        update_data = {}

        if status:
            update_data["status"] = status
            if status == "resolved":
                update_data["resolved_at"] = datetime.now(timezone.utc).isoformat()

        if not update_data:
            return await self.get_issue(issue_id)

        result = self.client.table("issues").update(
            update_data
        ).eq("id", issue_id).execute()

        if not result.data:
            return None

        return result.data[0]

    async def get_stats(self) -> Dict[str, Any]:
        """
        統計情報を取得

        Returns:
            {"total": int, "by_status": {...}, "by_type": {...}, "by_site": {...}}
        """
        # 全件取得（集計用）
        result = self.client.table("issues").select(
            "status, issue_type, service_name"
        ).execute()

        issues = result.data or []
        total = len(issues)

        # ステータス別集計
        by_status = {}
        for issue in issues:
            status = issue.get("status", "unknown")
            by_status[status] = by_status.get(status, 0) + 1

        # タイプ別集計
        by_type = {}
        for issue in issues:
            issue_type = issue.get("issue_type", "unknown")
            by_type[issue_type] = by_type.get(issue_type, 0) + 1

        # サイト別集計
        by_site = {}
        for issue in issues:
            site = issue.get("service_name") or "unknown"
            by_site[site] = by_site.get(site, 0) + 1

        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "by_site": by_site,
        }

    async def get_unique_sites(self) -> List[str]:
        """ユニークなサイト一覧を取得"""
        result = self.client.table("issues").select("service_name").execute()
        sites = set()
        for issue in result.data or []:
            if issue.get("service_name"):
                sites.add(issue["service_name"])
        return sorted(list(sites))

    async def get_unique_types(self) -> List[str]:
        """ユニークなイシュータイプ一覧を取得"""
        result = self.client.table("issues").select("issue_type").execute()
        types = set()
        for issue in result.data or []:
            if issue.get("issue_type"):
                types.add(issue["issue_type"])
        return sorted(list(types))


# シングルトンインスタンス
_service: Optional[IssueService] = None


def get_issue_service() -> IssueService:
    """IssueServiceのシングルトンを取得"""
    global _service
    if _service is None:
        _service = IssueService()
    return _service
