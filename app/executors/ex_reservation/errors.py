"""
EX予約 例外クラス

明確なエラー分類により：
1. エラーの原因が分かりやすい
2. リトライ可能かどうかが判断できる
3. ユーザーへの適切なメッセージが生成できる
"""


class EXReservationError(Exception):
    """EX予約の基底例外クラス"""

    def __init__(self, message: str, recoverable: bool = False):
        super().__init__(message)
        self.message = message
        self.recoverable = recoverable  # リトライで回復可能か


class LoginError(EXReservationError):
    """ログイン関連のエラー"""
    pass


class CredentialsNotFoundError(LoginError):
    """認証情報が見つからない"""

    def __init__(self, service: str = "ex_reservation"):
        super().__init__(
            f"{service}の認証情報が見つかりません",
            recoverable=True  # ユーザーが入力すれば回復可能
        )


class InvalidCredentialsError(LoginError):
    """認証情報が無効"""

    def __init__(self):
        super().__init__(
            "会員IDまたはパスワードが正しくありません",
            recoverable=True
        )


class OTPError(EXReservationError):
    """OTP認証関連のエラー"""
    pass


class OTPTimeoutError(OTPError):
    """OTPがタイムアウト"""

    def __init__(self, timeout_seconds: int = 90):
        super().__init__(
            f"OTP認証が{timeout_seconds}秒以内に完了しませんでした",
            recoverable=True  # 再送信で回復可能
        )


class OTPInvalidError(OTPError):
    """OTPコードが無効"""

    def __init__(self):
        super().__init__(
            "入力されたOTPコードが正しくありません",
            recoverable=True
        )


class SearchError(EXReservationError):
    """検索関連のエラー"""
    pass


class StationNotFoundError(SearchError):
    """駅が見つからない"""

    def __init__(self, station_name: str):
        super().__init__(
            f"駅「{station_name}」は対応していません",
            recoverable=False
        )


class NoTrainsFoundError(SearchError):
    """列車が見つからない"""

    def __init__(self, departure: str, arrival: str, date: str):
        super().__init__(
            f"{date}の{departure}→{arrival}で列車が見つかりませんでした",
            recoverable=True  # 条件変更で回復可能
        )


class NoSeatsAvailableError(SearchError):
    """空席がない"""

    def __init__(self, train_name: str):
        super().__init__(
            f"{train_name}は満席です",
            recoverable=True  # 別の列車で回復可能
        )


class SeatSelectionError(EXReservationError):
    """座席選択関連のエラー"""
    pass


class RequestedSeatNotAvailableError(SeatSelectionError):
    """希望の座席が取れない"""

    def __init__(self, requested: str, alternative: str = None):
        message = f"希望の座席（{requested}）が取れませんでした"
        if alternative:
            message += f"。{alternative}は空いています"
        super().__init__(message, recoverable=True)


class PurchaseError(EXReservationError):
    """購入関連のエラー"""
    pass


class ThreeDSecureError(PurchaseError):
    """3Dセキュア認証のエラー"""

    def __init__(self, message: str = "3Dセキュア認証に失敗しました"):
        super().__init__(message, recoverable=True)


class PaymentError(PurchaseError):
    """決済エラー"""

    def __init__(self, message: str = "決済処理に失敗しました"):
        super().__init__(message, recoverable=False)


class CancelError(EXReservationError):
    """キャンセル関連のエラー"""
    pass


class ReservationNotFoundError(CancelError):
    """予約が見つからない"""

    def __init__(self, reservation_id: str):
        super().__init__(
            f"予約番号「{reservation_id}」が見つかりません",
            recoverable=False
        )


class CancelNotAllowedError(CancelError):
    """キャンセル不可"""

    def __init__(self, reason: str):
        super().__init__(
            f"この予約はキャンセルできません: {reason}",
            recoverable=False
        )


class PageError(EXReservationError):
    """ページ遷移・表示のエラー"""
    pass


class UnexpectedPageError(PageError):
    """予期しないページ"""

    def __init__(self, expected: str, actual: str = "不明"):
        super().__init__(
            f"予期しないページです。期待: {expected}、実際: {actual}",
            recoverable=True  # 再試行で回復可能な場合あり
        )


class TimeoutError(PageError):
    """タイムアウト"""

    def __init__(self, operation: str, timeout_seconds: int):
        super().__init__(
            f"{operation}が{timeout_seconds}秒以内に完了しませんでした",
            recoverable=True
        )
