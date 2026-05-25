"""Guards that keep internal Vercel deployment URLs out of user-facing text."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

INTERNAL_FRONTEND_URL_RE = re.compile(
    r"https://frontend(?:-[a-z0-9-]+)?-mikis-projects-86652663\.vercel\.app(?P<path>/[^\s)\]}>'\"、。]*)?",
    re.IGNORECASE,
)

ARTIFACT_PATH_RE = re.compile(r"^/(?:artifacts|preview)/(?P<slug>[^/?#]+)(?P<rest>[^?#]*)?(?P<tail>[?#].*)?$")


def delivery_url_for_slug(slug: str, rest: str = "", tail: str = "") -> str:
    clean_rest = rest or "/"
    if not clean_rest.startswith("/"):
        clean_rest = f"/{clean_rest}"
    return f"https://{slug}-done.vercel.app{clean_rest}{tail or ''}"


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
