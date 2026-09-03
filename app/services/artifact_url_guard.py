"""Guards that keep internal Vercel deployment URLs out of user-facing text."""

from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

INTERNAL_FRONTEND_URL_RE = re.compile(
    r"https://frontend(?:-[a-z0-9-]+)?-mikis-projects-86652663\.vercel\.app(?P<path>/[^\s)\]}>'\"、。]*)?",
    re.IGNORECASE,
)

ARTIFACT_PATH_RE = re.compile(r"^/(?:artifacts|preview)/(?P<slug>[^/?#]+)(?P<rest>[^?#]*)?(?P<tail>[?#].*)?$")

# 廃止済みの専用 alias。過去に発行した <slug>-done.vercel.app は Vercel 側から
# 外れており、いま踏むと 404 になる。生成も再利用もしない。
LEGACY_ALIAS_SUFFIX = "-done.vercel.app"

_SHARE_URL_TTL_SECONDS = 300
_SHARE_URL_CACHE: dict[str, tuple[float, str]] = {}


def is_legacy_alias_url(value: str | None) -> bool:
    """廃止済み専用 alias (<slug>-done.vercel.app) かどうか。"""
    return bool(value) and LEGACY_ALIAS_SUFFIX in str(value)


def _lookup_share_url(slug: str) -> str:
    """成果物の実在する公開URLを DB から引く。分からなければ空文字。

    参照先は chat_artifact の share_url / draft_url（専用 Vercel プロジェクトの
    URL が入っている）。DB に触れない環境でも呼べるよう、例外は握りつぶす。
    """
    if not slug:
        return ""
    now = time.monotonic()
    cached = _SHARE_URL_CACHE.get(slug)
    if cached and now - cached[0] < _SHARE_URL_TTL_SECONDS:
        return cached[1]

    url = ""
    try:
        from app.services.supabase_client import get_supabase_client

        result = (
            get_supabase_client().client.table("chat_artifact")
            .select("share_url,draft_url,production_url,custom_domain")
            .eq("slug", slug)
            .limit(1)
            .execute()
        )
        row = (result.data or [{}])[0]
        custom_domain = str(row.get("custom_domain") or "").strip()
        candidates = [
            str(row.get("production_url") or "").strip() if custom_domain else "",
            str(row.get("share_url") or "").strip(),
            str(row.get("draft_url") or "").strip(),
        ]
        for candidate in candidates:
            if candidate.startswith(("http://", "https://")) and not is_legacy_alias_url(candidate):
                url = candidate.rstrip("/")
                break
    except Exception:
        url = ""

    _SHARE_URL_CACHE[slug] = (now, url)
    return url


def public_url_for_slug(slug: str, rest: str = "", tail: str = "") -> str:
    """ユーザーに見せてよい成果物URL。

    実在する公開URL（専用 Vercel プロジェクト、または独自ドメイン）を優先する。
    まだ公開されていない成果物は相対パス /preview/<slug> を返す。廃止済みの
    <slug>-done.vercel.app は決して返さない。
    """
    clean_rest = rest or "/"
    if not clean_rest.startswith("/"):
        clean_rest = f"/{clean_rest}"
    base = _lookup_share_url(slug)
    if base:
        suffix = "" if clean_rest == "/" else clean_rest
        return f"{base}{suffix or '/'}{tail or ''}"
    suffix = "" if clean_rest == "/" else clean_rest
    return f"/preview/{slug}{suffix}{tail or ''}"


# 旧名。呼び出し側の互換のために残す。
delivery_url_for_slug = public_url_for_slug


def sanitize_artifact_public_urls(text: str, fallback_slug: str | None = None) -> str:
    """Replace internal frontend deployment URLs with stable artifact URLs.

    If the URL contains /preview/<slug> or /artifacts/<slug>, the slug is
    recovered from the path. If it is only the deployment root, fallback_slug is
    used when the caller has a single active artifact context.
    """
    if not text:
        return text

    def repl(match: re.Match[str]) -> str:
        path = match.group("path") or ""
        parsed = ARTIFACT_PATH_RE.match(path)
        if parsed:
            return delivery_url_for_slug(
                parsed.group("slug"),
                parsed.group("rest") or "/",
                parsed.group("tail") or "",
            )
        if fallback_slug:
            try:
                split = urlsplit(path)
                rest = split.path or "/"
                tail = f"?{split.query}" if split.query else ""
                if split.fragment:
                    tail += f"#{split.fragment}"
            except Exception:
                rest, tail = "/", ""
            return delivery_url_for_slug(fallback_slug, rest, tail)
        return "[内部デプロイURL]"

    return INTERNAL_FRONTEND_URL_RE.sub(repl, text)
