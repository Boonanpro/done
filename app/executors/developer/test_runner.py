"""
Test Runner - テスト実行ユーティリティ

テストの実行と結果の取得を行う。
"""

import logging
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@dataclass
class TestResult:
    """テスト実行結果"""
    success: bool
    message: str
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    errors: int = 0
    output: Optional[str] = None
    failed_tests: Optional[List[str]] = None
    duration: Optional[float] = None


async def run_tests(
    paths: Optional[List[str]] = None,
    pattern: Optional[str] = None,
    verbose: bool = True,
    timeout: int = 300,
    collect_only: bool = False,
) -> TestResult:
    """
    テストを実行

    Args:
        paths: テスト対象パス（省略時はtests/）
        pattern: テストパターン（-k オプション）
        verbose: 詳細出力
        timeout: タイムアウト秒数
        collect_only: テスト収集のみ（実行しない）

    Returns:
        TestResult: テスト結果
    """
    try:
        cmd = ["python", "-m", "pytest"]

        if verbose:
            cmd.append("-v")

        cmd.append("--tb=short")

        if pattern:
            cmd.extend(["-k", pattern])

        if collect_only:
            cmd.append("--collect-only")

        if paths:
            cmd.extend(paths)
        else:
            cmd.append("tests/")

        logger.info(f"Running tests: {' '.join(cmd)}")

        import time
        start_time = time.time()

        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )

        duration = time.time() - start_time
        output = result.stdout + result.stderr

        # 結果をパース
        passed, failed, skipped, errors = _parse_test_output(output)

        failed_tests = []
        if failed > 0:
            for line in output.split("\n"):
                if "FAILED" in line:
                    failed_tests.append(line.strip())

        if result.returncode == 0:
            return TestResult(
                success=True,
                message=f"テスト成功: {passed} passed, {skipped} skipped",
                passed=passed,
                failed=failed,
                skipped=skipped,
                errors=errors,
                output=output,
                duration=duration,
            )
        else:
            return TestResult(
                success=False,
                message=f"テスト失敗: {passed} passed, {failed} failed, {errors} errors",
                passed=passed,
                failed=failed,
                skipped=skipped,
                errors=errors,
                output=output,
                failed_tests=failed_tests,
                duration=duration,
            )

    except subprocess.TimeoutExpired:
        return TestResult(
            success=False,
            message=f"テストがタイムアウトしました（{timeout}秒）",
        )
    except Exception as e:
        logger.error(f"Test run error: {e}")
        return TestResult(
            success=False,
            message=f"テスト実行エラー: {str(e)}",
        )


async def run_specific_tests(
    test_file: str,
    test_function: Optional[str] = None,
    timeout: int = 60,
) -> TestResult:
    """
    特定のテストを実行

    Args:
        test_file: テストファイルパス
        test_function: テスト関数名（省略時はファイル全体）
        timeout: タイムアウト秒数

    Returns:
        TestResult: テスト結果
    """
    if test_function:
        paths = [f"{test_file}::{test_function}"]
    else:
        paths = [test_file]

    return await run_tests(paths=paths, timeout=timeout)


async def run_all_tests(timeout: int = 600) -> TestResult:
    """
    全テストを実行

    Args:
        timeout: タイムアウト秒数

    Returns:
        TestResult: テスト結果
    """
    return await run_tests(paths=None, timeout=timeout)


async def list_tests(path: Optional[str] = None) -> TestResult:
    """
    テスト一覧を取得

    Args:
        path: テストパス

    Returns:
        TestResult: テスト一覧
    """
    return await run_tests(
        paths=[path] if path else None,
        collect_only=True,
    )


def _parse_test_output(output: str) -> tuple:
    """
    pytest出力から結果を抽出

    Args:
        output: pytest出力

    Returns:
        (passed, failed, skipped, errors)
    """
    passed = 0
    failed = 0
    skipped = 0
    errors = 0

    import re

    # "X passed, Y failed, Z skipped" 形式をパース
    summary_match = re.search(
        r'(\d+) passed',
        output
    )
    if summary_match:
        passed = int(summary_match.group(1))

    failed_match = re.search(
        r'(\d+) failed',
        output
    )
    if failed_match:
        failed = int(failed_match.group(1))

    skipped_match = re.search(
        r'(\d+) skipped',
        output
    )
    if skipped_match:
        skipped = int(skipped_match.group(1))

    error_match = re.search(
        r'(\d+) error',
        output
    )
    if error_match:
        errors = int(error_match.group(1))

    return passed, failed, skipped, errors


async def check_test_coverage(path: Optional[str] = None) -> Dict[str, Any]:
    """
    テストカバレッジを確認

    Args:
        path: 対象パス

    Returns:
        カバレッジ情報
    """
    try:
        cmd = ["python", "-m", "pytest", "--cov=app", "--cov-report=term-missing"]

        if path:
            cmd.append(path)
        else:
            cmd.append("tests/")

        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=600,
            encoding="utf-8",
        )

        output = result.stdout + result.stderr

        return {
            "success": result.returncode == 0,
            "output": output,
        }

    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": "カバレッジ計測がタイムアウトしました",
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"カバレッジ計測エラー: {str(e)}",
        }
