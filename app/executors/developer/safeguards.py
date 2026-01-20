"""
Safeguards - 安全機構

承認レベル判定、テストゲート、自動ロールバック、モジュール再読み込み機能。

承認レベル:
- AUTO: 自動承認（テストファイル新規作成など）
- SIMPLE: 1行確認（ドメインスキル変更）
- DETAILED: 差分表示 + 確認（Executor変更）
- STRICT: 詳細説明 + 明示的承認（コアモジュール変更）
"""

import logging
import importlib
import sys
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)

# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


class ApprovalLevel(str, Enum):
    """承認レベル"""
    AUTO = "auto"          # 自動承認
    SIMPLE = "simple"      # 1行確認
    DETAILED = "detailed"  # 差分表示 + 確認
    STRICT = "strict"      # 詳細説明 + 明示的承認


@dataclass
class ApprovalResult:
    """承認結果"""
    level: ApprovalLevel
    reason: str
    requires_confirmation: bool
    suggested_message: Optional[str] = None


@dataclass
class TestGateResult:
    """テストゲート結果"""
    passed: bool
    message: str
    test_output: Optional[str] = None
    failed_tests: Optional[List[str]] = None


@dataclass
class RollbackResult:
    """ロールバック結果"""
    success: bool
    message: str
    reverted_files: Optional[List[str]] = None


def determine_approval_level(path: str) -> ApprovalResult:
    """
    変更対象パスから承認レベルを判定

    | 変更対象 | レベル | 承認方法 |
    |---------|-------|---------|
    | tests/*.py (新規) | AUTO | 自動、ログのみ |
    | .claude/skills/domains/** | SIMPLE | 1行確認 |
    | app/executors/*.py | DETAILED | 差分表示 + 確認 |
    | app/agent/**, core/ | STRICT | 詳細説明 + 明示的承認 |

    Args:
        path: 変更対象のパス（相対パス）

    Returns:
        ApprovalResult: 承認レベルと理由
    """
    path_lower = path.lower().replace("\\", "/")

    # STRICT: コアモジュール
    strict_patterns = [
        "app/agent/",
        ".claude/skills/core/",
        "app/config",
        "main.py",
    ]
    for pattern in strict_patterns:
        if pattern in path_lower:
            return ApprovalResult(
                level=ApprovalLevel.STRICT,
                reason=f"コアモジュール（{pattern}）の変更は詳細な承認が必要です",
                requires_confirmation=True,
                suggested_message=f"このファイルはシステムの中核部分です。変更内容を詳細に説明し、明示的な承認を得てください。",
            )

    # DETAILED: Executor
    if "app/executors/" in path_lower and path_lower.endswith(".py"):
        return ApprovalResult(
            level=ApprovalLevel.DETAILED,
            reason="Executorファイルの変更は差分確認が必要です",
            requires_confirmation=True,
            suggested_message="変更内容の差分を表示し、確認を求めてください。",
        )

    # SIMPLE: ドメインスキル
    if ".claude/skills/domains/" in path_lower or ".claude/skills/ex-reservation" in path_lower:
        return ApprovalResult(
            level=ApprovalLevel.SIMPLE,
            reason="ドメインスキルの変更です",
            requires_confirmation=True,
            suggested_message="変更の概要を1行で説明してください。",
        )

    # AUTO: テストファイル（新規）
    if path_lower.startswith("tests/") and path_lower.endswith(".py"):
        return ApprovalResult(
            level=ApprovalLevel.AUTO,
            reason="テストファイルの変更は自動承認されます",
            requires_confirmation=False,
        )

    # AUTO: テンプレート
    if "templates/" in path_lower:
        return ApprovalResult(
            level=ApprovalLevel.AUTO,
            reason="テンプレートファイルの変更は自動承認されます",
            requires_confirmation=False,
        )

    # デフォルト: SIMPLE
    return ApprovalResult(
        level=ApprovalLevel.SIMPLE,
        reason="一般的なファイル変更です",
        requires_confirmation=True,
    )


async def run_test_gate(
    test_paths: Optional[List[str]] = None,
    timeout: int = 120,
) -> TestGateResult:
    """
    テストゲートを実行

    変更前後でテストを実行し、結果を返す。

    Args:
        test_paths: テスト対象パス（省略時は全テスト）
        timeout: タイムアウト秒数

    Returns:
        TestGateResult: テスト結果
    """
    import subprocess

    try:
        cmd = ["python", "-m", "pytest", "-v", "--tb=short"]

        if test_paths:
            cmd.extend(test_paths)
        else:
            # 全テストは重いので、基本的なテストのみ
            cmd.append("tests/")

        logger.info(f"Running tests: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )

        output = result.stdout + result.stderr

        if result.returncode == 0:
            return TestGateResult(
                passed=True,
                message="全てのテストがパスしました",
                test_output=output,
            )
        else:
            # 失敗したテストを抽出
            failed_tests = []
            for line in output.split("\n"):
                if "FAILED" in line:
                    failed_tests.append(line.strip())

            return TestGateResult(
                passed=False,
                message=f"テストが失敗しました: {len(failed_tests)}件",
                test_output=output,
                failed_tests=failed_tests,
            )

    except subprocess.TimeoutExpired:
        return TestGateResult(
            passed=False,
            message=f"テストがタイムアウトしました（{timeout}秒）",
        )
    except Exception as e:
        logger.error(f"Test gate error: {e}")
        return TestGateResult(
            passed=False,
            message=f"テスト実行エラー: {str(e)}",
        )


async def rollback_changes(files: List[str]) -> RollbackResult:
    """
    変更をロールバック

    git checkout で変更を元に戻す。

    Args:
        files: ロールバック対象ファイル

    Returns:
        RollbackResult: ロールバック結果
    """
    import subprocess

    try:
        reverted = []

        for file_path in files:
            cmd = ["git", "checkout", "--", file_path]

            result = subprocess.run(
                cmd,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
                encoding="utf-8",
            )

            if result.returncode == 0:
                reverted.append(file_path)
                logger.info(f"Reverted: {file_path}")
            else:
                logger.warning(f"Failed to revert {file_path}: {result.stderr}")

        if len(reverted) == len(files):
            return RollbackResult(
                success=True,
                message=f"{len(reverted)}件のファイルをロールバックしました",
                reverted_files=reverted,
            )
        else:
            return RollbackResult(
                success=False,
                message=f"一部のファイルのロールバックに失敗: {len(reverted)}/{len(files)}",
                reverted_files=reverted,
            )

    except Exception as e:
        logger.error(f"Rollback error: {e}")
        return RollbackResult(
            success=False,
            message=f"ロールバックエラー: {str(e)}",
        )


async def reload_module(module_path: str) -> Dict[str, Any]:
    """
    Pythonモジュールを再読み込み

    変更されたexecutorやtools.pyを即座に反映。

    Args:
        module_path: モジュールパス（例: "app.executors.developer.executor"）

    Returns:
        dict: 再読み込み結果
            - success: 成功/失敗
            - message: メッセージ
            - requires_restart: プロセス再起動が必要か
    """
    try:
        # モジュールパスをPythonモジュール形式に変換
        if module_path.endswith(".py"):
            module_path = module_path[:-3]

        module_path = module_path.replace("/", ".").replace("\\", ".")

        # app/ を app. に変換
        if module_path.startswith("app."):
            pass  # そのまま
        elif module_path.startswith("app/"):
            module_path = "app." + module_path[4:]

        # モジュールがロード済みか確認
        if module_path in sys.modules:
            module = sys.modules[module_path]
            try:
                importlib.reload(module)
                logger.info(f"Reloaded module: {module_path}")
                return {
                    "success": True,
                    "message": f"モジュール {module_path} を再読み込みしました",
                    "requires_restart": False,
                }
            except Exception as reload_error:
                logger.warning(f"Reload failed, may need restart: {reload_error}")
                return {
                    "success": False,
                    "message": f"再読み込みに失敗しました。プロセス再起動を推奨します: {str(reload_error)}",
                    "requires_restart": True,
                }
        else:
            # まだロードされていない場合は成功扱い（次回使用時に読み込まれる）
            return {
                "success": True,
                "message": f"モジュール {module_path} は未ロードのため、次回使用時に読み込まれます",
                "requires_restart": False,
            }

    except Exception as e:
        logger.error(f"Module reload error: {e}")
        return {
            "success": False,
            "message": f"モジュール再読み込みエラー: {str(e)}",
            "requires_restart": True,
        }


def format_diff_for_approval(diff_output: str, level: ApprovalLevel) -> str:
    """
    承認レベルに応じた差分フォーマットを生成

    Args:
        diff_output: git diff の出力
        level: 承認レベル

    Returns:
        フォーマットされた差分テキスト
    """
    if not diff_output:
        return "（変更なし）"

    if level == ApprovalLevel.STRICT:
        # 全差分を表示
        return f"""### 変更内容（詳細）

```diff
{diff_output}
```

### 確認事項
- この変更はシステムの中核部分に影響します
- 変更による影響範囲を説明してください
- 明示的な承認が必要です

この変更を適用してよろしいですか？"""

    elif level == ApprovalLevel.DETAILED:
        # 差分を表示（短縮なし）
        return f"""### 変更内容

```diff
{diff_output}
```

この変更を適用してよろしいですか？"""

    elif level == ApprovalLevel.SIMPLE:
        # 統計情報のみ
        lines = diff_output.split("\n")
        added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
        removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))

        return f"変更: +{added}行 / -{removed}行。適用しますか？"

    else:  # AUTO
        return "（自動承認）"


class ChangeTracker:
    """
    変更追跡クラス

    変更されたファイルを追跡し、必要に応じてロールバックする。
    """

    def __init__(self):
        self.changed_files: List[str] = []
        self.original_contents: Dict[str, str] = {}

    def track_file(self, path: str, original_content: Optional[str] = None) -> None:
        """変更を追跡"""
        if path not in self.changed_files:
            self.changed_files.append(path)

        if original_content is not None:
            self.original_contents[path] = original_content

    def get_changed_files(self) -> List[str]:
        """変更されたファイル一覧"""
        return self.changed_files.copy()

    def clear(self) -> None:
        """追跡をクリア"""
        self.changed_files = []
        self.original_contents = {}

    async def rollback_all(self) -> RollbackResult:
        """全ての変更をロールバック"""
        if not self.changed_files:
            return RollbackResult(
                success=True,
                message="ロールバック対象の変更がありません",
            )

        result = await rollback_changes(self.changed_files)
        if result.success:
            self.clear()
        return result
