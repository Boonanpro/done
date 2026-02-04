"""
エラー分類体系

Executor側でエラーを分類し、tools.py/runner.pyはそれを忠実に伝搬する。
これにより、LLMに実際のエラー（タイムアウト、セレクタ不一致等）が伝わる。
"""

from enum import Enum


class ErrorType(str, Enum):
    """
    エラータイプの分類

    Executor は適切なエラータイプを設定することで、
    runner.py が正しい対応（認証要求 or エラー表示）を行える。
    """

    # 認証関連
    CREDENTIALS_REQUIRED = "credentials_required"  # 認証情報がない
    CREDENTIALS_INVALID = "credentials_invalid"    # 認証情報が不正
    SESSION_EXPIRED = "session_expired"            # セッション切れ

    # 操作関連
    SELECTOR_NOT_FOUND = "selector_not_found"      # 要素が見つからない
    PAGE_TIMEOUT = "page_timeout"                  # タイムアウト
    UNEXPECTED_PAGE = "unexpected_page"            # 予期しないページ

    # ビジネスロジック関連
    NOT_FOUND = "not_found"                        # 検索結果なし
    NOT_AVAILABLE = "not_available"                # 在庫切れ、満席

    # システム関連
    INTERNAL_ERROR = "internal_error"              # 内部エラー
    UNKNOWN = "unknown"                            # 不明


# 認証要求が必要なエラータイプ
REQUIRES_CREDENTIALS_ERROR_TYPES = {
    ErrorType.CREDENTIALS_REQUIRED,
    ErrorType.CREDENTIALS_INVALID,
    ErrorType.SESSION_EXPIRED,
}


def is_credentials_error(error_type: str | ErrorType | None) -> bool:
    """
    認証関連のエラーかどうかを判定

    Args:
        error_type: エラータイプ（文字列またはEnum）

    Returns:
        認証関連エラーの場合 True
    """
    if error_type is None:
        return False

    if isinstance(error_type, str):
        try:
            error_type = ErrorType(error_type)
        except ValueError:
            return False

    return error_type in REQUIRES_CREDENTIALS_ERROR_TYPES
