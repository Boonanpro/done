"""
Issue Tracker Service

実装すべき機能のイシューを記録し、優先度を追跡する。
実際のユーザーリクエストから発生したイシューを自動検知し、
開発の優先順位付けをサポートする。
"""
from typing import Optional, Any
from dataclasses import dataclass
from enum import Enum
from datetime import datetime
import logging

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class IssueType(Enum):
    """イシュータイプ"""
    EXECUTOR_MISSING = "executor_missing"  # Executorが存在しない
    SELECTOR_OUTDATED = "selector_outdated"  # セレクタが古い
    EXECUTION_FAILED = "execution_failed"  # 実行に失敗した
    SEARCH_FAILED = "search_failed"  # 検索に失敗した


class IssueStatus(Enum):
    """イシューステータス"""
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    WONT_FIX = "wont_fix"


@dataclass
class Issue:
    """イシュー情報"""
    issue_type: IssueType
    original_wish: str
    service_type: Optional[str]
    service_name: Optional[str]
    research_result: dict
    error_message: str
    error_details: dict
    user_id: str


class IssueTracker:
    """イシュートラッカー"""

    def __init__(self):
        supabase_wrapper = get_supabase_client()
        self.supabase = supabase_wrapper.client

    async def record_issue(self, issue: Issue) -> str:
        """
        イシューを記録する

        同じイシュー（同じissue_type + service_type + service_name）が既に存在する場合は、
        priorityを+1し、新しいoccurrenceを追加する。
        存在しない場合は新規イシューを作成する。

        Args:
            issue: イシュー情報

        Returns:
            issue_id: 記録されたイシューのID
        """
        try:
            # 同じイシューが既に存在するかチェック
            existing = await self._find_similar_issue(issue)

            if existing:
                # 既存イシューの優先度を上げる
                issue_id = existing["id"]
                await self._increment_priority(issue_id)

                # 新しいoccurrenceを記録
                await self._record_occurrence(issue_id, issue)

                logger.info(f"Issue {issue_id} priority incremented (now: {existing['priority'] + 1})")
                return issue_id

            # 新規イシューを作成
            suggested_solutions = self._generate_solutions(issue)

            result = self.supabase.table("issues").insert({
                "user_id": issue.user_id,
                "issue_type": issue.issue_type.value,
                "original_wish": issue.original_wish,
                "service_type": issue.service_type,
                "service_name": issue.service_name,
                "research_result": issue.research_result,
                "error_message": issue.error_message,
                "error_details": issue.error_details,
                "suggested_solutions": suggested_solutions,
                "priority": 1,
                "status": IssueStatus.OPEN.value,
            }).execute()

            issue_id = result.data[0]["id"]

            # 最初のoccurrenceを記録
            await self._record_occurrence(issue_id, issue)

            logger.info(f"New issue created: {issue_id} ({issue.issue_type.value})")
            return issue_id

        except Exception as e:
            logger.error(f"Failed to record issue: {e}")
            raise

    async def _find_similar_issue(self, issue: Issue) -> Optional[dict]:
        """
        同じイシューが既に存在するかチェック

        同じ issue_type + service_type + service_name の組み合わせで、
        status が open のイシューを探す。
        """
        try:
            query = self.supabase.table("issues").select("*").eq(
                "issue_type", issue.issue_type.value
            ).eq(
                "status", IssueStatus.OPEN.value
            )

            if issue.service_type:
                query = query.eq("service_type", issue.service_type)
            if issue.service_name:
                query = query.eq("service_name", issue.service_name)

            result = query.execute()

            if result.data and len(result.data) > 0:
                return result.data[0]

            return None

        except Exception as e:
            logger.error(f"Failed to find similar issue: {e}")
            return None

    async def _increment_priority(self, issue_id: str) -> None:
        """イシューの優先度を+1する"""
        try:
            # 現在のpriorityを取得
            result = self.supabase.table("issues").select("priority").eq("id", issue_id).execute()

            if not result.data:
                return

            current_priority = result.data[0]["priority"]

            # +1して更新
            self.supabase.table("issues").update({
                "priority": current_priority + 1,
                "last_occurred_at": datetime.utcnow().isoformat(),
            }).eq("id", issue_id).execute()

        except Exception as e:
            logger.error(f"Failed to increment priority: {e}")

    async def _record_occurrence(self, issue_id: str, issue: Issue) -> None:
        """イシューの発生記録を追加"""
        try:
            self.supabase.table("issue_occurrences").insert({
                "issue_id": issue_id,
                "user_id": issue.user_id,
                "original_wish": issue.original_wish,
                "research_result": issue.research_result,
                "error_message": issue.error_message,
                "error_details": issue.error_details,
            }).execute()

        except Exception as e:
            logger.error(f"Failed to record occurrence: {e}")

    def _generate_solutions(self, issue: Issue) -> list[dict]:
        """
        イシューに対する解決策を生成

        Args:
            issue: イシュー情報

        Returns:
            解決策のリスト
        """
        solutions = []

        if issue.issue_type == IssueType.EXECUTOR_MISSING:
            solutions.append({
                "type": "create_executor",
                "service_type": issue.service_type,
                "service_name": issue.service_name,
                "description": f"{issue.service_name or issue.service_type}のExecutorを新規実装する必要があります",
                "estimated_effort": "medium",
                "suggested_file": f"app/executors/{issue.service_name}_executor.py" if issue.service_name else None,
                "suggested_steps": [
                    f"{issue.service_name}の公式サイトを分析",
                    "予約フローを調査",
                    "必要なセレクタを特定",
                    "search()メソッドを実装",
                    "execute()メソッドを実装",
                    "ExecutorRegistryに登録",
                    "テストスクリプトを作成",
                ],
            })

        elif issue.issue_type == IssueType.SELECTOR_OUTDATED:
            solutions.append({
                "type": "update_selectors",
                "executor": issue.service_name,
                "description": "セレクタが古くなっている可能性があります。サイトを確認してセレクタを更新してください",
                "estimated_effort": "small",
                "suggested_file": f"app/executors/{issue.service_name}/selectors.py" if issue.service_name else None,
                "suggested_steps": [
                    f"{issue.service_name}のサイトにアクセス",
                    "DevToolsで要素を検査",
                    "変更されたセレクタを特定",
                    "selectors.pyを更新",
                    "テストを実行",
                ],
            })

        elif issue.issue_type == IssueType.EXECUTION_FAILED:
            solutions.append({
                "type": "investigate_and_fix",
                "description": "実行フローを調査して修正が必要です",
                "estimated_effort": "unknown",
                "suggested_steps": [
                    "エラーログを確認",
                    "実行フローをステップ実行",
                    "失敗箇所を特定",
                    "修正を実装",
                    "テストを実行",
                ],
            })

        elif issue.issue_type == IssueType.SEARCH_FAILED:
            solutions.append({
                "type": "fix_search",
                "description": "検索機能の修正が必要です",
                "estimated_effort": "small",
                "suggested_steps": [
                    "検索パラメータを確認",
                    "セレクタを検証",
                    "検索結果の解析ロジックを確認",
                    "修正を実装",
                ],
            })

        return solutions

    async def get_open_issues(
        self,
        issue_type: Optional[str] = None,
        service_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        """
        オープンなイシューを取得（優先度順）

        Args:
            issue_type: イシュータイプでフィルタ
            service_type: サービスタイプでフィルタ
            limit: 取得件数

        Returns:
            イシューのリスト
        """
        try:
            query = self.supabase.table("issues").select("*").eq(
                "status", IssueStatus.OPEN.value
            ).order("priority", desc=True).order("created_at", desc=True).limit(limit)

            if issue_type:
                query = query.eq("issue_type", issue_type)
            if service_type:
                query = query.eq("service_type", service_type)

            result = query.execute()
            return result.data

        except Exception as e:
            logger.error(f"Failed to get open issues: {e}")
            return []

    async def get_issue_details(self, issue_id: str) -> Optional[dict]:
        """
        イシューの詳細を取得（occurrencesも含む）

        Args:
            issue_id: イシューID

        Returns:
            イシュー詳細
        """
        try:
            # イシュー本体を取得
            issue_result = self.supabase.table("issues").select("*").eq("id", issue_id).execute()

            if not issue_result.data:
                return None

            issue = issue_result.data[0]

            # occurrencesを取得
            occurrences_result = self.supabase.table("issue_occurrences").select(
                "*"
            ).eq("issue_id", issue_id).order("occurred_at", desc=True).limit(10).execute()

            issue["occurrences"] = occurrences_result.data

            return issue

        except Exception as e:
            logger.error(f"Failed to get issue details: {e}")
            return None

    async def update_issue_status(
        self,
        issue_id: str,
        status: IssueStatus,
    ) -> bool:
        """
        イシューのステータスを更新

        Args:
            issue_id: イシューID
            status: 新しいステータス

        Returns:
            成功したかどうか
        """
        try:
            update_data = {
                "status": status.value,
            }

            if status == IssueStatus.RESOLVED:
                update_data["resolved_at"] = datetime.utcnow().isoformat()

            self.supabase.table("issues").update(update_data).eq("id", issue_id).execute()

            logger.info(f"Issue {issue_id} status updated to {status.value}")
            return True

        except Exception as e:
            logger.error(f"Failed to update issue status: {e}")
            return False
