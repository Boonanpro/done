"""
EX予約（新幹線）Executor

SmartEXで新幹線を検索・予約する

モジュール構成:
- executor.py: メインExecutor
- models.py: データモデル（SearchParams, TrainInfo, etc.）
- constants.py: 定数定義
- errors.py: 例外クラス
- parser.py: HTMLパーサー
- search.py: 列車検索
- login.py: ログイン処理
- seat.py: 座席選択
- purchase.py: 購入処理
- cancel.py: キャンセル処理
"""

from app.executors.ex_reservation.executor import EXReservationExecutor
from app.executors.ex_reservation.models import (
    SearchParams,
    SearchResult,
    TrainInfo,
    BookingInfo,
    LoginResult,
    PurchaseResult,
    CancelResult,
)
from app.executors.ex_reservation.constants import (
    URLS,
    TIMEOUTS,
    STATION_CODES,
    ERROR_MESSAGES,
)
from app.executors.ex_reservation.errors import (
    EXReservationError,
    LoginError,
    CredentialsNotFoundError,
    OTPError,
    SearchError,
    SeatSelectionError,
    PurchaseError,
    CancelError,
)

__all__ = [
    # Executor
    "EXReservationExecutor",
    # Models
    "SearchParams",
    "SearchResult",
    "TrainInfo",
    "BookingInfo",
    "LoginResult",
    "PurchaseResult",
    "CancelResult",
    # Constants
    "URLS",
    "TIMEOUTS",
    "STATION_CODES",
    "ERROR_MESSAGES",
    # Errors
    "EXReservationError",
    "LoginError",
    "CredentialsNotFoundError",
    "OTPError",
    "SearchError",
    "SeatSelectionError",
    "PurchaseError",
    "CancelError",
]

