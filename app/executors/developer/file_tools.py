"""
File Tools - ファイル操作ユーティリティ

Phase 1: 読み取り専用
- read_file: ファイル読み取り
- list_files: ファイル一覧取得
- get_structure: ディレクトリ構造取得

Phase 2で追加予定:
- write_file: ファイル書き込み
- delete_file: ファイル削除
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# プロジェクトルート
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent


@dataclass
class FileResult:
    """ファイル操作結果"""
    success: bool
    message: str
    content: Optional[str] = None
    files: Optional[List[Dict[str, Any]]] = None
    structure: Optional[Dict[str, Any]] = None


def _is_safe_path(path: Path) -> bool:
    """
    パスが安全かどうかを検証

    - プロジェクトルート内であること
    - 機密ファイル（.env, credentials等）でないこと
    """
    try:
        resolved = path.resolve()
        project_resolved = PROJECT_ROOT.resolve()

        # プロジェクトルート内かチェック
        if not str(resolved).startswith(str(project_resolved)):
            logger.warning(f"Path outside project root: {path}")
            return False

        # 機密ファイルをブロック
        sensitive_patterns = [
            ".env",
            "credentials",
            "secrets",
            ".git/config",
            "id_rsa",
            "id_ed25519",
        ]

        path_str = str(resolved).lower()
        for pattern in sensitive_patterns:
            if pattern in path_str:
                logger.warning(f"Sensitive file blocked: {path}")
                return False

        return True
    except Exception as e:
        logger.error(f"Path validation error: {e}")
        return False


def _resolve_path(path_str: str) -> Path:
    """
    パス文字列をPathオブジェクトに変換

    - 相対パスはプロジェクトルートからの相対
    - 絶対パスはそのまま使用
    """
    path = Path(path_str)

    if path.is_absolute():
        return path

    return PROJECT_ROOT / path


async def read_file(path: str, encoding: str = "utf-8") -> FileResult:
    """
    ファイルを読み取る

    Args:
        path: ファイルパス（相対パスはプロジェクトルートから）
        encoding: 文字エンコーディング

    Returns:
        FileResult: 読み取り結果
    """
    try:
        file_path = _resolve_path(path)

        if not _is_safe_path(file_path):
            return FileResult(
                success=False,
                message=f"アクセスが許可されていないパスです: {path}",
            )

        if not file_path.exists():
            return FileResult(
                success=False,
                message=f"ファイルが見つかりません: {path}",
            )

        if not file_path.is_file():
            return FileResult(
                success=False,
                message=f"ディレクトリです。ファイルを指定してください: {path}",
            )

        # ファイルサイズチェック（1MB以上は警告）
        size = file_path.stat().st_size
        if size > 1024 * 1024:
            logger.warning(f"Large file: {path} ({size} bytes)")

        content = file_path.read_text(encoding=encoding)

        logger.info(f"File read: {path} ({len(content)} chars)")

        return FileResult(
            success=True,
            message=f"ファイルを読み取りました: {path}",
            content=content,
        )

    except UnicodeDecodeError:
        return FileResult(
            success=False,
            message=f"ファイルのエンコーディングエラー。バイナリファイルの可能性があります: {path}",
        )
    except Exception as e:
        logger.error(f"File read error: {e}")
        return FileResult(
            success=False,
            message=f"ファイル読み取りエラー: {str(e)}",
        )


async def list_files(
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
) -> FileResult:
    """
    ファイル一覧を取得

    Args:
        path: ディレクトリパス
        pattern: globパターン（例: "*.py", "SKILL.md"）
        recursive: サブディレクトリも検索するか

    Returns:
        FileResult: ファイル一覧
    """
    try:
        dir_path = _resolve_path(path)

        if not _is_safe_path(dir_path):
            return FileResult(
                success=False,
                message=f"アクセスが許可されていないパスです: {path}",
            )

        if not dir_path.exists():
            return FileResult(
                success=False,
                message=f"ディレクトリが見つかりません: {path}",
            )

        if not dir_path.is_dir():
            return FileResult(
                success=False,
                message=f"ファイルです。ディレクトリを指定してください: {path}",
            )

        # ファイル検索
        if recursive:
            matches = list(dir_path.rglob(pattern))
        else:
            matches = list(dir_path.glob(pattern))

        # 安全なパスのみフィルタ
        safe_matches = [p for p in matches if _is_safe_path(p)]

        files = []
        for p in safe_matches[:100]:  # 最大100件
            try:
                rel_path = p.relative_to(PROJECT_ROOT)
                files.append({
                    "path": str(rel_path),
                    "name": p.name,
                    "is_dir": p.is_dir(),
                    "size": p.stat().st_size if p.is_file() else None,
                })
            except Exception:
                continue

        logger.info(f"Listed {len(files)} files in {path}")

        return FileResult(
            success=True,
            message=f"{len(files)}件のファイルを取得しました",
            files=files,
        )

    except Exception as e:
        logger.error(f"List files error: {e}")
        return FileResult(
            success=False,
            message=f"ファイル一覧取得エラー: {str(e)}",
        )


async def get_structure(
    path: str = ".",
    max_depth: int = 3,
    include_files: bool = True,
) -> FileResult:
    """
    ディレクトリ構造を取得（ツリー形式）

    Args:
        path: ルートディレクトリ
        max_depth: 最大深度
        include_files: ファイルも含めるか（Falseならディレクトリのみ）

    Returns:
        FileResult: ディレクトリ構造
    """
    try:
        root_path = _resolve_path(path)

        if not _is_safe_path(root_path):
            return FileResult(
                success=False,
                message=f"アクセスが許可されていないパスです: {path}",
            )

        if not root_path.exists():
            return FileResult(
                success=False,
                message=f"ディレクトリが見つかりません: {path}",
            )

        def build_tree(current_path: Path, depth: int) -> Dict[str, Any]:
            """再帰的にツリーを構築"""
            if depth > max_depth:
                return {"name": current_path.name, "type": "dir", "truncated": True}

            result = {
                "name": current_path.name,
                "type": "dir" if current_path.is_dir() else "file",
            }

            if current_path.is_dir():
                children = []
                try:
                    for child in sorted(current_path.iterdir()):
                        # 隠しファイル・ディレクトリをスキップ
                        if child.name.startswith(".") and child.name not in [".claude"]:
                            continue

                        # 安全でないパスをスキップ
                        if not _is_safe_path(child):
                            continue

                        # __pycache__ などをスキップ
                        if child.name in ["__pycache__", "node_modules", ".git", "venv", ".venv"]:
                            continue

                        if child.is_dir():
                            children.append(build_tree(child, depth + 1))
                        elif include_files:
                            children.append({
                                "name": child.name,
                                "type": "file",
                                "size": child.stat().st_size,
                            })
                except PermissionError:
                    pass

                result["children"] = children

            return result

        structure = build_tree(root_path, 0)

        # ツリーをテキスト形式にも変換
        def format_tree(node: Dict, prefix: str = "", is_last: bool = True) -> List[str]:
            """ツリーを見やすいテキスト形式に変換"""
            lines = []

            connector = "└── " if is_last else "├── "
            lines.append(f"{prefix}{connector}{node['name']}")

            if "children" in node:
                children = node["children"]
                for i, child in enumerate(children):
                    is_child_last = i == len(children) - 1
                    new_prefix = prefix + ("    " if is_last else "│   ")
                    lines.extend(format_tree(child, new_prefix, is_child_last))

            return lines

        tree_text = "\n".join(format_tree(structure))

        logger.info(f"Structure generated for {path}")

        return FileResult(
            success=True,
            message=f"ディレクトリ構造を取得しました: {path}",
            content=tree_text,
            structure=structure,
        )

    except Exception as e:
        logger.error(f"Get structure error: {e}")
        return FileResult(
            success=False,
            message=f"ディレクトリ構造取得エラー: {str(e)}",
        )


# ===========================================
# Phase 2: 書き込み機能
# ===========================================

async def write_file(
    path: str,
    content: str,
    encoding: str = "utf-8",
    create_dirs: bool = True,
) -> FileResult:
    """
    ファイルを書き込む

    Args:
        path: ファイルパス（相対パスはプロジェクトルートから）
        content: 書き込む内容
        encoding: 文字エンコーディング
        create_dirs: 親ディレクトリを自動作成するか

    Returns:
        FileResult: 書き込み結果
    """
    try:
        file_path = _resolve_path(path)

        if not _is_safe_path(file_path):
            return FileResult(
                success=False,
                message=f"アクセスが許可されていないパスです: {path}",
            )

        # 親ディレクトリを作成
        if create_dirs:
            file_path.parent.mkdir(parents=True, exist_ok=True)
        elif not file_path.parent.exists():
            return FileResult(
                success=False,
                message=f"親ディレクトリが存在しません: {file_path.parent}",
            )

        # 既存ファイルの場合は元の内容を保存（ロールバック用）
        original_content = None
        if file_path.exists():
            try:
                original_content = file_path.read_text(encoding=encoding)
            except Exception:
                pass

        # ファイルを書き込み
        file_path.write_text(content, encoding=encoding)

        logger.info(f"File written: {path} ({len(content)} chars)")

        return FileResult(
            success=True,
            message=f"ファイルを書き込みました: {path}",
            content=original_content,  # 元の内容を返す（ロールバック用）
        )

    except PermissionError:
        return FileResult(
            success=False,
            message=f"書き込み権限がありません: {path}",
        )
    except Exception as e:
        logger.error(f"File write error: {e}")
        return FileResult(
            success=False,
            message=f"ファイル書き込みエラー: {str(e)}",
        )


async def delete_file(path: str) -> FileResult:
    """
    ファイルを削除

    Args:
        path: ファイルパス（相対パスはプロジェクトルートから）

    Returns:
        FileResult: 削除結果
    """
    try:
        file_path = _resolve_path(path)

        if not _is_safe_path(file_path):
            return FileResult(
                success=False,
                message=f"アクセスが許可されていないパスです: {path}",
            )

        if not file_path.exists():
            return FileResult(
                success=False,
                message=f"ファイルが見つかりません: {path}",
            )

        if file_path.is_dir():
            return FileResult(
                success=False,
                message=f"ディレクトリは削除できません。ファイルを指定してください: {path}",
            )

        # 元の内容を保存（ロールバック用）
        original_content = None
        try:
            original_content = file_path.read_text(encoding="utf-8")
        except Exception:
            pass

        # ファイルを削除
        file_path.unlink()

        logger.info(f"File deleted: {path}")

        return FileResult(
            success=True,
            message=f"ファイルを削除しました: {path}",
            content=original_content,  # 元の内容を返す（ロールバック用）
        )

    except PermissionError:
        return FileResult(
            success=False,
            message=f"削除権限がありません: {path}",
        )
    except Exception as e:
        logger.error(f"File delete error: {e}")
        return FileResult(
            success=False,
            message=f"ファイル削除エラー: {str(e)}",
        )


async def create_directory(path: str) -> FileResult:
    """
    ディレクトリを作成

    Args:
        path: ディレクトリパス

    Returns:
        FileResult: 作成結果
    """
    try:
        dir_path = _resolve_path(path)

        if not _is_safe_path(dir_path):
            return FileResult(
                success=False,
                message=f"アクセスが許可されていないパスです: {path}",
            )

        if dir_path.exists():
            if dir_path.is_dir():
                return FileResult(
                    success=True,
                    message=f"ディレクトリは既に存在します: {path}",
                )
            else:
                return FileResult(
                    success=False,
                    message=f"同名のファイルが存在します: {path}",
                )

        dir_path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Directory created: {path}")

        return FileResult(
            success=True,
            message=f"ディレクトリを作成しました: {path}",
        )

    except PermissionError:
        return FileResult(
            success=False,
            message=f"作成権限がありません: {path}",
        )
    except Exception as e:
        logger.error(f"Directory create error: {e}")
        return FileResult(
            success=False,
            message=f"ディレクトリ作成エラー: {str(e)}",
        )
