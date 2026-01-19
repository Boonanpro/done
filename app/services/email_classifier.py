"""
Email Classifier - メール内容の分類と情報抽出

設計原則:
- 現在: OTP抽出に使用
- 将来: 請求書検知、通知分類などに拡張可能

使用例:
    classifier = EmailClassifier()

    # OTP抽出
    otp = classifier.extract_otp(email_content)

    # 将来: メールタイプの分類
    email_type = classifier.classify(email_content)
    if email_type == EmailType.BILL:
        bill_info = classifier.extract_bill(email_content)
"""

import re
import logging
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class EmailType(str, Enum):
    """メールの種類"""
    OTP = "otp"                    # ワンタイムパスワード
    BILL = "bill"                  # 請求書
    SHIPPING = "shipping"          # 配送通知
    RESERVATION = "reservation"    # 予約確認
    NOTIFICATION = "notification"  # 一般通知
    UNKNOWN = "unknown"            # 不明


@dataclass
class OTPInfo:
    """OTP情報"""
    code: str
    source_service: Optional[str] = None  # ex_reservation, amazon, etc.


@dataclass
class BillInfo:
    """請求書情報（将来用）"""
    amount: Optional[int] = None
    due_date: Optional[str] = None
    payee: Optional[str] = None
    description: Optional[str] = None


# =============================================================================
# OTP抽出パターン
# =============================================================================

OTP_PATTERNS = [
    # 明示的なラベル付きパターン（3DS/SafeKey対応含む）
    r'(?:認証コード|確認コード|ワンタイムパスワード|OTP|verification code|security code|passcode|セキュリティコード|SafeKey)[：:\s]*[「\[]?(\d{4,8})[」\]]?',
    r'(?:コード|code)[：:\s]*[「\[]?(\d{4,8})[」\]]?',
    # 「コードは」「code is」パターン
    r'(?:コードは|code is)[：:\s]*[「\[]?(\d{4,8})[」\]]?',
    # AmEx SafeKey形式: "is 123456" or ": 123456"
    r'(?:is|：|:)\s*(\d{6})\b',
    # 独立した6桁の数字（最も一般的）
    r'(?<!\d)(\d{6})(?!\d)',
]

# OTPを送信するサービスのドメイン
OTP_SENDER_DOMAINS = {
    "amazon": ["amazon.co.jp", "amazon.com", "amazon.jp"],
    "ex_reservation": ["expy.jp", "jr-central.co.jp", "smartex.jp"],
    "rakuten": ["rakuten.co.jp", "rakuten.jp"],
    "3ds": ["americanexpress", "safekey", "visa", "mastercard", "jcb"],
    "google": ["google.com", "google.co.jp"],
    "line": ["line.me", "line.biz"],
}


# =============================================================================
# 請求書検知パターン（将来用）
# =============================================================================

BILL_PATTERNS = {
    "amount": [
        r'(?:ご請求金額|請求額|お支払い金額|合計)[：:\s]*[￥¥]?([0-9,]+)円?',
        r'[￥¥]([0-9,]+)',
    ],
    "due_date": [
        r'(?:お支払い期限|支払期限|振込期限)[：:\s]*(\d{4}[年/.-]\d{1,2}[月/.-]\d{1,2}日?)',
    ],
}

BILL_KEYWORDS = [
    "ご請求", "請求書", "お支払い", "振込", "口座引落",
    "クレジットカード", "Invoice", "Payment Due",
]


# =============================================================================
# メール分類器
# =============================================================================

class EmailClassifier:
    """
    メール内容の分類と情報抽出

    現在はOTP抽出のみ実装。将来、請求書や通知の検知を追加予定。
    """

    def classify(self, content: str, subject: str = "", sender: str = "") -> EmailType:
        """
        メールの種類を分類

        Args:
            content: メール本文
            subject: 件名
            sender: 送信元

        Returns:
            EmailType
        """
        full_text = f"{subject}\n{content}".lower()

        # OTPチェック（最優先）
        if self.extract_otp(content):
            return EmailType.OTP

        # 請求書チェック
        if self._is_bill(full_text):
            return EmailType.BILL

        # 配送通知チェック
        if self._is_shipping(full_text):
            return EmailType.SHIPPING

        # 予約確認チェック
        if self._is_reservation(full_text):
            return EmailType.RESERVATION

        return EmailType.UNKNOWN

    def extract_otp(self, content: str) -> Optional[OTPInfo]:
        """
        テキストからOTPを抽出

        Args:
            content: 解析対象のテキスト

        Returns:
            OTPInfo or None
        """
        if not content:
            return None

        for pattern in OTP_PATTERNS:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                code = match.group(1)
                # 4〜8桁の数字であることを確認
                if code.isdigit() and 4 <= len(code) <= 8:
                    logger.debug(f"OTP extracted: {code[:2]}****")
                    return OTPInfo(code=code)

        return None

    def extract_bill(self, content: str) -> Optional[BillInfo]:
        """
        テキストから請求書情報を抽出（将来用）

        Args:
            content: 解析対象のテキスト

        Returns:
            BillInfo or None
        """
        # TODO: 将来実装
        if not content:
            return None

        amount = None
        due_date = None

        # 金額抽出
        for pattern in BILL_PATTERNS["amount"]:
            match = re.search(pattern, content)
            if match:
                amount_str = match.group(1).replace(",", "")
                amount = int(amount_str)
                break

        # 期限抽出
        for pattern in BILL_PATTERNS["due_date"]:
            match = re.search(pattern, content)
            if match:
                due_date = match.group(1)
                break

        if amount or due_date:
            return BillInfo(amount=amount, due_date=due_date)

        return None

    def identify_service(self, sender: str, content: str) -> Optional[str]:
        """
        送信元とコンテンツからサービスを特定

        Args:
            sender: 送信元アドレス
            content: メール本文

        Returns:
            サービス名 or None
        """
        sender_lower = sender.lower() if sender else ""
        content_lower = content.lower() if content else ""

        for service, domains in OTP_SENDER_DOMAINS.items():
            for domain in domains:
                if domain in sender_lower or domain in content_lower:
                    return service

        return None

    def _is_bill(self, text: str) -> bool:
        """請求書かどうか判定"""
        return any(keyword.lower() in text for keyword in BILL_KEYWORDS)

    def _is_shipping(self, text: str) -> bool:
        """配送通知かどうか判定"""
        shipping_keywords = ["配送", "お届け", "発送", "tracking", "shipped"]
        return any(keyword in text for keyword in shipping_keywords)

    def _is_reservation(self, text: str) -> bool:
        """予約確認かどうか判定"""
        reservation_keywords = ["予約確認", "ご予約", "reservation", "booking"]
        return any(keyword in text for keyword in reservation_keywords)


# シングルトン
_classifier: Optional[EmailClassifier] = None


def get_email_classifier() -> EmailClassifier:
    """EmailClassifierのインスタンスを取得"""
    global _classifier
    if _classifier is None:
        _classifier = EmailClassifier()
    return _classifier
