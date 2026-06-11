"""ドメインから「どのレジストラで登録されているか」を自動特定する（RDAP）。

ユーザーが外部ドメインを接続したいとき、本人が「どこで買ったか / ログインは何か」を
忘れていてもダン側で特定できるようにするための土台。WHOIS の現代版 RDAP を引き、
登録レジストラ名・IANA ID を取り出して、ダンが扱える形（API自動 / ブラウザ代理ログイン /
未対応）に正規化して返す。

- レジストラ口座のログイン情報は不要（RDAP は公開情報）。
- 「実際にうちの口座内にあるか（API管理可能か）」は別途 list_owned_domains で確認する。
  本モジュールはあくまで「登録レジストラの同定」と「対応方式のヒント」まで。

使い方:
    from app.tools.publish_site.registrar_detect import detect_registrar
    info = await detect_registrar("example.com")
    # -> {"registrar_name": "...", "iana_id": "49", "registrar_key": "gmo_onamae",
    #     "automation": "browser", "login_url": "https://...", "found": True}

CLI: python -m app.tools.publish_site.registrar_detect example.com
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

RDAP_BASE = "https://rdap.org/domain/"
HTTP_TIMEOUT = 15.0

# 既知レジストラの正規化テーブル。キーは IANA Registrar ID（文字列）。
#   key        : ダン内部で使う安定slug
#   label      : 人間向け表示名
#   login_url  : ユーザーを案内するログイン画面
#   automation : "api"     = ダンがAPIトークンで直接DNS設定できる（口座内なら）
#                "browser" = 代理ログイン(ブラウザ自動操作)で対応予定
#                "manual"  = 自動化未対応。手動レコード設定を案内
_BY_IANA: dict[str, dict[str, str]] = {
    "625": {"key": "namecom", "label": "Name.com", "login_url": "https://www.name.com/account/login", "automation": "api"},
    "1910": {"key": "cloudflare", "label": "Cloudflare Registrar", "login_url": "https://dash.cloudflare.com/login", "automation": "api"},
    "49": {"key": "gmo_onamae", "label": "お名前.com (GMO Internet)", "login_url": "https://navi.onamae.com/login", "automation": "browser"},
    "1645": {"key": "muumuu", "label": "ムームードメイン (GMO Pepabo)", "login_url": "https://muumuu-domain.com/checkout/login", "automation": "browser"},
    "146": {"key": "godaddy", "label": "GoDaddy", "login_url": "https://sso.godaddy.com/", "automation": "browser"},
    "81": {"key": "gandi", "label": "Gandi", "login_url": "https://id.gandi.net/login", "automation": "browser"},
    "1861": {"key": "porkbun", "label": "Porkbun", "login_url": "https://porkbun.com/account/login", "automation": "browser"},
    "292": {"key": "markmonitor", "label": "MarkMonitor", "login_url": "https://www.markmonitor.com/", "automation": "manual"},
    "895": {"key": "google_squarespace", "label": "Squarespace (旧Google Domains)", "login_url": "https://account.squarespace.com/", "automation": "browser"},
}

# IANA ID が取れない時の保険：レジストラ名の部分一致で同定する。
_BY_NAME_SUBSTR: list[tuple[str, str]] = [
    ("name.com", "625"),
    ("cloudflare", "1910"),
    ("onamae", "49"),
    ("gmo internet", "49"),
    ("muumuu", "1645"),
    ("pepabo", "1645"),
    ("godaddy", "146"),
    ("gandi", "81"),
    ("porkbun", "1861"),
    ("markmonitor", "292"),
    ("squarespace", "895"),
    ("google", "895"),
]


def _normalize(domain: str) -> str:
    d = (domain or "").strip().lower().rstrip(".")
    if "://" in d:
        d = d.split("://", 1)[1]
    return d.split("/", 1)[0].lstrip("www.") if d.startswith("www.") else d.split("/", 1)[0]


def _extract_registrar(rdap: dict[str, Any]) -> tuple[Optional[str], Optional[str]]:
    """RDAP レスポンスから (registrar_name, iana_id) を取り出す。"""
    name: Optional[str] = None
    iana: Optional[str] = None
    for ent in rdap.get("entities", []) or []:
        if "registrar" not in (ent.get("roles") or []):
            continue
        for v in (ent.get("vcardArray", [[], []])[1] or []):
            if v and v[0] == "fn":
                name = v[3]
        pid = ent.get("publicIds") or []
        if pid:
            iana = str(pid[0].get("identifier") or "") or None
    return name, iana


def _classify(name: Optional[str], iana: Optional[str]) -> dict[str, str]:
    """(name, iana) を既知レジストラに正規化。未知なら key=unknown/automation=manual。"""
    if iana and iana in _BY_IANA:
        return _BY_IANA[iana]
    if name:
        low = name.lower()
        for sub, mapped_iana in _BY_NAME_SUBSTR:
            if sub in low:
                return _BY_IANA[mapped_iana]
    return {"key": "unknown", "label": name or "不明なレジストラ", "login_url": "", "automation": "manual"}


async def detect_registrar(domain: str) -> dict[str, Any]:
    """ドメインの登録レジストラを RDAP で特定して正規化情報を返す。

    Returns dict:
        found        : RDAP が引けて registrar が取れたか
        domain       : 正規化後ドメイン
        registrar_name / iana_id : RDAP 由来の生データ
        registrar_key / label / login_url / automation : 正規化結果
        detail       : 失敗時の説明
    """
    d = _normalize(domain)
    base = {
        "found": False, "domain": d, "registrar_name": None, "iana_id": None,
        "registrar_key": "unknown", "label": "不明なレジストラ", "login_url": "",
        "automation": "manual", "detail": "",
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                RDAP_BASE + d, headers={"Accept": "application/rdap+json"}
            )
        if resp.status_code != 200:
            base["detail"] = f"RDAP 応答 {resp.status_code}"
            return base
        rdap = resp.json()
    except Exception as e:  # noqa: BLE001
        base["detail"] = f"RDAP 取得失敗: {e}"
        return base

    name, iana = _extract_registrar(rdap)
    cls = _classify(name, iana)
    base.update(
        found=bool(name or iana),
        registrar_name=name,
        iana_id=iana,
        registrar_key=cls["key"],
        label=cls["label"],
        login_url=cls["login_url"],
        automation=cls["automation"],
    )
    if not base["found"]:
        base["detail"] = "RDAP に registrar 情報が含まれていません"
    return base


def _main() -> int:
    import sys

    if len(sys.argv) < 2:
        print("usage: python -m app.tools.publish_site.registrar_detect <domain> [domain...]")
        return 2
    async def run() -> None:
        for dom in sys.argv[1:]:
            info = await detect_registrar(dom)
            print(
                f"{info['domain']:24} {info['label']:32} "
                f"key={info['registrar_key']:14} automation={info['automation']:8} "
                f"iana={info['iana_id']}"
            )
    asyncio.run(run())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
