"""
ソース信頼性スコアリング

URLとコンテンツからソースの信頼性を0-100でスコアリングする。

重み:
- ドメイン権威 35%: .gov/.edu/.ac.jp=90, 大手メディア=70, ブログ=40
- 鮮度 20%: 90日以内=100, 1年以内=85, 2年以内=70
- 専門性 25%: 学術/政府=+30, 技術文書=+20, 個人ブログ=-10
- 偏り 20%: センセーショナル語=-20, 学術的語=+20
"""

import re
import logging
from urllib.parse import urlparse
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ドメイン権威スコア（0-100）
HIGH_AUTHORITY_TLDS = {
    ".gov", ".edu", ".ac.jp", ".go.jp", ".lg.jp",
}

HIGH_AUTHORITY_DOMAINS = {
    # 日本政府・公的機関
    "mhlw.go.jp", "mlit.go.jp", "cao.go.jp", "stat.go.jp",
    "jma.go.jp", "nta.go.jp", "mof.go.jp",
    # 海外政府
    "whitehouse.gov", "cdc.gov", "nih.gov", "nasa.gov",
    # 学術
    "arxiv.org", "scholar.google.com", "pubmed.ncbi.nlm.nih.gov",
    "nature.com", "science.org",
}

MEDIA_DOMAINS = {
    # 日本メディア
    "nikkei.com", "nhk.or.jp", "asahi.com", "mainichi.jp",
    "yomiuri.co.jp", "sankei.com", "jiji.com", "kyodonews.jp",
    "reuters.com", "nikkei.co.jp", "toyokeizai.net", "diamond.jp",
    "itmedia.co.jp", "impress.co.jp", "gigazine.net",
    # 海外メディア
    "bbc.com", "bbc.co.uk", "cnn.com", "nytimes.com",
    "washingtonpost.com", "theguardian.com", "apnews.com",
    "bloomberg.com", "ft.com", "wsj.com",
}

TECH_DOMAINS = {
    "github.com", "stackoverflow.com", "developer.mozilla.org",
    "docs.python.org", "docs.microsoft.com", "cloud.google.com",
    "aws.amazon.com", "qiita.com", "zenn.dev",
}

BLOG_DOMAINS = {
    "ameblo.jp", "note.com", "hateblo.jp", "hatenablog.com",
    "livedoor.blog", "fc2.com", "blogspot.com", "wordpress.com",
    "medium.com",
}

# 偏り検出用キーワード
SENSATIONAL_WORDS_JA = [
    "衝撃", "驚愕", "ヤバい", "ヤバすぎ", "炎上", "暴露",
    "知らないと損", "まさかの", "激震", "緊急速報",
]

SENSATIONAL_WORDS_EN = [
    "shocking", "bombshell", "breaking", "devastating",
    "you won't believe", "mind-blowing", "insane",
]

ACADEMIC_WORDS_JA = [
    "研究", "論文", "調査結果", "統計", "分析",
    "エビデンス", "データ", "報告書",
]

ACADEMIC_WORDS_EN = [
    "study", "research", "analysis", "findings",
    "data", "evidence", "peer-reviewed", "methodology",
]


def _get_domain_authority(url: str) -> int:
    """ドメイン権威スコア (0-100)"""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        return 40

    # 高信頼TLD
    for tld in HIGH_AUTHORITY_TLDS:
        if hostname.endswith(tld):
            return 90

    # 高信頼ドメイン
    for domain in HIGH_AUTHORITY_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return 90

    # メディア
    for domain in MEDIA_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return 70

    # テック文書
    for domain in TECH_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return 65

    # ブログ
    for domain in BLOG_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            return 40

    # or.jp / co.jp は中程度
    if hostname.endswith(".or.jp") or hostname.endswith(".co.jp"):
        return 60

    # 不明なドメイン
    return 50


def _get_freshness_score(published_date: Optional[str]) -> int:
    """鮮度スコア (0-100)"""
    if not published_date:
        return 60  # 日付不明は中立

    try:
        # 様々な日付フォーマットをパース
        for fmt in [
            "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z",
        ]:
            try:
                dt = datetime.strptime(published_date[:19], fmt[:min(len(fmt), 19)])
                break
            except ValueError:
                continue
        else:
            return 60

        days_ago = (datetime.now() - dt).days
        if days_ago < 0:
            return 100  # 未来日付は最新扱い
        if days_ago <= 90:
            return 100
        if days_ago <= 365:
            return 85
        if days_ago <= 730:
            return 70
        if days_ago <= 1825:  # 5年
            return 50
        return 30

    except Exception:
        return 60


def _get_expertise_score(url: str, content: str) -> int:
    """専門性スコア (0-100)"""
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
    except Exception:
        hostname = ""

    score = 50  # ベース

    # ドメインベースの調整
    for tld in HIGH_AUTHORITY_TLDS:
        if hostname.endswith(tld):
            score += 30
            break

    for domain in TECH_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            score += 20
            break

    for domain in BLOG_DOMAINS:
        if hostname == domain or hostname.endswith("." + domain):
            score -= 10
            break

    # コンテンツベースの調整（学術用語の密度）
    content_lower = content.lower()
    academic_count = sum(1 for w in ACADEMIC_WORDS_EN if w in content_lower)
    academic_count += sum(1 for w in ACADEMIC_WORDS_JA if w in content)
    if academic_count >= 3:
        score += 15
    elif academic_count >= 1:
        score += 5

    return max(0, min(100, score))


def _get_bias_score(content: str) -> int:
    """偏りスコア (0-100, 高い=偏りが少ない)"""
    score = 70  # ベース

    content_lower = content.lower()

    # センセーショナル語のカウント
    sensational_count = sum(1 for w in SENSATIONAL_WORDS_EN if w in content_lower)
    sensational_count += sum(1 for w in SENSATIONAL_WORDS_JA if w in content)
    score -= sensational_count * 10

    # 学術的語のカウント
    academic_count = sum(1 for w in ACADEMIC_WORDS_EN if w in content_lower)
    academic_count += sum(1 for w in ACADEMIC_WORDS_JA if w in content)
    score += academic_count * 5

    return max(0, min(100, score))


def evaluate_source(
    url: str,
    content: str,
    published_date: Optional[str] = None,
) -> dict:
    """
    ソースの信頼性をスコアリング (0-100)

    重み:
    - ドメイン権威 35%
    - 鮮度 20%
    - 専門性 25%
    - 偏り 20%

    Returns:
        {
            "score": 75,
            "trust_level": "moderate",
            "details": {
                "domain_authority": 70,
                "freshness": 85,
                "expertise": 65,
                "bias": 70,
            }
        }
    """
    # 各スコアを計算
    domain_authority = _get_domain_authority(url)
    freshness = _get_freshness_score(published_date)
    # content が長すぎる場合は先頭2000文字で評価
    eval_content = content[:2000] if content else ""
    expertise = _get_expertise_score(url, eval_content)
    bias = _get_bias_score(eval_content)

    # 重み付き合計
    total = (
        domain_authority * 0.35
        + freshness * 0.20
        + expertise * 0.25
        + bias * 0.20
    )
    score = int(round(total))

    # 信頼レベル
    if score >= 80:
        trust_level = "high"
    elif score >= 60:
        trust_level = "moderate"
    elif score >= 40:
        trust_level = "low"
    else:
        trust_level = "very_low"

    return {
        "score": score,
        "trust_level": trust_level,
        "details": {
            "domain_authority": domain_authority,
            "freshness": freshness,
            "expertise": expertise,
            "bias": bias,
        },
    }
