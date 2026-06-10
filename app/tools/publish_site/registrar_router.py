"""レジストラのTLD振り分け。

Cloudflare Registrar は扱う TLD が限られる（.ai/.io/.co/.us/ccTLD等は非対象）。
Cloudflare が対応する TLD は Cloudflare（at-cost＋ゾーン自動作成）、それ以外は
Name.com（広いTLD・API登録可・**前払い残高不要でカード都度課金**）にルーティング。

`get_registrar_for(domain)` が (registrar_client, provider_name) を返す。
各クライアントは check_availability / register / get_registration_status /
update_nameservers の同一I/F を実装しているので、呼び出し側は provider を
意識せず使える。
"""
from __future__ import annotations

from typing import Any, Optional

from app.tools.publish_site.cloudflare_registrar import get_cloudflare_registrar
from app.tools.publish_site.namecom_registrar import get_namecom_registrar

# Cloudflare Registrar が対応する主要 TLD（保守的に列挙。ここに無い TLD は
# Porkbun に回す＝Porkbun はほぼ全 TLD を扱えるので取りこぼしが少ない）。
CLOUDFLARE_TLDS: frozenset[str] = frozenset({
    "com", "net", "org", "info", "biz", "app", "dev", "page", "blog",
    "shop", "store", "online", "site", "website", "space", "tech", "xyz",
    "club", "live", "life", "world", "today", "news", "media", "studio",
    "design", "agency", "company", "group", "solutions", "services",
    "email", "cloud", "digital", "network", "systems",
})


def tld_of(domain: str) -> str:
    """ドメインの最終ラベル（TLD）を小文字で返す。"""
    return domain.strip().lower().rstrip(".").rsplit(".", 1)[-1]


def provider_for(domain: str) -> str:
    """このドメインをどのレジストラで扱うか。"cloudflare" | "namecom"。"""
    return "cloudflare" if tld_of(domain) in CLOUDFLARE_TLDS else "namecom"


async def get_registrar_for(domain: str, user_id: Optional[str] = None) -> tuple[Any, str]:
    """ドメインに応じた registrar クライアントと provider 名を返す（TLDヒント routing）。"""
    provider = provider_for(domain)
    if provider == "cloudflare":
        return await get_cloudflare_registrar(user_id), "cloudflare"
    return await get_namecom_registrar(user_id), "namecom"


async def get_registrar_by_name(provider: str, user_id: Optional[str] = None) -> Any:
    """provider 名から registrar クライアントを返す。"""
    if provider == "cloudflare":
        return await get_cloudflare_registrar(user_id)
    return await get_namecom_registrar(user_id)


def _reg_price(quote: dict[str, Any]) -> float:
    try:
        return float(((quote.get("pricing") or {}).get("registration_cost")))
    except (TypeError, ValueError):
        return float("inf")


async def resolve_domain(query: str, user_id: Optional[str] = None) -> tuple[dict[str, Any], Optional[str]]:
    """両レジストラに空き確認し、取得可能なら**初年度が安い方**を選ぶ。取得不可なら
    理由付き(taken / unsupported)で返す。

    Returns:
        ``(exact_dict, provider_name | None)``。exact_dict は
        ``{name, registrable, tier, pricing, reason}``。provider は採用したレジストラ
        （取得不可なら None）。
    """
    quotes: list[tuple[str, dict[str, Any]]] = []
    nc_reason: Optional[str] = None
    # Cloudflare（対応外TLDは registrable=False/価格なしで返るので候補に入らない）
    try:
        cf = (await (await get_cloudflare_registrar(user_id)).check_availability([query]))[0]
        if cf.get("registrable") and cf.get("pricing"):
            quotes.append(("cloudflare", cf))
    except Exception:  # noqa: BLE001
        pass
    # Name.com
    try:
        nc = (await (await get_namecom_registrar(user_id)).check_availability([query]))[0]
        nc_reason = nc.get("reason")
        if nc.get("registrable") and nc.get("pricing"):
            quotes.append(("namecom", nc))
    except Exception:  # noqa: BLE001
        nc_reason = "unsupported"

    if quotes:
        provider, exact = min(quotes, key=lambda q: _reg_price(q[1]))
        exact = dict(exact)
        exact["reason"] = "available"
        return exact, provider

    # どちらも取得不可 → taken（登録済み）か unsupported（未対応TLD）か
    reason = "unsupported" if nc_reason == "unsupported" else "taken"
    return {"name": query, "registrable": False, "pricing": None, "reason": reason}, None
