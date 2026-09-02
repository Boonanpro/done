"""電管ナレッジの収集で使う、日本語サイト向けの文字コード判定。

収集先には charset を返さない古い個人サイトがある（例: 佐近電気の koatukitei 配下）。
その場合 requests は本文を ISO-8859-1 と仮定し、apparent_encoding も日本語を
Windows-1254 と誤判定するため、タイトルも本文も丸ごと文字化けする。
文字化けした本文はそのまま知識ベースへ入り、AI回答の出典表示にも出てしまう。

そこで HTTP ヘッダ → HTML の meta charset → 推定 の順で候補を並べ、
厳密デコードが通る最初の候補を採用する。
"""

from __future__ import annotations

import re

_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+?charset\s*=\s*["']?\s*([A-Za-z0-9_\-]+)""", re.I
)
_HEADER_CHARSET_RE = re.compile(r"charset\s*=\s*([A-Za-z0-9_\-]+)", re.I)
# 日本語サイトで誤判定されやすい欧文コードページ。候補として信用しない。
_UNTRUSTED = {"iso-8859-1", "windows-1252", "windows-1254", "iso-8859-9", "ascii"}


def encoding_candidates(resp) -> list[str]:
    candidates: list[str] = []
    header = _HEADER_CHARSET_RE.search(resp.headers.get("Content-Type", "") or "")
    if header and header.group(1).lower() not in _UNTRUSTED:
        candidates.append(header.group(1))
    meta = _META_CHARSET_RE.search(resp.content[:8192])
    if meta:
        enc = meta.group(1).decode("ascii", "ignore")
        if enc and enc.lower() not in _UNTRUSTED:
            candidates.append(enc)
    apparent = resp.apparent_encoding
    if apparent and apparent.lower() not in _UNTRUSTED:
        candidates.append(apparent)
    candidates += ["utf-8", "cp932", "euc-jp"]
    seen: set[str] = set()
    ordered: list[str] = []
    for enc in candidates:
        key = enc.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(enc)
    return ordered


def resolve_encoding(resp) -> str:
    """レスポンスを読むべき文字コード名を返す。"""
    raw = resp.content
    if not raw:
        return "utf-8"
    candidates = encoding_candidates(resp)
    # MacRoman や Latin-1 はどんなバイト列でも「読めて」しまうため、
    # 厳密デコードが通っただけでは正解と判断できない。日本語として
    # 成立しているかまで見て、化けている候補は捨てる。
    first_ok: str | None = None
    for enc in candidates:
        try:
            text = raw.decode(enc, errors="strict")
        except (UnicodeDecodeError, LookupError):
            continue
        if first_ok is None:
            first_ok = enc
        if not looks_mojibake(text, whole=True):
            return enc
    if first_ok:
        return first_ok
    # どれも厳密には通らない時は、化けが最も少ないものを選ぶ。
    best, best_score = "utf-8", -1.0
    for enc in candidates:
        try:
            text = raw.decode(enc, errors="replace")
        except LookupError:
            continue
        score = 1.0 - text.count("�") / max(1, len(text))
        if score > best_score:
            best, best_score = enc, score
    return best


def decode_html(resp) -> str:
    """レスポンスを正しい文字コードで文字列にする。"""
    if not resp.content:
        return ""
    return resp.content.decode(resolve_encoding(resp), errors="replace")


_JP = re.compile(r"[぀-ヿ一-鿿]")
# 日本語を欧文コードページで読むと大量に出る文字。
# 「°」「×」など日本語文中にも出る記号を含むので、必ず日本語の量と比べて判定する。
_LATIN_EXT = re.compile(r"[À-ɏ‘-‟�]")


def looks_mojibake(text: str, *, whole: bool = False) -> bool:
    """文字化けした状態の文字列かどうか。

    ``whole=True`` は HTML 全体を見る用（先頭はタグばかりで判定できないため）。
    """
    sample = (text or "") if whole else (text or "")[:600]
    if len(sample) < 20:
        return False
    ext = len(_LATIN_EXT.findall(sample))
    return ext >= (20 if whole else 10) and ext > len(_JP.findall(sample))
