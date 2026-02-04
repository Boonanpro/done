"""
EX予約 データモデル

設計原則: 入力は寛容に、出力は厳格に（Postel's Law）
- from_dict(): 複数のパラメータ名を受け付ける
- 内部: 正規化されたデータで処理
- 出力: 明確な型で返す
"""

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)


@dataclass
class SearchParams:
    """
    検索パラメータ

    LLMからの入力を正規化して保持する。
    複数のパラメータ名（departure/departure_station等）を受け付ける。
    """
    departure: str
    arrival: str
    date: str  # YYYY-MM-DD形式
    time: Optional[str] = None  # HH:MM形式
    seat_position: str = "指定なし"  # 窓側A, 通路側C, 指定なし
    product_type: str = "regular"  # regular, green
    adult_count: int = 1
    # 座席表機能
    specific_seat: Optional[str] = None  # 特定席指定（例: "5号車3番A席"）
    prefer_adjacent_empty: bool = False  # 隣空席優先
    show_seat_map: bool = False  # 座席表表示

    @classmethod
    def from_dict(cls, params: Dict[str, Any]) -> "SearchParams":
        """
        辞書からSearchParamsを作成

        複数のパラメータ名を受け付ける（LLMの揺れに対応）
        """
        # 出発駅（複数の名前を受け付ける）
        departure = (
            params.get("departure") or
            params.get("departure_station") or
            params.get("from") or
            params.get("from_station")
        )
        if not departure:
            raise ValueError("出発駅が指定されていません（departure または departure_station）")

        # 到着駅
        arrival = (
            params.get("arrival") or
            params.get("arrival_station") or
            params.get("to") or
            params.get("to_station")
        )
        if not arrival:
            raise ValueError("到着駅が指定されていません（arrival または arrival_station）")

        # 日付
        date_raw = (
            params.get("date") or
            params.get("departure_date") or
            params.get("travel_date")
        )
        date = cls._normalize_date(date_raw)

        # 時刻
        time_raw = params.get("time") or params.get("departure_time")
        time = cls._normalize_time(time_raw) if time_raw else None

        # 座席位置
        seat_raw = params.get("seat_position") or params.get("seat") or "指定なし"
        seat_position = cls._normalize_seat_position(seat_raw)

        # 商品タイプ
        product_raw = params.get("product_type") or params.get("seat_type") or "regular"
        product_type = cls._normalize_product_type(product_raw)

        # 人数
        adult_count = int(params.get("adult_count") or params.get("passengers") or 1)

        # 座席表機能
        specific_seat = params.get("specific_seat")
        prefer_adjacent_empty = bool(params.get("prefer_adjacent_empty", False))
        show_seat_map = bool(params.get("show_seat_map", False))

        return cls(
            departure=departure,
            arrival=arrival,
            date=date,
            time=time,
            seat_position=seat_position,
            product_type=product_type,
            adult_count=adult_count,
            specific_seat=specific_seat,
            prefer_adjacent_empty=prefer_adjacent_empty,
            show_seat_map=show_seat_map,
        )

    @staticmethod
    def _normalize_date(date_raw: Optional[str]) -> str:
        """日付を正規化（YYYY-MM-DD形式に）"""
        if not date_raw:
            # デフォルトは明日
            tomorrow = datetime.now() + timedelta(days=1)
            return tomorrow.strftime("%Y-%m-%d")

        date_str = str(date_raw).lower().strip()

        # 相対日付
        if date_str in ("today", "今日"):
            return datetime.now().strftime("%Y-%m-%d")
        if date_str in ("tomorrow", "明日"):
            return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        # すでにYYYY-MM-DD形式
        if len(date_str) == 10 and date_str[4] == "-":
            return date_str

        # YYYYMMDD形式
        if len(date_str) == 8 and date_str.isdigit():
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        # そのまま返す（パースできない場合）
        return date_str

    @staticmethod
    def _normalize_time(time_raw: str) -> Optional[str]:
        """時刻を正規化（HH:MM形式に）"""
        if not time_raw:
            return None

        time_str = str(time_raw).strip()

        # すでにHH:MM形式
        if ":" in time_str:
            return time_str

        # "19時" や "1900" 形式
        if "時" in time_str:
            hour = time_str.split("時")[0]
            return f"{int(hour):02d}:00"

        if len(time_str) == 4 and time_str.isdigit():
            return f"{time_str[:2]}:{time_str[2:]}"

        return time_str

    @staticmethod
    def _normalize_seat_position(seat_raw: str) -> str:
        """座席位置を正規化"""
        seat_str = str(seat_raw).lower().strip()

        mapping = {
            # 窓側
            "窓側": "窓側A",
            "窓": "窓側A",
            "window": "窓側A",
            "窓側a": "窓側A",
            # 通路側
            "通路側": "通路側C",
            "通路": "通路側C",
            "aisle": "通路側C",
            "通路側c": "通路側C",
            # 指定なし
            "指定なし": "指定なし",
            "none": "指定なし",
            "any": "指定なし",
            "": "指定なし",
        }

        return mapping.get(seat_str, seat_raw)

    @staticmethod
    def _normalize_product_type(product_raw: str) -> str:
        """商品タイプを正規化"""
        product_str = str(product_raw).lower().strip()

        mapping = {
            "regular": "regular",
            "普通車": "regular",
            "普通": "regular",
            "指定席": "regular",
            "green": "green",
            "グリーン": "green",
            "グリーン車": "green",
        }

        return mapping.get(product_str, "regular")

    def to_form_params(self) -> Dict[str, Any]:
        """検索フォーム用のパラメータに変換"""
        # 時刻を分解
        hour = None
        minute = None
        if self.time and ":" in self.time:
            parts = self.time.split(":")
            hour = f"{int(parts[0])}時"
            minute_int = int(parts[1])
            minute_rounded = (minute_int // 5) * 5
            minute = f"{minute_rounded:02d}分"

        # 日付をYYYYMMDD形式に
        date_formatted = self.date.replace("-", "") if self.date else None

        return {
            "departure": self.departure,
            "arrival": self.arrival,
            "date": date_formatted,
            "hour": hour,
            "minute": minute,
            "adult_count": self.adult_count,
            "product_type": self.product_type,
            "seat_position": self.seat_position,
        }


@dataclass
class TrainInfo:
    """
    列車情報

    検索結果から取得した列車の情報。
    全ての必須フィールドを持つ。
    """
    index: int  # 候補のインデックス（0始まり）
    train_name: str  # のぞみ49号
    departure_time: str  # 19:02 or 19時02分
    arrival_time: str  # 21:30 or 21時30分（必須！）
    departure_station: str = ""
    arrival_station: str = ""
    available: bool = True
    price: Optional[int] = None

    def format_time(self, time_str: str) -> str:
        """時刻を統一形式に（HH:MM）"""
        if not time_str:
            return ""
        if "時" in time_str and "分" in time_str:
            # 19時02分 → 19:02
            h = time_str.split("時")[0]
            m = time_str.split("時")[1].replace("分", "")
            return f"{int(h):02d}:{int(m):02d}"
        return time_str

    @property
    def departure_time_formatted(self) -> str:
        return self.format_time(self.departure_time)

    @property
    def arrival_time_formatted(self) -> str:
        return self.format_time(self.arrival_time)


@dataclass
class SearchResult:
    """検索結果"""
    success: bool
    message: str
    trains: List[TrainInfo] = field(default_factory=list)
    screenshot_path: Optional[str] = None

    @property
    def options(self) -> List[TrainInfo]:
        """後方互換性のためのエイリアス"""
        return self.trains


@dataclass
class BookingInfo:
    """
    予約情報

    確認画面から取得した予約の詳細情報。
    """
    train_name: str
    departure_time: str
    arrival_time: str
    departure_station: str
    arrival_station: str
    date: str
    seat_info: str  # 3号車12A
    price: int
    reservation_number: Optional[str] = None
    screenshot_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "train_name": self.train_name,
            "departure_time": self.departure_time,
            "arrival_time": self.arrival_time,
            "departure_station": self.departure_station,
            "arrival_station": self.arrival_station,
            "date": self.date,
            "seat_info": self.seat_info,
            "price": self.price,
            "reservation_number": self.reservation_number,
            "screenshot_path": self.screenshot_path,
        }


@dataclass
class LoginResult:
    """ログイン結果"""
    success: bool
    message: str = ""
    requires_otp: bool = False
    screenshot_path: Optional[str] = None


@dataclass
class PurchaseResult:
    """購入結果"""
    success: bool
    message: str = ""
    reservation_number: Optional[str] = None
    screenshot_path: Optional[str] = None


@dataclass
class CancelResult:
    """キャンセル結果"""
    success: bool
    message: str = ""
    refund_amount: Optional[int] = None
    refund_fee: Optional[int] = None
    screenshot_path: Optional[str] = None


@dataclass
class BrowserState:
    """
    ブラウザの実際の状態

    第一原理: ブラウザの実際の状態が唯一の真実。
    LLMの推測ではなく、実際のページ状態を報告する。
    """
    url: str = ""
    page_type: str = ""  # "login", "search", "seat_map", "confirmation", "error"
    logged_in: bool = False
    current_car: Optional[int] = None  # 座席表表示時の号車
    error_message: Optional[str] = None  # ページ上のエラーメッセージ
    screenshot_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "page_type": self.page_type,
            "logged_in": self.logged_in,
            "current_car": self.current_car,
            "error_message": self.error_message,
            "screenshot_path": self.screenshot_path,
        }


@dataclass
class RequestedConditions:
    """
    ユーザーがリクエストした条件

    ツール結果で「何をリクエストされたか」を明示する。
    """
    seat_type: Optional[str] = None  # "2列席窓側", "3列席窓側", etc.
    seat_position: Optional[str] = None  # "窓側A", "通路側C", etc.
    adjacent_empty: bool = False  # 隣空席希望
    specific_seat: Optional[str] = None  # "5号車3番E席"
    car_number: Optional[int] = None  # 号車指定

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seat_type": self.seat_type,
            "seat_position": self.seat_position,
            "adjacent_empty": self.adjacent_empty,
            "specific_seat": self.specific_seat,
            "car_number": self.car_number,
        }

    def describe(self) -> str:
        """条件を日本語で説明"""
        parts = []
        if self.seat_type:
            parts.append(self.seat_type)
        if self.seat_position:
            parts.append(self.seat_position)
        if self.adjacent_empty:
            parts.append("隣空席希望")
        if self.specific_seat:
            parts.append(f"指定席: {self.specific_seat}")
        if self.car_number:
            parts.append(f"{self.car_number}号車")
        return "、".join(parts) if parts else "指定なし"


@dataclass
class ActualResult:
    """
    実際に選択された結果

    ツール結果で「何を実行したか」を明示する。
    """
    seat: Optional[str] = None  # "4号車2番A席"
    seat_type: Optional[str] = None  # "3列席窓側"
    car_number: Optional[int] = None
    adjacent_empty: bool = False  # 隣が空いているか
    row: Optional[int] = None
    letter: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "seat": self.seat,
            "seat_type": self.seat_type,
            "car_number": self.car_number,
            "adjacent_empty": self.adjacent_empty,
            "row": self.row,
            "letter": self.letter,
        }

    def describe(self) -> str:
        """結果を日本語で説明"""
        parts = []
        if self.seat:
            parts.append(self.seat)
        if self.seat_type:
            parts.append(f"（{self.seat_type}）")
        if self.adjacent_empty:
            parts.append("隣も空席")
        return "".join(parts) if parts else "未選択"


@dataclass
class SeatDeviation:
    """
    リクエストと結果の差分

    第一原理: 差分があれば必ず報告する。
    ユーザーが何を要求し、何が返されたかを明確にする。
    """
    has_deviation: bool = False
    requested: Optional[RequestedConditions] = None
    actual: Optional[ActualResult] = None
    reason: Optional[str] = None  # 差分が生じた理由
    alternatives_checked: List[str] = field(default_factory=list)  # 確認した代替案

    def to_dict(self) -> Dict[str, Any]:
        return {
            "has_deviation": self.has_deviation,
            "requested": self.requested.to_dict() if self.requested else None,
            "actual": self.actual.to_dict() if self.actual else None,
            "reason": self.reason,
            "alternatives_checked": self.alternatives_checked,
        }

    def describe(self) -> str:
        """差分を日本語で説明"""
        if not self.has_deviation:
            return "要件通り"

        parts = []
        if self.requested:
            parts.append(f"要求: {self.requested.describe()}")
        if self.actual:
            parts.append(f"実際: {self.actual.describe()}")
        if self.reason:
            parts.append(f"理由: {self.reason}")
        if self.alternatives_checked:
            parts.append(f"確認済み: {', '.join(self.alternatives_checked)}")
        return " → ".join(parts)
