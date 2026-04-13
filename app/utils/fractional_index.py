"""Fractional indexing for block ordering.

2つのキー間の中間キーを生成することで、並べ替え時のDB更新を1行に限定する。
base62 を使い、SQLのBINARY/UTF-8照合で辞書順ソートが正しく動作する。

参考: https://observablehq.com/@dgreensp/implementing-fractional-indexing
"""

from __future__ import annotations

BASE_62_DIGITS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
SMALLEST = BASE_62_DIGITS[0]   # '0'
LARGEST = BASE_62_DIGITS[-1]   # 'z'


def _validate(key: str) -> None:
    if not key:
        return
    for ch in key:
        if ch not in BASE_62_DIGITS:
            raise ValueError(f"invalid character in fractional index: {ch!r}")
    if key[-1] == SMALLEST:
        raise ValueError(f"fractional index must not end with smallest digit: {key!r}")


def _midpoint(a: str, b: str) -> str:
    """aとbの辞書順中間点を返す。a < b 前提。"""
    if b and a >= b:
        raise ValueError(f"a must be < b, got a={a!r} b={b!r}")

    n = 0
    while True:
        digit_a = a[n] if n < len(a) else SMALLEST
        digit_b = b[n] if b and n < len(b) else LARGEST
        if digit_a == digit_b:
            n += 1
            continue

        idx_a = BASE_62_DIGITS.index(digit_a)
        idx_b = BASE_62_DIGITS.index(digit_b)
        if idx_b - idx_a > 1:
            mid_idx = (idx_a + idx_b) // 2
            return a[:n] + BASE_62_DIGITS[mid_idx]

        # 差が1しかない: b側を基準にして新しい桁を追加
        if b and n + 1 < len(b):
            return a[:n] + digit_a + _midpoint(a[n + 1:] if n + 1 < len(a) else "", b[n + 1:])
        # a側を伸ばす
        n += 1
        if n >= len(a):
            # a を digit_b で拡張しながら中間を探す
            return a + _midpoint("", b[n:] if b and n < len(b) else "")


def key_between(a: str | None, b: str | None) -> str:
    """aとbの間の新しいキーを返す。

    a=None: bより小さい最初のキー
    b=None: aより大きい次のキー
    両方None: 中央値 ('V')
    """
    if a is not None:
        _validate(a)
    if b is not None:
        _validate(b)
    if a is not None and b is not None and a >= b:
        raise ValueError(f"a must be < b, got a={a!r} b={b!r}")

    if a is None and b is None:
        return "V"  # base62 の中央付近

    if a is None:
        # b より小さいキー
        assert b is not None
        first_digit = b[0]
        idx = BASE_62_DIGITS.index(first_digit)
        if idx > 0:
            # 先頭の桁を1つ小さくする
            return BASE_62_DIGITS[idx - 1] + "V" if len(b) == 1 else BASE_62_DIGITS[idx - 1]
        # b が '0...' で始まる: 桁を伸ばす
        return "0" + key_between(None, b[1:] if len(b) > 1 else None)

    if b is None:
        # a より大きいキー
        last_digit = a[-1]
        idx = BASE_62_DIGITS.index(last_digit)
        if idx < len(BASE_62_DIGITS) - 1:
            return a[:-1] + BASE_62_DIGITS[idx + 1]
        # 末尾が 'z': 桁を伸ばす
        return a + "V"

    return _midpoint(a, b)


def generate_n_keys_between(a: str | None, b: str | None, n: int) -> list[str]:
    """aとbの間にn個のキーを均等に生成する。"""
    if n <= 0:
        return []
    if n == 1:
        return [key_between(a, b)]

    mid = key_between(a, b)
    half = n // 2
    left = generate_n_keys_between(a, mid, half)
    right = generate_n_keys_between(mid, b, n - half - 1)
    return left + [mid] + right
