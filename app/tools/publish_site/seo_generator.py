"""
SEO アセット自動生成

公開ドメイン用に sitemap.xml / robots.txt / JSON-LD / Next.js metadata を生成する。
全て純粋関数で副作用なし。ファイル書き出しは呼び出し側 (orchestrator) が行う。

Manus / Base44 はここまで自動化していないので、ダンの差別化ポイント。

使い方:
    from app.tools.publish_site.seo_generator import (
        BusinessInfo, PageInfo,
        generate_sitemap_xml, generate_sitemap_ts,
        generate_robots_txt, generate_robots_ts,
        generate_local_business_jsonld,
        generate_metadata,
    )
    sitemap = generate_sitemap_xml("https://example.com", pages)
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from typing import Any, Literal, Optional, TypedDict
from urllib.parse import urljoin

# ============================================
# データ型
# ============================================


class BusinessInfo(TypedDict, total=False):
    """LocalBusiness JSON-LD 用のビジネス情報"""

    name: str  # 例: "株式会社吉川特装"
    legal_name: str  # 例: "Yoshikawa Tokuso Inc."
    description: str
    url: str  # 例: "https://yoshikawa-tokuso.com"
    logo: str  # ロゴ画像の絶対URL
    image: str  # ヒーロー画像など
    telephone: str  # 例: "+81-859-XX-XXXX"
    email: str
    street_address: str
    locality: str  # 市区町村
    region: str  # 都道府県
    postal_code: str
    country: str  # ISO 3166-1 alpha-2 (例: "JP")
    latitude: float
    longitude: float
    opening_hours: list[str]  # 例: ["Mo-Fr 09:00-18:00"]
    price_range: str  # 例: "¥¥"
    same_as: list[str]  # SNS・関連サイトURL
    business_type: str  # schema.org type (例: "LocalBusiness", "AutoRepair", "Restaurant")


class PageInfo(TypedDict, total=False):
    path: str  # サイトルートからのパス (例: "/services")
    title: str
    description: str
    last_modified: str  # ISO 8601 (例: "2026-05-12")
    change_freq: Literal["always", "hourly", "daily", "weekly", "monthly", "yearly", "never"]
    priority: float  # 0.0 - 1.0
    images: list[str]  # 絶対URL


# ============================================
# sitemap.xml / sitemap.ts
# ============================================


def _xml_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _join_url(base: str, path: str) -> str:
    base = base.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def generate_sitemap_xml(base_url: str, pages: list[PageInfo]) -> str:
    """XML形式の sitemap (静的ファイル / Next.js public/sitemap.xml 用)"""
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
        '        xmlns:image="http://www.google.com/schemas/sitemap-image/1.1">',
    ]
    for page in pages:
        url = _xml_escape(_join_url(base_url, page.get("path", "/")))
        lines.append("  <url>")
        lines.append(f"    <loc>{url}</loc>")
        if page.get("last_modified"):
            lines.append(f"    <lastmod>{_xml_escape(page['last_modified'])}</lastmod>")
        if page.get("change_freq"):
            lines.append(f"    <changefreq>{page['change_freq']}</changefreq>")
        if "priority" in page:
            lines.append(f"    <priority>{page['priority']:.1f}</priority>")
        for img in page.get("images", []):
            lines.append("    <image:image>")
            lines.append(f"      <image:loc>{_xml_escape(img)}</image:loc>")
            lines.append("    </image:image>")
        lines.append("  </url>")
    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def generate_sitemap_ts(base_url: str, pages: list[PageInfo]) -> str:
    """Next.js 13+ App Router の sitemap.ts (動的生成)"""
    entries = []
    for page in pages:
        url = _join_url(base_url, page.get("path", "/"))
        entry: dict[str, Any] = {"url": url}
        if page.get("last_modified"):
            entry["lastModified"] = page["last_modified"]
        if page.get("change_freq"):
            entry["changeFrequency"] = page["change_freq"]
        if "priority" in page:
            entry["priority"] = page["priority"]
        entries.append(entry)
    json_body = json.dumps(entries, indent=2, ensure_ascii=False)
    return f"""import type {{ MetadataRoute }} from \"next\";

export default function sitemap(): MetadataRoute.Sitemap {{
  return {json_body};
}}
"""


# ============================================
# robots.txt / robots.ts
# ============================================


def generate_robots_txt(
    sitemap_url: str, *, disallow: Optional[list[str]] = None
) -> str:
    """robots.txt (静的)"""
    lines = ["User-agent: *", "Allow: /"]
    for path in disallow or []:
        lines.append(f"Disallow: {path}")
    lines.append("")
    lines.append(f"Sitemap: {sitemap_url}")
    return "\n".join(lines) + "\n"


def generate_robots_ts(
    sitemap_url: str, *, disallow: Optional[list[str]] = None
) -> str:
    """Next.js 13+ の robots.ts"""
    disallow_list = disallow or []
    return f"""import type {{ MetadataRoute }} from \"next\";

export default function robots(): MetadataRoute.Robots {{
  return {{
    rules: {{
      userAgent: \"*\",
      allow: \"/\",
      disallow: {json.dumps(disallow_list, ensure_ascii=False)},
    }},
    sitemap: {json.dumps(sitemap_url)},
  }};
}}
"""


# ============================================
# JSON-LD (構造化データ)
# ============================================


def generate_local_business_jsonld(
    business: BusinessInfo, *, page_url: Optional[str] = None
) -> dict[str, Any]:
    """LocalBusiness スキーマ (B2B HP向け)。

    Google にリッチリザルト表示の素地を作る。
    """
    btype = business.get("business_type", "LocalBusiness")
    data: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": btype,
    }
    if name := business.get("name"):
        data["name"] = name
    if legal_name := business.get("legal_name"):
        data["legalName"] = legal_name
    if desc := business.get("description"):
        data["description"] = desc
    if url := page_url or business.get("url"):
        data["url"] = url
    if logo := business.get("logo"):
        data["logo"] = logo
    if image := business.get("image"):
        data["image"] = image
    if tel := business.get("telephone"):
        data["telephone"] = tel
    if email := business.get("email"):
        data["email"] = email
    if business.get("street_address") or business.get("locality"):
        address: dict[str, Any] = {"@type": "PostalAddress"}
        for src_key, dst_key in [
            ("street_address", "streetAddress"),
            ("locality", "addressLocality"),
            ("region", "addressRegion"),
            ("postal_code", "postalCode"),
            ("country", "addressCountry"),
        ]:
            if v := business.get(src_key):
                address[dst_key] = v
        data["address"] = address
    if "latitude" in business and "longitude" in business:
        data["geo"] = {
            "@type": "GeoCoordinates",
            "latitude": business["latitude"],
            "longitude": business["longitude"],
        }
    if hours := business.get("opening_hours"):
        data["openingHours"] = hours
    if price_range := business.get("price_range"):
        data["priceRange"] = price_range
    if same_as := business.get("same_as"):
        data["sameAs"] = same_as
    return data


def generate_jsonld_script(jsonld: dict[str, Any]) -> str:
    """JSON-LD を <script type="application/ld+json"> 要素として出力する文字列"""
    body = json.dumps(jsonld, ensure_ascii=False, separators=(",", ":"))
    return f'<script type="application/ld+json">{body}</script>'


# ============================================
# Next.js Metadata
# ============================================


def generate_metadata(
    page: PageInfo,
    business: Optional[BusinessInfo] = None,
    *,
    base_url: Optional[str] = None,
) -> dict[str, Any]:
    """Next.js 13+ App Router の export const metadata 用オブジェクト。

    title / description / OpenGraph / Twitter / canonical を一括生成。
    """
    base = (base_url or (business or {}).get("url", "")).rstrip("/")
    canonical = _join_url(base, page.get("path", "/")) if base else None
    title = page.get("title") or (business or {}).get("name", "")
    description = page.get("description") or (business or {}).get("description", "")
    images = page.get("images") or ([(business or {}).get("image", "")] if business and business.get("image") else [])

    metadata: dict[str, Any] = {}
    if title:
        metadata["title"] = title
    if description:
        metadata["description"] = description
    if canonical:
        metadata["alternates"] = {"canonical": canonical}

    # OpenGraph
    og: dict[str, Any] = {}
    if title:
        og["title"] = title
    if description:
        og["description"] = description
    if canonical:
        og["url"] = canonical
    if images:
        og["images"] = [img for img in images if img]
    og["type"] = "website"
    if og:
        metadata["openGraph"] = og

    # Twitter
    twitter: dict[str, Any] = {"card": "summary_large_image"}
    if title:
        twitter["title"] = title
    if description:
        twitter["description"] = description
    if images:
        twitter["images"] = [img for img in images if img]
    metadata["twitter"] = twitter

    return metadata


# ============================================
# ページスキャナ (Next.js artifact directory)
# ============================================


_NEXT_DYNAMIC_RE = re.compile(r"\[.+\]")


def scan_artifact_pages(
    artifact_dir: str,
    *,
    skip_dynamic: bool = True,
    skip_dirs: tuple[str, ...] = ("components", "v2", "scratch", "demo"),
) -> list[PageInfo]:
    """Next.js artifact ディレクトリを走査して page.tsx を一覧化。

    Args:
        artifact_dir: 例: ``frontend/src/app/artifacts/kittoku``
        skip_dynamic: ``[slug]`` のような動的ルートを除外
        skip_dirs: 走査対象外のサブディレクトリ名

    Returns:
        ``[{"path": "/services", "last_modified": "2026-05-12"}, ...]``
    """
    import pathlib

    root = pathlib.Path(artifact_dir)
    if not root.is_dir():
        return []

    pages: list[PageInfo] = []
    for page_file in root.rglob("page.tsx"):
        rel_parts = page_file.relative_to(root).parent.parts
        if any(part in skip_dirs for part in rel_parts):
            continue
        if skip_dynamic and any(_NEXT_DYNAMIC_RE.search(part) for part in rel_parts):
            continue
        path = "/" + "/".join(rel_parts) if rel_parts else "/"
        mtime = _dt.datetime.fromtimestamp(page_file.stat().st_mtime, _dt.timezone.utc)
        pages.append(
            {
                "path": path,
                "last_modified": mtime.date().isoformat(),
                "change_freq": "weekly",
                "priority": 1.0 if path == "/" else 0.8,
            }
        )
    # ルートを先頭に並べる
    pages.sort(key=lambda p: (p["path"] != "/", p["path"]))
    return pages
