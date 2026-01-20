"""
Developer Executor Tests

Phase 1: 読み取り専用機能のテスト
- ファイル読み取り
- ファイル一覧
- ディレクトリ構造
- Git操作
"""

import pytest
from pathlib import Path

# テスト対象
from app.executors.developer.file_tools import (
    read_file,
    list_files,
    get_structure,
    _is_safe_path,
    _resolve_path,
    PROJECT_ROOT,
)
from app.executors.developer.git_tools import (
    git_status,
    git_diff,
    git_log,
)
from app.executors.developer.executor import DeveloperExecutor


class TestFileSecurity:
    """パスセキュリティのテスト"""

    def test_safe_path_inside_project(self):
        """プロジェクト内のパスは安全"""
        path = PROJECT_ROOT / "app" / "executors"
        assert _is_safe_path(path) is True

    def test_unsafe_path_outside_project(self):
        """プロジェクト外のパスは危険"""
        path = Path("C:/Windows/System32")
        assert _is_safe_path(path) is False

    def test_unsafe_path_env_file(self):
        """環境変数ファイルは危険"""
        path = PROJECT_ROOT / ".env"
        assert _is_safe_path(path) is False

    def test_unsafe_path_credentials(self):
        """認証情報ファイルは危険"""
        path = PROJECT_ROOT / "credentials.json"
        assert _is_safe_path(path) is False

    def test_resolve_relative_path(self):
        """相対パスはプロジェクトルートから解決"""
        resolved = _resolve_path("app/executors")
        assert resolved == PROJECT_ROOT / "app" / "executors"

    def test_resolve_absolute_path(self):
        """絶対パスはそのまま"""
        abs_path = str(PROJECT_ROOT / "app")
        resolved = _resolve_path(abs_path)
        assert str(resolved) == abs_path


class TestFileTools:
    """ファイルツールのテスト"""

    @pytest.mark.asyncio
    async def test_read_file_success(self):
        """ファイル読み取り成功"""
        result = await read_file("README.md")
        # README.mdが存在すれば成功
        if result.success:
            assert result.content is not None
            assert len(result.content) > 0

    @pytest.mark.asyncio
    async def test_read_file_not_found(self):
        """存在しないファイル"""
        result = await read_file("nonexistent_file_12345.txt")
        assert result.success is False
        assert "見つかりません" in result.message

    @pytest.mark.asyncio
    async def test_read_file_blocked_env(self):
        """環境変数ファイルはブロック"""
        result = await read_file(".env")
        assert result.success is False
        assert "許可されていない" in result.message

    @pytest.mark.asyncio
    async def test_list_files_success(self):
        """ファイル一覧取得成功"""
        result = await list_files("app/executors", "*.py")
        assert result.success is True
        assert result.files is not None
        assert len(result.files) > 0

    @pytest.mark.asyncio
    async def test_list_files_recursive(self):
        """再帰的ファイル一覧"""
        result = await list_files("app", "*.py", recursive=True)
        assert result.success is True
        assert result.files is not None
        # 再帰検索なので複数見つかるはず
        assert len(result.files) > 5

    @pytest.mark.asyncio
    async def test_get_structure_success(self):
        """ディレクトリ構造取得成功"""
        result = await get_structure("app", max_depth=2)
        assert result.success is True
        assert result.content is not None  # ツリーテキスト
        assert result.structure is not None  # 構造化データ
        assert "executors" in result.content.lower() or "agent" in result.content.lower()


class TestGitTools:
    """Gitツールのテスト"""

    @pytest.mark.asyncio
    async def test_git_status_success(self):
        """Git status成功"""
        result = await git_status()
        assert result.success is True
        assert result.data is not None
        assert "branch" in result.data
        assert "changes" in result.data

    @pytest.mark.asyncio
    async def test_git_diff_success(self):
        """Git diff成功"""
        result = await git_diff()
        assert result.success is True
        # 差分があるかないかに関わらず成功

    @pytest.mark.asyncio
    async def test_git_log_success(self):
        """Git log成功"""
        result = await git_log(count=5)
        assert result.success is True
        assert result.output is not None
        # コミットがあれば出力がある
        if result.output:
            assert len(result.output) > 0


class TestDeveloperExecutor:
    """DeveloperExecutorのテスト"""

    @pytest.fixture
    def executor(self):
        return DeveloperExecutor()

    @pytest.mark.asyncio
    async def test_search_read_action(self, executor):
        """readアクション"""
        result = await executor._do_search({
            "action": "read",
            "path": "app/executors/developer/__init__.py",
        })
        assert result.success is True
        assert len(result.options) > 0
        assert result.options[0].details.get("content") is not None

    @pytest.mark.asyncio
    async def test_search_list_action(self, executor):
        """listアクション"""
        result = await executor._do_search({
            "action": "list",
            "path": "app/executors",
            "pattern": "*.py",
        })
        assert result.success is True
        assert len(result.options) > 0

    @pytest.mark.asyncio
    async def test_search_structure_action(self, executor):
        """structureアクション"""
        result = await executor._do_search({
            "action": "structure",
            "path": "app",
            "max_depth": "2",
        })
        assert result.success is True
        assert len(result.options) > 0
        assert result.options[0].details.get("tree_text") is not None

    @pytest.mark.asyncio
    async def test_search_git_status_action(self, executor):
        """git_statusアクション"""
        result = await executor._do_search({
            "action": "git_status",
        })
        assert result.success is True
        assert len(result.options) > 0
        assert "branch" in result.options[0].details

    @pytest.mark.asyncio
    async def test_search_git_diff_action(self, executor):
        """git_diffアクション"""
        result = await executor._do_search({
            "action": "git_diff",
        })
        assert result.success is True

    @pytest.mark.asyncio
    async def test_search_git_log_action(self, executor):
        """git_logアクション"""
        result = await executor._do_search({
            "action": "git_log",
            "count": "3",
        })
        assert result.success is True

    @pytest.mark.asyncio
    async def test_search_unknown_action(self, executor):
        """不明なアクション"""
        result = await executor._do_search({
            "action": "unknown_action",
        })
        assert result.success is False
        assert "不明なアクション" in result.message

    @pytest.mark.asyncio
    async def test_executor_properties(self, executor):
        """Executorプロパティ"""
        assert executor.service_type == "developer"
        assert executor.service_name == "developer"
        assert executor._requires_login() is False
