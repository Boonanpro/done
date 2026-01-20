"""
Developer Executor - Self-Healing機能のメインExecutor

ダン自身がスキルを作成・編集・削除できるようにする。

Phase 1: 読み取り専用
- read: ファイル読み取り
- list: ファイル一覧
- structure: ディレクトリ構造
- git_status: Git状態
- git_diff: 差分表示
- git_log: コミット履歴

Phase 2: 変更機能
- write: ファイル書き込み
- delete: ファイル削除
- test: テスト実行
- commit: コミット
- branch: ブランチ操作
"""

import logging
from typing import Dict, Any, Optional, List

from app.executors.base import BaseExecutor, ExecutorSearchResult, SearchOption
from app.executors.developer.file_tools import (
    read_file,
    list_files,
    get_structure,
    write_file,
    delete_file,
    create_directory,
    FileResult,
)
from app.executors.developer.git_tools import (
    git_status,
    git_diff,
    git_log,
    git_show,
    git_blame,
    git_add,
    git_branch,
    git_checkout,
    git_commit,
    git_revert,
    git_reset,
    GitResult,
)
from app.executors.developer.test_runner import (
    run_tests,
    run_specific_tests,
    run_all_tests,
    TestResult,
)
from app.executors.developer.safeguards import (
    determine_approval_level,
    run_test_gate,
    rollback_changes,
    reload_module,
    format_diff_for_approval,
    ChangeTracker,
    ApprovalLevel,
)
from app.services.logging import (
    get_error_tracker,
    get_recent_errors,
    format_errors_for_diagnosis,
    capture_error,
)
from app.services.logging.error_tracker import (
    read_log_file,
    list_log_files,
)
from app.models.schemas import ExecutionResult, SearchResult as TaskSearchResult

logger = logging.getLogger(__name__)


class DeveloperExecutor(BaseExecutor):
    """
    開発機能Executor - Self-Healing

    ダン自身のスキル・コードを操作する機能を提供。
    """

    service_type = "developer"
    service_name = "developer"
    service_display_name = "開発機能"

    async def _do_search(
        self,
        params: Dict[str, Any],
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutorSearchResult:
        """
        探索モード - ファイル/構造の確認

        action パラメータで操作を分岐:
        - read: ファイル読み取り
        - list: ファイル一覧
        - structure: ディレクトリ構造
        - git_status: Git状態
        - git_diff: 差分
        - git_log: 履歴
        """
        action = params.get("action", "structure")

        logger.info(f"Developer search: action={action}")

        try:
            if action == "read":
                return await self._action_read(params)

            elif action == "list":
                return await self._action_list(params)

            elif action in ("structure", "tree"):
                return await self._action_structure(params)

            elif action == "git_status":
                return await self._action_git_status(params)

            elif action == "git_diff":
                return await self._action_git_diff(params)

            elif action == "git_log":
                return await self._action_git_log(params)

            elif action == "git_show":
                return await self._action_git_show(params)

            elif action == "git_blame":
                return await self._action_git_blame(params)

            # Phase 2: 変更アクション
            elif action == "write":
                return await self._action_write(params)

            elif action == "delete":
                return await self._action_delete(params)

            elif action == "mkdir":
                return await self._action_mkdir(params)

            elif action == "test":
                return await self._action_test(params)

            elif action == "git_add":
                return await self._action_git_add(params)

            elif action == "git_commit":
                return await self._action_git_commit(params)

            elif action == "git_branch":
                return await self._action_git_branch(params)

            elif action == "git_checkout":
                return await self._action_git_checkout(params)

            elif action == "approval_check":
                return await self._action_approval_check(params)

            # ログ読み取りアクション
            elif action == "read_logs":
                return await self._action_read_logs(params)

            elif action == "list_logs":
                return await self._action_list_logs(params)

            else:
                return ExecutorSearchResult(
                    success=False,
                    options=[],
                    message=f"不明なアクション: {action}。利用可能: read, list, structure, git_status, git_diff, git_log, write, delete, test, git_commit, read_logs, list_logs",
                )

        except Exception as e:
            logger.error(f"Developer action error: {e}", exc_info=True)
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=f"エラー: {str(e)}",
            )

    async def _action_read(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ファイル読み取り"""
        path = params.get("path")
        if not path:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="path パラメータが必要です",
            )

        result = await read_file(path)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        # ファイル内容をオプションとして返す
        option = SearchOption(
            id=f"file_{path}",
            title=path,
            description=f"ファイル内容 ({len(result.content or '')} 文字)",
            available=True,
            details={
                "content": result.content,
                "path": path,
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_list(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ファイル一覧"""
        path = params.get("path", ".")
        pattern = params.get("pattern", "*")
        recursive = params.get("recursive", "false").lower() == "true"

        result = await list_files(path, pattern, recursive)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        # ファイル一覧をオプションとして返す
        options = []
        for f in (result.files or []):
            options.append(SearchOption(
                id=f"file_{f['path']}",
                title=f['name'],
                description=f"{'[DIR]' if f['is_dir'] else f['size']} bytes" if f.get('size') else "[DIR]",
                available=True,
                details=f,
            ))

        return ExecutorSearchResult(
            success=True,
            options=options,
            message=result.message,
        )

    async def _action_structure(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ディレクトリ構造"""
        path = params.get("path", ".")
        max_depth = int(params.get("max_depth", 3))
        include_files = params.get("include_files", "true").lower() == "true"

        result = await get_structure(path, max_depth, include_files)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="structure",
            title="ディレクトリ構造",
            description=f"{path} の構造 (深度: {max_depth})",
            available=True,
            details={
                "tree_text": result.content,
                "structure": result.structure,
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_git_status(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """Git状態"""
        result = await git_status()

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_status",
            title=f"Git Status - {result.data.get('branch', 'unknown')}",
            description=f"変更: {len(result.data.get('changes', []))}件",
            available=True,
            details={
                "output": result.output,
                **result.data,
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_git_diff(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """差分表示"""
        staged = params.get("staged", "false").lower() == "true"
        path = params.get("path")
        stat_only = params.get("stat_only", "false").lower() == "true"

        result = await git_diff(staged, path, stat_only)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_diff",
            title="Git Diff" + (" (staged)" if staged else ""),
            description=result.message,
            available=True,
            details={
                "diff": result.output,
                **(result.data or {}),
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_git_log(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """コミット履歴"""
        count = int(params.get("count", 10))
        oneline = params.get("oneline", "true").lower() == "true"
        path = params.get("path")

        result = await git_log(count, oneline, path)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_log",
            title=f"Git Log (最新{count}件)",
            description=f"コミット履歴",
            available=True,
            details={
                "log": result.output,
                **(result.data or {}),
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_git_show(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """コミット詳細"""
        commit = params.get("commit", "HEAD")
        path = params.get("path")

        result = await git_show(commit, path)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_show",
            title=f"Git Show - {commit}",
            description="コミット詳細",
            available=True,
            details={
                "show": result.output,
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_git_blame(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ファイル変更履歴"""
        path = params.get("path")
        if not path:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="path パラメータが必要です",
            )

        line_start = params.get("line_start")
        line_end = params.get("line_end")

        result = await git_blame(
            path,
            int(line_start) if line_start else None,
            int(line_end) if line_end else None,
        )

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_blame",
            title=f"Git Blame - {path}",
            description="行ごとの変更履歴",
            available=True,
            details={
                "blame": result.output,
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    # ===========================================
    # Phase 2: 変更アクション
    # ===========================================

    async def _action_write(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ファイル書き込み"""
        path = params.get("path")
        content = params.get("content")

        if not path:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="path パラメータが必要です",
            )

        if content is None:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="content パラメータが必要です",
            )

        # 承認レベルを確認
        approval = determine_approval_level(path)

        result = await write_file(path, content)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id=f"write_{path}",
            title=f"ファイル書き込み: {path}",
            description=f"承認レベル: {approval.level.value}",
            available=True,
            details={
                "path": path,
                "size": len(content),
                "approval_level": approval.level.value,
                "approval_reason": approval.reason,
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_delete(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ファイル削除"""
        path = params.get("path")

        if not path:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="path パラメータが必要です",
            )

        # 承認レベルを確認
        approval = determine_approval_level(path)

        result = await delete_file(path)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id=f"delete_{path}",
            title=f"ファイル削除: {path}",
            description=f"承認レベル: {approval.level.value}",
            available=True,
            details={
                "path": path,
                "original_content": result.content,  # ロールバック用
                "approval_level": approval.level.value,
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_mkdir(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ディレクトリ作成"""
        path = params.get("path")

        if not path:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="path パラメータが必要です",
            )

        result = await create_directory(path)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id=f"mkdir_{path}",
            title=f"ディレクトリ作成: {path}",
            description="作成完了",
            available=True,
            details={"path": path},
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_test(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """テスト実行"""
        paths = params.get("paths")
        pattern = params.get("pattern")
        timeout = int(params.get("timeout", 120))

        if paths:
            paths = paths.split(",") if isinstance(paths, str) else paths

        result = await run_tests(paths=paths, pattern=pattern, timeout=timeout)

        option = SearchOption(
            id="test_result",
            title=f"テスト結果: {'成功' if result.success else '失敗'}",
            description=f"{result.passed} passed, {result.failed} failed",
            available=True,
            details={
                "passed": result.passed,
                "failed": result.failed,
                "skipped": result.skipped,
                "errors": result.errors,
                "output": result.output,
                "failed_tests": result.failed_tests,
                "duration": result.duration,
            },
        )

        return ExecutorSearchResult(
            success=result.success,
            options=[option],
            message=result.message,
        )

    async def _action_git_add(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ステージング"""
        files = params.get("files")

        if not files:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="files パラメータが必要です",
            )

        if isinstance(files, str):
            files = files.split(",")

        result = await git_add(files)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_add",
            title=f"ステージング: {len(files)}件",
            description=result.message,
            available=True,
            details={
                "files": files,
                **(result.data or {}),
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_git_commit(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """コミット"""
        message = params.get("message")
        files = params.get("files")
        add_all = params.get("add_all", "false").lower() == "true"

        if not message:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="message パラメータが必要です",
            )

        if files and isinstance(files, str):
            files = files.split(",")

        result = await git_commit(message, files, add_all)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_commit",
            title=f"コミット: {result.data.get('commit_hash', 'unknown')}",
            description=message[:50],
            available=True,
            details={
                "message": message,
                **(result.data or {}),
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_git_branch(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ブランチ操作"""
        name = params.get("name")
        checkout = params.get("checkout", "false").lower() == "true"
        delete = params.get("delete", "false").lower() == "true"

        result = await git_branch(name, checkout, delete)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_branch",
            title="ブランチ操作",
            description=result.message,
            available=True,
            details={
                "output": result.output,
                **(result.data or {}),
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_git_checkout(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ブランチチェックアウト"""
        name = params.get("name")

        if not name:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="name パラメータが必要です",
            )

        result = await git_checkout(name)

        if not result.success:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message=result.message,
            )

        option = SearchOption(
            id="git_checkout",
            title=f"チェックアウト: {name}",
            description=result.message,
            available=True,
            details={
                **(result.data or {}),
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=result.message,
        )

    async def _action_approval_check(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """承認レベル確認"""
        path = params.get("path")

        if not path:
            return ExecutorSearchResult(
                success=False,
                options=[],
                message="path パラメータが必要です",
            )

        approval = determine_approval_level(path)

        option = SearchOption(
            id="approval_check",
            title=f"承認レベル: {approval.level.value}",
            description=approval.reason,
            available=True,
            details={
                "path": path,
                "level": approval.level.value,
                "reason": approval.reason,
                "requires_confirmation": approval.requires_confirmation,
                "suggested_message": approval.suggested_message,
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=f"{path} の承認レベル: {approval.level.value}",
        )

    # ===========================================
    # ログ読み取りアクション
    # ===========================================

    async def _action_read_logs(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """エラーログ読み取り"""
        source_filter = params.get("source")
        session_id = params.get("session_id")
        minutes = params.get("minutes")
        limit = int(params.get("limit", 20))
        use_db = params.get("use_db", "false").lower() == "true"

        tracker = get_error_tracker()

        if use_db:
            # DBから検索（永続化されたログ）
            recent_errors = tracker.query_db(
                limit=limit,
                source_filter=source_filter,
                session_id=session_id,
                minutes=int(minutes) if minutes else None,
            )
        else:
            # インメモリから取得（高速）
            recent_errors = get_recent_errors(
                limit=limit,
                source_filter=source_filter,
                session_id=session_id,
                minutes=int(minutes) if minutes else None,
            )

        # 診断用にフォーマット
        formatted = format_errors_for_diagnosis(recent_errors)

        # サマリー情報を取得
        summary = tracker.get_error_summary(
            minutes=int(minutes) if minutes else 60,
            session_id=session_id,
        )

        option = SearchOption(
            id="error_logs",
            title=f"エラーログ ({len(recent_errors)}件)",
            description="直近のエラー一覧",
            available=True,
            details={
                "formatted": formatted,
                "errors": recent_errors,
                "summary": summary,
                "source": "database" if use_db else "memory",
            },
        )

        return ExecutorSearchResult(
            success=True,
            options=[option],
            message=f"エラーログ {len(recent_errors)}件を取得しました" if recent_errors else "エラーは記録されていません",
        )

    async def _action_list_logs(self, params: Dict[str, Any]) -> ExecutorSearchResult:
        """ログファイル一覧"""
        files = list_log_files()

        options = []
        for f in files:
            options.append(SearchOption(
                id=f"log_{f['name']}",
                title=f['name'],
                description=f"{f['size_bytes']} bytes, 更新: {f['modified']}",
                available=True,
                details=f,
            ))

        return ExecutorSearchResult(
            success=True,
            options=options,
            message=f"ログファイル {len(files)}件",
        )

    async def _do_execute(
        self,
        task_id: str,
        search_result: TaskSearchResult,
        credentials: Optional[Dict[str, str]] = None,
    ) -> ExecutionResult:
        """
        実行モード - テストゲート付き変更実行

        変更前にテストを実行し、失敗したら自動ロールバック。
        """
        # 実行モードは通常の操作では使用しない
        # _do_search内の各アクションで直接変更を行う
        return ExecutionResult(
            success=True,
            message="Developer Executorは検索モードで変更操作を行います",
        )

    def _requires_login(self) -> bool:
        """ログイン不要"""
        return False
