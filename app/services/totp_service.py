"""
TOTP (RFC 6238) — 認証アプリの6桁コードをダン自身で生成する。

認証アプリ（Google Authenticator 等）は、どこかからコードを受け取っているのではなく
「シード（登録時に一度だけ表示される秘密）」と現在時刻から毎回コードを計算している。
シードさえ保管しておけば、スマホも SMS 転送も介さずにダンが同じコードを出せる。
SMS が届かない・転送が切れる・キャリアに止められる、という失敗が構造的に消える。

コード自体は 30 秒で使い捨てなので保管しない。保管するのはシードだけで、
これはパスワードと同格の永続的な秘密なので credentials テーブルに暗号化して置く。

外部ライブラリ（pyotp 等）は使わない。標準ライブラリだけで完結する。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import struct
import time
from typing import Any, Optional
from urllib.parse import parse_qs, unquote, urlparse

logger = logging.getLogger(__name__)

DEFAULT_DIGITS = 6
DEFAULT_PERIOD = 30
DEFAULT_ALGORITHM = "SHA1"

_ALGORITHMS = {
    "SHA1": hashlib.sha1,
    "SHA256": hashlib.sha256,
    "SHA512": hashlib.sha512,
}


class TOTPError(ValueError):
    """シードが不正・復元不能な場合に投げる（値そのものはメッセージに含めない）。"""


def normalize_secret(secret: str) -> str:
    """
    シードを base32 の標準形に整える。

    ユーザーやサイトは "abcd efgh ijkl" のように空白区切り・小文字・パディング無しで
    見せてくることが多い。そのまま base32 デコードすると失敗するので寄せる。
    """
    if not secret:
        raise TOTPError("シードが空です")
    cleaned = "".join(secret.split()).replace("-", "").upper()
    if not cleaned:
        raise TOTPError("シードが空です")
    # base32 は 8 文字単位。足りない分を padding で補う。
    remainder = len(cleaned) % 8
    if remainder:
        cleaned += "=" * (8 - remainder)
    return cleaned


def _decode_secret(secret: str) -> bytes:
    try:
        return base64.b32decode(normalize_secret(secret), casefold=True)
    except Exception as exc:  # 値は絶対にログに出さない
        raise TOTPError(
            "シードを base32 として解釈できません。認証アプリ登録画面の"
            "「キー」文字列（英数字の羅列）か otpauth:// URI をそのまま渡してください。"
        ) from exc


def parse_totp_uri(raw: str) -> dict[str, Any]:
    """
    登録画面から取れる文字列を解釈する。

    受け付ける形式:
      - otpauth://totp/Meta:me@example.com?secret=XXXX&issuer=Meta&digits=6&period=30
      - 素の base32 シード "XXXX YYYY ZZZZ"

    QR コードの中身は otpauth:// URI なので、QR を読めた場合はそのまま渡せる。
    """
    if not raw or not raw.strip():
        raise TOTPError("シードが空です")
    raw = raw.strip()

    if not raw.lower().startswith("otpauth://"):
        # 素のシード。妥当性だけ確認して返す。
        _decode_secret(raw)
        return {
            "secret": normalize_secret(raw),
            "digits": DEFAULT_DIGITS,
            "period": DEFAULT_PERIOD,
            "algorithm": DEFAULT_ALGORITHM,
            "issuer": None,
            "account": None,
        }

    parsed = urlparse(raw)
    if (parsed.netloc or "").lower() != "totp":
        # otpauth://hotp/... はカウンタ方式で時刻から計算できない
        raise TOTPError(
            "時刻ベース(TOTP)の URI ではありません。認証アプリ方式(TOTP)のものを渡してください。"
        )

    query = parse_qs(parsed.query)

    def _first(key: str) -> Optional[str]:
        values = query.get(key)
        return values[0] if values else None

    secret = _first("secret")
    if not secret:
        raise TOTPError("URI に secret が含まれていません")
    _decode_secret(secret)

    algorithm = (_first("algorithm") or DEFAULT_ALGORITHM).upper()
    if algorithm not in _ALGORITHMS:
        raise TOTPError(f"未対応のアルゴリズムです: {algorithm}")

    try:
        digits = int(_first("digits") or DEFAULT_DIGITS)
    except ValueError:
        digits = DEFAULT_DIGITS
    if digits not in (6, 7, 8):
        digits = DEFAULT_DIGITS

    try:
        period = int(_first("period") or DEFAULT_PERIOD)
    except ValueError:
        period = DEFAULT_PERIOD
    if period <= 0:
        period = DEFAULT_PERIOD

    # ラベルは "Issuer:account" 形式（URL エンコード済み）
    label = unquote((parsed.path or "").lstrip("/"))
    account = label.split(":", 1)[1].strip() if ":" in label else (label or None)

    return {
        "secret": normalize_secret(secret),
        "digits": digits,
        "period": period,
        "algorithm": algorithm,
        "issuer": _first("issuer") or (label.split(":", 1)[0] if ":" in label else None),
        "account": account,
    }


def generate_code(
    secret: str,
    digits: int = DEFAULT_DIGITS,
    period: int = DEFAULT_PERIOD,
    algorithm: str = DEFAULT_ALGORITHM,
    at: Optional[float] = None,
) -> str:
    """
    シードと現在時刻からコードを計算する（RFC 6238）。

    Args:
        secret: base32 のシード
        digits: 桁数（通常 6）
        period: 更新間隔の秒数（通常 30）
        algorithm: SHA1 / SHA256 / SHA512
        at: 計算に使う UNIX 時刻。省略時は現在時刻

    Returns:
        ゼロ埋めされた数字コード
    """
    key = _decode_secret(secret)
    digest = _ALGORITHMS.get((algorithm or DEFAULT_ALGORITHM).upper())
    if digest is None:
        raise TOTPError(f"未対応のアルゴリズムです: {algorithm}")
    if period <= 0:
        period = DEFAULT_PERIOD

    counter = int((time.time() if at is None else at) // period)
    mac = hmac.new(key, struct.pack(">Q", counter), digest).digest()

    # 動的切り出し: 末尾ニブルをオフセットにして 4 バイト取り出す
    offset = mac[-1] & 0x0F
    truncated = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** digits)).zfill(digits)


def seconds_remaining(period: int = DEFAULT_PERIOD, at: Optional[float] = None) -> int:
    """今のコードが切り替わるまでの残り秒数。入力途中で失効するのを避ける判断に使う。"""
    if period <= 0:
        period = DEFAULT_PERIOD
    now = time.time() if at is None else at
    return int(period - (now % period))


def generate_from_stored(stored: dict[str, Any]) -> dict[str, Any]:
    """
    保管済みの認証情報からコードを生成する。

    Args:
        stored: credentials_service が返す辞書（totp_secret 等を含む）

    Returns:
        {"code": "123456", "seconds_remaining": 17, "period": 30}
    """
    secret = (stored or {}).get("totp_secret")
    if not secret:
        raise TOTPError("この認証情報には認証アプリのシードが保管されていません")

    digits = int(stored.get("totp_digits") or DEFAULT_DIGITS)
    period = int(stored.get("totp_period") or DEFAULT_PERIOD)
    algorithm = stored.get("totp_algorithm") or DEFAULT_ALGORITHM

    return {
        "code": generate_code(secret, digits=digits, period=period, algorithm=algorithm),
        "seconds_remaining": seconds_remaining(period),
        "period": period,
    }
