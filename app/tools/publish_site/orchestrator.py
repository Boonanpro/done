"""
公開フロー統合 (Orchestrator)

`check_domain()` と `publish_with_custom_domain()` の2つが本ファイルの主要API。

publish_with_custom_domain の流れ:
    1. ドメイン空き確認 (Cloudflare Registrar)
    2. ドメイン購入                (Cloudflare Registrar)
    3. 登録完了待ち                (Cloudflare Registrar)
    4. Vercel プロジェクトに紐付け (Vercel)
    5. Vercel が要求するDNSレコードを Cloudflare に作成 (Cloudflare DNS)
    6. DNS verification 完了待ち   (Vercel)
    7. SEO アセット生成・書き出し  (SEO generator)
    8. Search Console 所有権確認 + sitemap 申請 (Search Console)
    9. chat_artifact DB 更新

各ステップは PublishStep として記録され、UI 側でストリーミング表示可能。
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from app.services.chat_artifact_service import ChatArtifactService
from app.tools.publish_site.cloudflare_dns import (
    CloudflareDNSError,
    get_cloudflare_dns,
)
from app.tools.publish_site.cloudflare_registrar import (
    Contact,
    RegistrarError,
    get_cloudflare_registrar,
)
from app.tools.publish_site.seo_generator import (
    BusinessInfo,
    generate_robots_ts,
    generate_sitemap_ts,
    scan_artifact_pages,
)
from app.tools.publish_site.vercel_domains import VercelError, get_vercel

logger = logging.getLogger(__name__)

StepStatus = Literal["pending", "running", "completed", "failed", "skipped"]

REGISTRATION_POLL_INTERVAL_SEC = 5
REGISTRATION_POLL_TIMEOUT_SEC = 180
DNS_VERIFY_POLL_INTERVAL_SEC = 5
DNS_VERIFY_TIMEOUT_SEC = 180
DEFAULT_VERCEL_PROJECT = "frontend"
DEDICATED_ALIAS_SUFFIX = "-done.vercel.app"


@dataclass
class PublishStep:
    name: str
    status: StepStatus = "pending"
    detail: str = ""
    duration_ms: int = 0


@dataclass
class PublishResult:
    success: bool
    artifact_id: str
    domain: str
    deploy_url: Optional[str] = None
    steps: list[PublishStep] = field(default_factory=list)
    error: Optional[str] = None
    pricing: Optional[dict[str, Any]] = None


def _alias_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    return slug[:45].strip("-") or "artifact"


async def issue_dedicated_delivery_url(
    *,
    artifact_id: str,
    slug: str,
    user_id: Optional[str] = None,
    vercel_project: str = DEFAULT_VERCEL_PROJECT,
) -> dict[str, Any]:
    """Issue a dedicated vercel.app URL for a non-website artifact.

    The alias points to the latest production deployment. Middleware maps
    ``<slug>-done.vercel.app`` to the artifact root.
    """
    vercel = await get_vercel(user_id)
    deployments = await vercel.list_deployments(vercel_project, target="production", limit=1)
    if not deployments:
        raise RuntimeError("No production deployment is available for delivery URL")

    deployment = deployments[0]
    deployment_id = deployment.get("uid") or deployment.get("id")
    if not deployment_id:
        raise RuntimeError("Latest production deployment has no id")

    base_slug = _alias_slug(slug)
    candidates = [
        f"{base_slug}{DEDICATED_ALIAS_SUFFIX}",
        f"{base_slug}-{artifact_id[:8]}{DEDICATED_ALIAS_SUFFIX}",
    ]
    last_error: Exception | None = None
    for alias in candidates:
        try:
            result = await vercel.assign_alias(deployment_id, alias)
            url = f"https://{alias}"
            svc = ChatArtifactService()
            update_data = {
                "production_url": url,
                "publish_status": "delivery_live",
                "delivery_status": "ready",
                "delivery_mode": "dedicated_url",
                "last_publish_error": None,
            }
            if user_id:
                await svc.update(artifact_id, update_data, user_id)
            else:
                svc.supabase.table(svc.table).update(update_data).eq("id", artifact_id).execute()
            return {"url": url, "alias": alias, "deployment_id": deployment_id, "vercel": result}
        except VercelError as e:
            last_error = e
            if e.status == 409:
                continue
            raise
    raise RuntimeError(f"Could not assign delivery alias: {last_error}")


# ============================================
# Domain check (UI 入力補助)
# ============================================


async def check_domain(query: str, *, include_suggestions: bool = True) -> dict[str, Any]:
    """UI が「公開」ボタン押下後に呼ぶ事前チェック。

    Returns:
        ``{"exact": {...}, "suggestions": [...]}``  両方とも domain-check 形式。
    """
    r = await get_cloudflare_registrar()
    exact_list = await r.check_availability([query])
    exact = exact_list[0] if exact_list else None
    suggestions: list[dict[str, Any]] = []
    if include_suggestions:
        try:
            suggestions = await r.search(query, limit=8)
        except RegistrarError as e:
            logger.warning("search failed (non-fatal): %s", e)
    return {"exact": exact, "suggestions": suggestions}


# ============================================
# 公開フロー本体
# ============================================


class _StepRecorder:
    """Step 計測・記録用ヘルパー"""

    def __init__(self) -> None:
        self.steps: list[PublishStep] = []

    def start(self, name: str) -> PublishStep:
        step = PublishStep(name=name, status="running")
        self.steps.append(step)
        step._start = time.monotonic()  # type: ignore[attr-defined]
        logger.info("[publish] %s ...", name)
        return step

    def complete(self, step: PublishStep, detail: str = "") -> None:
        step.status = "completed"
        step.detail = detail
        step.duration_ms = int((time.monotonic() - step._start) * 1000)  # type: ignore[attr-defined]
        logger.info("[publish] %s ✓ (%dms) %s", step.name, step.duration_ms, detail)

    def fail(self, step: PublishStep, detail: str) -> None:
        step.status = "failed"
        step.detail = detail
        step.duration_ms = int((time.monotonic() - step._start) * 1000)  # type: ignore[attr-defined]
        logger.error("[publish] %s ✗ %s", step.name, detail)

    def skip(self, name: str, detail: str = "") -> None:
        self.steps.append(PublishStep(name=name, status="skipped", detail=detail))


async def _wait_registration_complete(registrar, domain: str) -> None:
    """購入したドメインの登録ワークフロー完了を待つ。"""
    deadline = time.monotonic() + REGISTRATION_POLL_TIMEOUT_SEC
    while time.monotonic() < deadline:
        status = await registrar.get_registration_status(domain)
        state = status.get("status") or status.get("state")
        if state in ("complete", "completed", "active"):
            return
        if state in ("failed", "rejected"):
            raise RuntimeError(f"registration failed: {status}")
        await asyncio.sleep(REGISTRATION_POLL_INTERVAL_SEC)
    raise TimeoutError(f"registration did not complete in {REGISTRATION_POLL_TIMEOUT_SEC}s")


async def _wait_vercel_dns_verified(vercel, domain: str) -> dict[str, Any]:
    """Vercel側で DNS設定が反映されるのを待つ。"""
    deadline = time.monotonic() + DNS_VERIFY_TIMEOUT_SEC
    last_config: dict[str, Any] = {}
    while time.monotonic() < deadline:
        config = await vercel.get_domain_config(domain)
        last_config = config
        if not config.get("misconfigured"):
            return config
        await asyncio.sleep(DNS_VERIFY_POLL_INTERVAL_SEC)
    raise TimeoutError(
        f"DNS verification did not pass in {DNS_VERIFY_TIMEOUT_SEC}s (last config: {last_config})"
    )


async def publish_with_custom_domain(
    *,
    artifact_id: str,
    domain: str,
    vercel_project: str,
    business_info: Optional[BusinessInfo] = None,
    contact: Optional[Contact] = None,
    years: int = 1,
    auto_renew: bool = True,
    artifact_dir: Optional[str] = None,
    write_seo_files: bool = True,
    dry_run: bool = False,
    user_id: Optional[str] = None,
) -> PublishResult:
    """カスタムドメインで artifact を公開するフルフロー。

    Args:
        artifact_id: chat_artifact.id (DB更新用)
        domain: 取得するドメイン (例: "yoshikawa-tokuso.com")
        vercel_project: Vercel project id または name
        business_info: SEO JSON-LD 用ビジネス情報 (任意)
        contact: WHOIS 用 Registrant Contact (省略時はアカウントデフォルト)
        years: 登録年数
        auto_renew: 自動更新
        artifact_dir: ``frontend/src/app/artifacts/<slug>`` への絶対/相対パス。
            sitemap.ts / robots.ts を書き出す先。
        write_seo_files: SEO ファイルを実ファイルとして書き出す
        dry_run: True なら購入を行わず手順だけ実行 (検証用)
        user_id: credentials DB のキー
    """
    rec = _StepRecorder()
    result = PublishResult(success=False, artifact_id=artifact_id, domain=domain, steps=rec.steps)

    try:
        registrar = await get_cloudflare_registrar(user_id)
        vercel = await get_vercel(user_id)
        cf_dns = await get_cloudflare_dns(user_id)

        # 1. 空き確認
        s = rec.start("check_availability")
        avail = (await registrar.check_availability([domain]))[0]
        if not avail.get("registrable"):
            rec.fail(s, f"{domain} is not registrable (tier={avail.get('tier')})")
            result.error = f"{domain} is not available"
            return result
        result.pricing = avail.get("pricing")
        rec.complete(s, f"${result.pricing.get('registration_cost')}/y")

        # 2. 購入
        s = rec.start("register_domain")
        if dry_run:
            rec.complete(s, "[DRY-RUN] skipped actual registration")
        else:
            await registrar.register(
                domain, years=years, auto_renew=auto_renew, contact=contact
            )
            rec.complete(s)

        # 3. 登録完了待ち
        s = rec.start("wait_registration_complete")
        if dry_run:
            rec.complete(s, "[DRY-RUN] skipped")
        else:
            await _wait_registration_complete(registrar, domain)
            rec.complete(s)

        # 4. Vercel に紐付け
        s = rec.start("attach_to_vercel")
        if dry_run:
            rec.complete(s, f"[DRY-RUN] would attach {domain} to {vercel_project}")
        else:
            try:
                await vercel.add_domain_to_project(vercel_project, domain)
                rec.complete(s, f"attached to {vercel_project}")
            except VercelError as e:
                if e.status == 409:  # already attached
                    rec.complete(s, "already attached")
                else:
                    raise

        # 5. DNS レコード設定 (Vercel が要求する形)
        zone: Optional[dict[str, Any]] = None
        s = rec.start("configure_dns")
        if dry_run:
            rec.complete(s, "[DRY-RUN] skipped DNS")
        else:
            zone = await cf_dns.get_zone_by_name(domain)
            if zone is None:
                rec.fail(s, "zone not found in Cloudflare (registrar didn't create zone?)")
                result.error = "DNS zone missing"
                return result
            # Vercel が要求するレコード: CNAME @ cname.vercel-dns.com
            try:
                await cf_dns.upsert_record(
                    zone["id"], type="CNAME", name="@", content="cname.vercel-dns.com"
                )
                await cf_dns.upsert_record(
                    zone["id"], type="CNAME", name="www", content="cname.vercel-dns.com"
                )
                rec.complete(s, "CNAME @ + www → cname.vercel-dns.com")
            except CloudflareDNSError as e:
                rec.fail(s, str(e))
                result.error = f"DNS configuration failed: {e}"
                return result

        # 6. Vercel DNS verification 待ち
        s = rec.start("verify_dns_propagation")
        if dry_run:
            rec.complete(s, "[DRY-RUN] skipped")
        else:
            try:
                await _wait_vercel_dns_verified(vercel, domain)
                rec.complete(s)
            except TimeoutError as e:
                rec.fail(s, str(e))
                # 続行 (DNS は伝播するまで時間がかかる場合あり)

        # 7. SEO アセット生成 + 書き出し
        s = rec.start("generate_seo_assets")
        base_url = f"https://{domain}"
        if artifact_dir:
            pages = scan_artifact_pages(artifact_dir)
        else:
            pages = []
        if pages:
            sitemap_ts = generate_sitemap_ts(base_url, pages)
            robots_ts = generate_robots_ts(f"{base_url}/sitemap.xml")
            if write_seo_files and artifact_dir and not dry_run:
                sm_path = Path(artifact_dir) / "sitemap.ts"
                rb_path = Path(artifact_dir) / "robots.ts"
                sm_path.write_text(sitemap_ts, encoding="utf-8")
                rb_path.write_text(robots_ts, encoding="utf-8")
                rec.complete(s, f"wrote sitemap.ts + robots.ts ({len(pages)} pages)")
            else:
                rec.complete(s, f"generated for {len(pages)} pages (not written)")
        else:
            rec.skip("generate_seo_assets", "no pages found, skipped")

        # 8. Search Console 申請 (公開 → 検索でヒットする状態まで自動化)
        s = rec.start("submit_to_search_console")
        if dry_run:
            rec.complete(s, "[DRY-RUN] skipped")
        elif zone is None:
            s.status = "skipped"
            s.detail = "Cloudflare zone が不明のためスキップ"
        else:
            try:
                from app.tools.publish_site.search_console import auto_submit

                sc_result = await auto_submit(
                    domain,
                    f"{base_url}/sitemap.xml",
                    zone_id=zone["id"],
                    cf_dns=cf_dns,
                )
                if not sc_result.get("configured"):
                    s.status = "skipped"
                    s.detail = sc_result.get("detail", "Search Console 未設定")
                elif sc_result.get("sitemap_submitted"):
                    rec.complete(s, sc_result.get("detail", ""))
                else:
                    # 所有権確認や申請が一部失敗しても公開自体は成立しているので致命的にしない
                    rec.fail(s, sc_result.get("detail", "Search Console 申請に一部失敗"))
            except Exception as e:
                rec.fail(s, f"Search Console 申請でエラー: {e}")

        # 9. DB 更新
        s = rec.start("update_artifact_db")
        if dry_run:
            rec.complete(s, "[DRY-RUN] skipped")
        else:
            try:
                svc = ChatArtifactService()
                update_data = {
                    "custom_domain": domain,
                    "production_url": base_url,
                    "publish_status": "live",
                    "delivery_status": "delivered",
                    "delivery_mode": "client_domain",
                    "last_publish_error": None,
                }
                if user_id:
                    await svc.update(artifact_id, update_data, user_id)
                else:
                    svc.supabase.table(svc.table).update(update_data).eq("id", artifact_id).execute()
                rec.complete(s)
            except Exception as e:
                rec.fail(s, f"DB update failed: {e}")
                # DB エラーでも公開自体は成立しているので致命的にしない

        result.success = True
        result.deploy_url = base_url
        return result

    except (RegistrarError, VercelError, CloudflareDNSError) as e:
        for s in rec.steps:
            if s.status == "running":
                rec.fail(s, str(e))
        result.error = str(e)
        return result
    except Exception as e:
        for s in rec.steps:
            if s.status == "running":
                rec.fail(s, repr(e))
        result.error = repr(e)
        return result


# ============================================
# クライアント所有ドメインの案内フロー
# ============================================
#
# オーナーが代理決済せず、クライアント自身がドメインを取得・所有する方式。
# オーナーは案内URL (/domain-setup/<token>) を発行してクライアントに渡すだけ。
# クライアントは公開ページから 購入 → DNS設定 → 検証 を自分で進められる。

PROJECT_ROOT = Path(__file__).resolve().parents[3]  # D:\done
VERCEL_APEX_IP = "76.76.21.21"  # Vercel のルートドメイン用 A レコード
VERCEL_WWW_CNAME = "cname.vercel-dns.com"  # Vercel の www 用 CNAME

# クライアントにドメイン購入先として案内するレジストラ (homepage の安定URL)
REGISTRAR_LINKS: list[dict[str, str]] = [
    {"label": "お名前.com（国内最大手・日本語サポート）", "url": "https://www.onamae.com/"},
    {"label": "ムームードメイン（個人事業者向け・操作が簡単）", "url": "https://muumuu-domain.com/"},
    {"label": "Cloudflare Registrar（原価販売・更新料が安い）", "url": "https://www.cloudflare.com/products/registrar/"},
]


def _normalize_domain(domain: str) -> str:
    """入力ドメインを FQDN に正規化する。"""
    d = (domain or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "")
    d = d.split("/")[0].strip().strip(".")
    return d


def _write_seo_files_best_effort(slug: str, base_url: str) -> None:
    """artifact ディレクトリに sitemap.ts / robots.ts を生成する (ベストエフォート)。

    生成後は git commit/push でデプロイされて初めて公開URLに反映される。
    """
    if not slug:
        return
    try:
        artifact_dir = PROJECT_ROOT / "frontend" / "src" / "app" / "artifacts" / slug
        if not artifact_dir.is_dir():
            logger.info("SEO: artifact dir not found, skipped (%s)", artifact_dir)
            return
        pages = scan_artifact_pages(str(artifact_dir))
        if not pages:
            return
        (artifact_dir / "sitemap.ts").write_text(
            generate_sitemap_ts(base_url, pages), encoding="utf-8"
        )
        (artifact_dir / "robots.ts").write_text(
            generate_robots_ts(f"{base_url}/sitemap.xml"), encoding="utf-8"
        )
        logger.info("SEO: wrote sitemap.ts + robots.ts for %s (%d pages)", slug, len(pages))
    except Exception as e:  # noqa: BLE001 - SEO 生成失敗で案内発行を止めない
        logger.warning("SEO file generation skipped: %s", e)


async def create_domain_setup(
    *,
    artifact_id: str,
    domain: str,
    vercel_project: str = DEFAULT_VERCEL_PROJECT,
    user_id: str,
) -> dict[str, Any]:
    """クライアント向けドメイン設定の案内セッションを作成する (オーナー操作)。

    Returns:
        ``{"token": str, "setup": dict, "artifact_label": str}``
    """
    svc = ChatArtifactService()
    artifact = await svc.get(artifact_id, user_id)
    if artifact is None:
        raise RuntimeError("artifact が見つかりません")

    domain = _normalize_domain(domain)
    if "." not in domain:
        raise RuntimeError("ドメインは example.com のような形式で入力してください")
    slug = artifact.get("slug") or ""

    # 1. 空き確認 (取得済みでも案内自体は続行する)
    availability: dict[str, Any] = {}
    try:
        availability = await check_domain(domain, include_suggestions=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("domain availability check failed (non-fatal): %s", e)

    # 2. クライアントが設定する DNS レコード
    dns_records: list[dict[str, str]] = [
        {"type": "A", "name": "@", "value": VERCEL_APEX_IP,
         "purpose": "サイトを表示する（ルートドメイン）"},
        {"type": "CNAME", "name": "www", "value": VERCEL_WWW_CNAME,
         "purpose": "サイトを表示する（www付き）"},
    ]
    # Google Search Console 所有権確認 TXT (サービスアカウント設定済みの時のみ)
    try:
        from app.tools.publish_site.search_console import get_dns_verification_record

        sc_rec = await get_dns_verification_record(domain)
        if sc_rec:
            dns_records.append(
                {**sc_rec, "purpose": "Google検索に登録する（所有権の確認）"}
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("search console verification record skipped: %s", e)

    # 3. SEO ファイル生成 (オーナー操作なのでこのタイミングで作る)
    _write_seo_files_best_effort(slug, f"https://{domain}")

    # 4. セッション保存
    token = secrets.token_urlsafe(24)
    setup = {
        "domain": domain,
        "vercel_project": vercel_project,
        "slug": slug,
        "status": "pending",
        "dns_records": dns_records,
        "availability": availability,
        "registrar_links": REGISTRAR_LINKS,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "verified_at": None,
        "last_error": None,
        "search_console": None,
    }
    await svc.update(
        artifact_id,
        {
            "domain_setup_token": token,
            "domain_setup": setup,
            "payment_responsibility": "client_pays",
            "delivery_mode": "client_domain",
        },
        user_id,
    )
    return {
        "token": token,
        "setup": setup,
        "artifact_label": artifact.get("label") or slug,
    }


async def get_domain_setup_state(token: str) -> Optional[dict[str, Any]]:
    """案内トークンからセッション状態を取得する (公開ページ用・認証なし)。"""
    svc = ChatArtifactService()
    artifact = await svc.get_by_domain_setup_token(token)
    if artifact is None:
        return None
    setup = artifact.get("domain_setup") or {}
    return {
        "artifact_id": artifact["id"],
        "artifact_label": artifact.get("label") or setup.get("slug") or "成果物",
        "setup": setup,
        "production_url": artifact.get("production_url"),
    }


async def verify_domain_setup(token: str) -> dict[str, Any]:
    """クライアントが DNS 設定後に押す検証。DNS が通っていれば公開を確定する。

    Returns:
        ``{"found": bool, "status": str, "verified": bool, "detail": str,
           "production_url": str|None, "setup": dict}``
    """
    svc = ChatArtifactService()
    artifact = await svc.get_by_domain_setup_token(token)
    if artifact is None:
        return {"found": False, "verified": False, "detail": "案内ページが見つかりません"}

    setup = dict(artifact.get("domain_setup") or {})
    domain = setup.get("domain")
    artifact_id = artifact["id"]
    vercel_project = setup.get("vercel_project") or DEFAULT_VERCEL_PROJECT

    if not domain:
        return {
            "found": True, "status": "failed", "verified": False,
            "detail": "ドメイン情報が登録されていません", "setup": setup,
        }

    def _save() -> None:
        svc.supabase.table(svc.table).update({"domain_setup": setup}).eq(
            "id", artifact_id
        ).execute()

    # 1. Vercel に紐付け + DNS 構成チェック
    #    ホスティングは運営者の Vercel アカウントが全テナント分を提供する。
    try:
        vercel = await get_vercel()
        try:
            await vercel.add_domain_to_project(vercel_project, domain)
        except VercelError as e:
            if e.status != 409:  # 409 = 既に紐付け済み
                raise
        config = await vercel.get_domain_config(domain)
    except Exception as e:  # noqa: BLE001
        setup["last_error"] = str(e)[:300]
        _save()
        return {
            "found": True, "status": setup.get("status", "pending"), "verified": False,
            "detail": f"接続確認でエラーが発生しました: {str(e)[:200]}", "setup": setup,
        }

    if config.get("misconfigured", True):
        setup["status"] = "dns_pending"
        setup["last_error"] = None
        _save()
        return {
            "found": True, "status": "dns_pending", "verified": False,
            "detail": (
                "DNSの設定がまだ反映されていません。"
                "レコードを設定済みの場合、反映に数分〜数十分かかることがあります。"
                "少し待ってからもう一度「接続を確認」を押してください。"
            ),
            "setup": setup,
        }

    # 2. DNS OK → 公開を確定 + Search Console 申請
    base_url = f"https://{domain}"
    try:
        from app.tools.publish_site.search_console import verify_and_submit

        sc_result = await verify_and_submit(domain, f"{base_url}/sitemap.xml")
    except Exception as e:  # noqa: BLE001
        sc_result = {
            "configured": True, "verified": False, "sitemap_submitted": False,
            "detail": f"Search Console 申請でエラー: {str(e)[:200]}",
        }

    setup["status"] = "live"
    setup["verified_at"] = datetime.now(timezone.utc).isoformat()
    setup["last_error"] = None
    setup["search_console"] = sc_result

    svc.supabase.table(svc.table).update(
        {
            "custom_domain": domain,
            "production_url": base_url,
            "publish_status": "live",
            "delivery_status": "delivered",
            "delivery_mode": "client_domain",
            "last_publish_error": None,
            "domain_setup": setup,
        }
    ).eq("id", artifact_id).execute()

    if sc_result.get("sitemap_submitted"):
        detail = "ドメインを接続し、Google検索への登録（sitemap申請）まで完了しました。"
    elif sc_result.get("configured"):
        detail = "ドメインを接続しました。検索登録は申請を試みましたが一部未完了です。"
    else:
        detail = "ドメインを接続しました。サイトは公開済みです。"

    return {
        "found": True, "status": "live", "verified": True,
        "production_url": base_url, "detail": detail, "setup": setup,
    }
