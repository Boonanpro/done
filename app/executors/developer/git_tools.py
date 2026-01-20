"""
Git Tools - Git操作ユーティリティ

Phase 1: 読み取り専用
- git_status: 現在の状態を取得
- git_diff: 差分を取得
- git_log: コミット履歴を取得

Phase 2で追加予定:
- git_branch: ブランチ作成・切り替え
- git_commit: コミット
- git_revert: リバート
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
class GitResult:
    """Git操作結果"""
    success: bool
    message: str
    output: Optional[str] = None
    data: Optional[Dict[str, Any]] = None


def _run_git_command(
    args: List[str],
    cwd: Optional[Path] = None,
    timeout: int = 30,
) -> GitResult:
    """
    Gitコマンドを実行

    Args:
        args: コマンド引数（例: ["status", "--porcelain"]）
        cwd: 作業ディレクトリ
        timeout: タイムアウト秒数

    Returns:
        GitResult: 実行結果
    """
    try:
        cmd = ["git"] + args
        logger.debug(f"Running: {' '.join(cmd)}")

        result = subprocess.run(
            cmd,
            cwd=cwd or PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() or result.stdout.strip()
            logger.warning(f"Git command failed: {error_msg}")
            return GitResult(
                success=False,
                message=f"Gitコマンドエラー: {error_msg}",
                output=error_msg,
            )

        return GitResult(
            success=True,
            message="成功",
            output=result.stdout.strip(),
        )

    except subprocess.TimeoutExpired:
        logger.error(f"Git command timeout: {args}")
        return GitResult(
            success=False,
            message="Gitコマンドがタイムアウトしました",
        )
    except FileNotFoundError:
        return GitResult(
            success=False,
            message="Gitがインストールされていないか、PATHに含まれていません",
        )
    except Exception as e:
        logger.error(f"Git command error: {e}")
        return GitResult(
            success=False,
            message=f"Gitコマンドエラー: {str(e)}",
        )


async def git_status() -> GitResult:
    """
    現在のGit状態を取得

    Returns:
        GitResult: ステータス情報
            - output: git status の出力
            - data: パース済みの状態情報
    """
    # 通常のステータス
    result = _run_git_command(["status"])
    if not result.success:
        return result

    # ポーセリンフォーマットで詳細取得
    porcelain_result = _run_git_command(["status", "--porcelain"])

    # ブランチ名取得
    branch_result = _run_git_command(["branch", "--show-current"])

    # データを構造化
    changes = []
    if porcelain_result.success and porcelain_result.output:
        for line in porcelain_result.output.split("\n"):
            if line:
                status_code = line[:2]
                file_path = line[3:]

                status_map = {
                    "M ": "modified (staged)",
                    " M": "modified (unstaged)",
                    "MM": "modified (staged + unstaged)",
                    "A ": "added (staged)",
                    " A": "added (unstaged)",
                    "D ": "deleted (staged)",
                    " D": "deleted (unstaged)",
                    "R ": "renamed",
                    "C ": "copied",
                    "??": "untracked",
                    "!!": "ignored",
                }

                changes.append({
                    "status": status_map.get(status_code, status_code),
                    "status_code": status_code,
                    "path": file_path,
                })

    data = {
        "branch": branch_result.output if branch_result.success else "unknown",
        "changes": changes,
        "has_changes": len(changes) > 0,
        "staged_count": sum(1 for c in changes if "staged" in c["status"] and "unstaged" not in c["status"]),
        "unstaged_count": sum(1 for c in changes if "unstaged" in c["status"]),
        "untracked_count": sum(1 for c in changes if c["status"] == "untracked"),
    }

    logger.info(f"Git status: {data['branch']}, {len(changes)} changes")

    return GitResult(
        success=True,
        message=f"ブランチ: {data['branch']}, 変更: {len(changes)}件",
        output=result.output,
        data=data,
    )


async def git_diff(
    staged: bool = False,
    path: Optional[str] = None,
    stat_only: bool = False,
) -> GitResult:
    """
    差分を取得

    Args:
        staged: ステージング済みの差分を表示するか
        path: 特定のファイル/ディレクトリの差分のみ
        stat_only: 統計情報のみ（変更行数）

    Returns:
        GitResult: 差分情報
    """
    args = ["diff"]

    if staged:
        args.append("--staged")

    if stat_only:
        args.append("--stat")

    if path:
        args.append("--")
        args.append(path)

    result = _run_git_command(args)

    if result.success:
        lines = result.output.split("\n") if result.output else []
        result.data = {
            "line_count": len(lines),
            "is_empty": len(result.output or "") == 0,
        }

        if result.data["is_empty"]:
            result.message = "差分はありません"
        else:
            result.message = f"差分: {len(lines)}行"

    logger.info(f"Git diff: staged={staged}, path={path}")

    return result


async def git_log(
    count: int = 10,
    oneline: bool = True,
    path: Optional[str] = None,
) -> GitResult:
    """
    コミット履歴を取得

    Args:
        count: 取得するコミット数
        oneline: 1行形式で表示
        path: 特定のファイル/ディレクトリの履歴のみ

    Returns:
        GitResult: コミット履歴
    """
    args = ["log", f"-{count}"]

    if oneline:
        args.append("--oneline")
    else:
        args.extend(["--format=%H%n%an%n%ae%n%at%n%s%n%b%n---COMMIT---"])

    if path:
        args.append("--")
        args.append(path)

    result = _run_git_command(args)

    if result.success and not oneline and result.output:
        # 詳細形式のパース
        commits = []
        for commit_block in result.output.split("---COMMIT---"):
            lines = commit_block.strip().split("\n")
            if len(lines) >= 5:
                commits.append({
                    "hash": lines[0],
                    "author_name": lines[1],
                    "author_email": lines[2],
                    "timestamp": lines[3],
                    "subject": lines[4],
                    "body": "\n".join(lines[5:]).strip(),
                })
        result.data = {"commits": commits}

    logger.info(f"Git log: count={count}")

    return result


async def git_show(commit: str = "HEAD", path: Optional[str] = None) -> GitResult:
    """
    特定のコミットの詳細を表示

    Args:
        commit: コミットハッシュまたは参照（HEAD, main等）
        path: 特定のファイルの変更のみ

    Returns:
        GitResult: コミット詳細
    """
    args = ["show", commit]

    if path:
        args.append("--")
        args.append(path)

    result = _run_git_command(args)

    logger.info(f"Git show: {commit}")

    return result


async def git_blame(path: str, line_start: Optional[int] = None, line_end: Optional[int] = None) -> GitResult:
    """
    ファイルの各行の変更履歴を取得

    Args:
        path: ファイルパス
        line_start: 開始行
        line_end: 終了行

    Returns:
        GitResult: blame情報
    """
    args = ["blame"]

    if line_start and line_end:
        args.extend(["-L", f"{line_start},{line_end}"])

    args.append(path)

    result = _run_git_command(args)

    logger.info(f"Git blame: {path}")

    return result


# ===========================================
# Phase 2: 書き込み操作
# ===========================================

async def git_add(files: List[str]) -> GitResult:
    """
    ファイルをステージングに追加

    Args:
        files: ステージングするファイルのリスト

    Returns:
        GitResult: 結果
    """
    if not files:
        return GitResult(
            success=False,
            message="ステージングするファイルを指定してください",
        )

    args = ["add"] + files

    result = _run_git_command(args)

    if result.success:
        result.message = f"{len(files)}件のファイルをステージングしました"
        result.data = {"staged_files": files}

    logger.info(f"Git add: {files}")

    return result


async def git_branch(
    name: Optional[str] = None,
    checkout: bool = False,
    delete: bool = False,
) -> GitResult:
    """
    ブランチ操作

    Args:
        name: ブランチ名（省略時は一覧表示）
        checkout: 作成後にチェックアウトするか
        delete: ブランチを削除するか

    Returns:
        GitResult: 結果
    """
    if name is None:
        # ブランチ一覧
        result = _run_git_command(["branch", "-a"])
        if result.success:
            branches = [b.strip() for b in result.output.split("\n") if b.strip()]
            current = next((b[2:] for b in branches if b.startswith("* ")), None)
            result.data = {
                "branches": [b.lstrip("* ") for b in branches],
                "current": current,
            }
        return result

    if delete:
        # ブランチ削除
        result = _run_git_command(["branch", "-d", name])
        if result.success:
            result.message = f"ブランチ {name} を削除しました"
        return result

    if checkout:
        # ブランチ作成 + チェックアウト
        result = _run_git_command(["checkout", "-b", name])
        if result.success:
            result.message = f"ブランチ {name} を作成してチェックアウトしました"
            result.data = {"branch": name}
        return result
    else:
        # ブランチ作成のみ
        result = _run_git_command(["branch", name])
        if result.success:
            result.message = f"ブランチ {name} を作成しました"
            result.data = {"branch": name}
        return result


async def git_checkout(name: str) -> GitResult:
    """
    ブランチをチェックアウト

    Args:
        name: ブランチ名

    Returns:
        GitResult: 結果
    """
    result = _run_git_command(["checkout", name])

    if result.success:
        result.message = f"ブランチ {name} にチェックアウトしました"
        result.data = {"branch": name}

    logger.info(f"Git checkout: {name}")

    return result


async def git_commit(
    message: str,
    files: Optional[List[str]] = None,
    add_all: bool = False,
) -> GitResult:
    """
    コミット

    Args:
        message: コミットメッセージ
        files: コミットするファイル（省略時はステージング済みファイル）
        add_all: 全ての変更をステージングしてコミット

    Returns:
        GitResult: 結果
    """
    if not message:
        return GitResult(
            success=False,
            message="コミットメッセージを指定してください",
        )

    # ファイル指定がある場合は先にステージング
    if files:
        add_result = await git_add(files)
        if not add_result.success:
            return add_result

    # -a オプションで全変更をステージング
    if add_all:
        args = ["commit", "-a", "-m", message]
    else:
        args = ["commit", "-m", message]

    result = _run_git_command(args)

    if result.success:
        # コミットハッシュを取得
        hash_result = _run_git_command(["rev-parse", "HEAD"])
        commit_hash = hash_result.output[:7] if hash_result.success else "unknown"

        result.message = f"コミットしました: {commit_hash}"
        result.data = {"commit_hash": commit_hash, "message": message}

    logger.info(f"Git commit: {message[:50]}...")

    return result


async def git_revert(commit: str, no_commit: bool = False) -> GitResult:
    """
    コミットをリバート

    Args:
        commit: リバートするコミットハッシュ
        no_commit: コミットせずにステージングのみ

    Returns:
        GitResult: 結果
    """
    args = ["revert"]

    if no_commit:
        args.append("--no-commit")

    args.append(commit)

    result = _run_git_command(args)

    if result.success:
        result.message = f"コミット {commit} をリバートしました"
        result.data = {"reverted_commit": commit}

    logger.info(f"Git revert: {commit}")

    return result


async def git_reset(
    files: Optional[List[str]] = None,
    hard: bool = False,
    commit: str = "HEAD",
) -> GitResult:
    """
    変更をリセット

    Args:
        files: リセットするファイル（省略時は全てのステージング）
        hard: ハードリセット（作業ディレクトリも戻す）
        commit: リセット先のコミット

    Returns:
        GitResult: 結果
    """
    args = ["reset"]

    if hard:
        args.append("--hard")

    args.append(commit)

    if files:
        args.append("--")
        args.extend(files)

    result = _run_git_command(args)

    if result.success:
        if files:
            result.message = f"{len(files)}件のファイルをリセットしました"
        else:
            result.message = f"{commit} にリセットしました"

    logger.info(f"Git reset: hard={hard}, commit={commit}")

    return result


async def git_stash(
    action: str = "push",
    message: Optional[str] = None,
) -> GitResult:
    """
    変更をスタッシュ

    Args:
        action: "push" (スタッシュ), "pop" (復元), "list" (一覧)
        message: スタッシュメッセージ

    Returns:
        GitResult: 結果
    """
    args = ["stash"]

    if action == "push":
        args.append("push")
        if message:
            args.extend(["-m", message])
    elif action == "pop":
        args.append("pop")
    elif action == "list":
        args.append("list")
    else:
        return GitResult(
            success=False,
            message=f"不明なアクション: {action}（push, pop, list のいずれか）",
        )

    result = _run_git_command(args)

    logger.info(f"Git stash: {action}")

    return result
