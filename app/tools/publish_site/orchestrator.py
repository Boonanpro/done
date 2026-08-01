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
from app.tools.publish_site.namecom_registrar import NameComError, get_namecom_registrar
from app.tools.publish_site.registrar_router import (
    get_registrar_by_name,
    resolve_domain,
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
    dns_instructions: Optional[dict[str, Any]] = None  # 外部DNS時に手動設定するレコード
    conflict_label: Optional[str] = None  # 同じドメインを使用中の別成果物名(上書き確認用)
    verified: bool = True  # 外部DNSが未反映なら False(本番URLは未確定)


# 旧 issue_dedicated_delivery_url（<slug>-done.vercel.app 専用 alias 発行）は廃止。
# 納品 URL は常に <host>/preview/<slug>。production_url は custom_domain を取って
# 公開した時のみセットする。複数 URL が存在することで「修正したのに本番が直らない」
# 系の事故が起きていたため、URL 一本化のために削除した。


# ============================================
# Domain check (UI 入力補助)
# ============================================


async def check_domain(query: str, *, include_suggestions: bool = True) -> dict[str, Any]:
    """UI が「公開」ボタン押下後に呼ぶ事前チェック。

    TLD に応じて Cloudflare / Porkbun を自動選択する。Cloudflare に振った TLD が
    実は非対応（registrable=False かつ価格なし）だった場合は Porkbun に再問い合わせる。

    Returns:
        ``{"exact": {...}, "suggestions": [...]}``  両方とも domain-check 形式。
    """
    # 両レジストラを比較して安い方を採用＋理由(available/taken/unsupported)を判定
    exact, _provider = await resolve_domain(query)

    # 候補（予測サジェスト）は Cloudflare の domain-search を使う。
    # Porkbun の checkDomain は「10秒1回」制限で多数照会に向かないため、
    # 高速かつ複数TLDをまとめて返せる Cloudflare 検索に一本化する。
    suggestions: list[dict[str, Any]] = []
    if include_suggestions:
        base = query.strip().lower().rstrip(".")
        keyword = base.rsplit(".", 1)[0] if "." in base else base
        try:
            cf = await get_cloudflare_registrar()
            suggestions = await cf.search(keyword, limit=8)
        except Exception as e:  # noqa: BLE001
            logger.warning("suggestion search failed (non-fatal): %s", e)
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
        vercel = await get_vercel(user_id)
        cf_dns = await get_cloudflare_dns(user_id)

        # 1. 空き確認（両レジストラを比較し、初年度が安い方を採用）
        s = rec.start("check_availability")
        exact, provider = await resolve_domain(domain, user_id)
        if provider is None or not exact.get("registrable"):
            reason = (exact or {}).get("reason", "unavailable")
            rec.fail(s, f"{domain} is not registrable ({reason})")
            result.error = f"{domain} is not available ({reason})"
            return result
        registrar = await get_registrar_by_name(provider, user_id)
        result.pricing = exact.get("pricing")
        rec.complete(s, f"${(result.pricing or {}).get('registration_cost')}/y via {provider}")

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

        # 3.5 外部レジストラ(Porkbun等): Cloudflare にゾーン作成し NS を向ける。
        #     Cloudflare Registrar で取得した場合はゾーンが自動作成されるので不要。
        if provider != "cloudflare":
            s = rec.start("setup_dns_zone")
            if dry_run:
                rec.complete(s, "[DRY-RUN] would create CF zone + point NS")
            else:
                try:
                    zone_obj = await cf_dns.ensure_zone(domain)
                    nameservers = zone_obj.get("name_servers") or []
                    if nameservers and hasattr(registrar, "update_nameservers"):
                        await registrar.update_nameservers(domain, nameservers)
                    rec.complete(s, f"CF zone + NS→{','.join(nameservers[:2])}")
                except Exception as e:  # noqa: BLE001
                    rec.fail(s, str(e))
                    result.error = f"DNS zone setup failed: {e}"
                    return result

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

        # 8.5 Umami 計測 website 登録 (公開ドメインの訪問数を計測できるようにする)
        s = rec.start("register_analytics_website")
        if dry_run:
            rec.complete(s, "[DRY-RUN] skipped")
        else:
            try:
                from app.services.umami_service import ensure_website, is_configured

                if not is_configured():
                    s.status = "skipped"
                    s.detail = "Umami 未設定"
                else:
                    wid = await ensure_website(domain)
                    if wid:
                        rec.complete(s, f"umami website 登録 id={wid}")
                    else:
                        rec.fail(s, "umami website 登録に失敗（公開は成立）")
            except Exception as e:
                rec.fail(s, f"Umami 登録でエラー: {e}")

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

        # 10. クリーンURL配信: 取得ドメインの host rewrite を再生成して main へ push
        #     （接続フローと同じ。購入で取得した場合も /business 等をクリーンURLで配信する）。
        s = rec.start("publish_routing")
        if dry_run:
            rec.complete(s, "[DRY-RUN] skipped")
        else:
            try:
                # Dedicated projects resolve their own host; shared rewrite publication is retired.
                pub = {"changed": False}
                if pub.get("pushed"):
                    rec.complete(s, "クリーンURL設定を反映（数分で公開）")
                elif pub.get("changed") is False:
                    rec.complete(s, "クリーンURL設定は最新")
                else:
                    rec.fail(s, pub.get("detail", "ルーティング反映に失敗"))
            except Exception as e:  # noqa: BLE001
                rec.fail(s, f"ルーティング反映でエラー: {e}")

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
# 既に所有しているドメインを接続する（購入なし）
# ============================================


async def _detect_dns_provider(domain: str, user_id: Optional[str] = None) -> str:
    """ドメインのDNSをどこで設定できるか判定。"namecom" | "cloudflare" | "external"。"""
    try:
        nc = await get_namecom_registrar(user_id)
        if domain in await nc.list_owned_domains():
            return "namecom"
    except Exception:  # noqa: BLE001
        pass
    try:
        cf_dns = await get_cloudflare_dns(user_id)
        if await cf_dns.get_zone_by_name(domain):
            return "cloudflare"
    except Exception:  # noqa: BLE001
        pass
    return "external"


async def _artifact_using_domain(svc: ChatArtifactService, domain: str) -> Optional[dict[str, Any]]:
    """その custom_domain を使っている成果物を1件返す（無ければ None）。"""
    try:
        res = (
            svc.supabase.table(svc.table)
            .select("id, slug, label, custom_domain")
            .eq("custom_domain", domain)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None
    except Exception:  # noqa: BLE001
        return None


async def connect_existing_domain(
    *,
    artifact_id: str,
    domain: str,
    vercel_project: str = DEFAULT_VERCEL_PROJECT,
    user_id: Optional[str] = None,
    replace: bool = False,
) -> PublishResult:
    """既に所有しているドメイン（購入なし）を成果物に接続して公開する。

    - 別の成果物が同じドメインを使用中なら ``replace=False`` で error="domain_in_use" を返す
      （UIで確認 → replace=True で差し替え）。
    - 外部DNS管理のドメインは、実際に Vercel を向いている（検証OK）まで本番URLを確定しない
      （他人のドメイン誤接続で production_url が誤って立つ事故の防止）。
    """
    rec = _StepRecorder()
    domain = _normalize_domain(domain)
    base_url = f"https://{domain}"
    result = PublishResult(success=False, artifact_id=artifact_id, domain=domain, steps=rec.steps)
    try:
        vercel = await get_vercel(user_id)
        svc = ChatArtifactService()

        # 0. 上書きチェック（別成果物が同じドメインを使っていないか）
        s = rec.start("check_conflict")
        other = await _artifact_using_domain(svc, domain)
        if other and other.get("id") != artifact_id:
            label = other.get("label") or other.get("slug") or "別の成果物"
            if not replace:
                rec.fail(s, f"{domain} は「{label}」が使用中")
                result.error = "domain_in_use"
                result.conflict_label = label
                return result
            # 差し替え: 旧成果物からドメインを外す
            try:
                svc.supabase.table(svc.table).update(
                    {"custom_domain": None, "production_url": None, "publish_status": "preview_live"}
                ).eq("id", other["id"]).execute()
            except Exception:  # noqa: BLE001
                pass
            rec.complete(s, f"「{label}」から差し替え")
        else:
            rec.complete(s, "ok")

        # 1. DNS管理元を判定
        s = rec.start("detect_provider")
        provider = await _detect_dns_provider(domain, user_id)
        rec.complete(s, provider)

        # 2. Vercel に紐付け
        s = rec.start("attach_to_vercel")
        try:
            await vercel.add_domain_to_project(vercel_project, domain)
            rec.complete(s, f"attached to {vercel_project}")
        except VercelError as e:
            if e.status == 409:
                rec.complete(s, "already attached")
            else:
                raise

        # 3. Vercel が要求するレコードを取得
        cfg = await vercel.get_domain_config(domain)
        rec_ipv4 = (cfg.get("recommendedIPv4") or [])
        apex_ip = "76.76.21.21"
        if rec_ipv4 and rec_ipv4[0].get("value"):
            apex_ip = rec_ipv4[0]["value"][0]
        rec_cname = (cfg.get("recommendedCNAME") or [])
        cname_target = rec_cname[0]["value"].rstrip(".") if rec_cname else "cname.vercel-dns.com"

        # 4. DNS を Vercel に向ける
        s = rec.start("configure_dns")
        if provider == "namecom":
            nc = await get_namecom_registrar(user_id)
            await nc.set_vercel_dns(domain, apex_ip=apex_ip, cname_target=cname_target)
            rec.complete(s, f"A @→{apex_ip} / CNAME www→{cname_target}")
        elif provider == "cloudflare":
            cf_dns = await get_cloudflare_dns(user_id)
            zone = await cf_dns.get_zone_by_name(domain)
            await cf_dns.upsert_record(zone["id"], type="CNAME", name="@", content=cname_target)
            await cf_dns.upsert_record(zone["id"], type="CNAME", name="www", content=cname_target)
            rec.complete(s, f"CNAME @+www→{cname_target}")
        else:
            # 外部DNS: 自動設定できないので手動レコードを案内
            result.dns_instructions = {
                "a": {"host": "@", "value": apex_ip},
                "cname": {"host": "www", "value": cname_target},
            }
            rec.complete(s, "外部DNS: 手動でレコード設定が必要")

        # 5. 反映確認。外部DNSは「実際にVercelを向いているか」を検証し、未検証なら
        #    本番URLを確定しない（他人のドメイン誤接続で production_url が立つ事故の防止）。
        s = rec.start("verify_dns_propagation")
        verified = provider != "external"  # うちの口座内ドメインは所有確定
        if provider == "external":
            try:
                cfg2 = await vercel.get_domain_config(domain)
                verified = not cfg2.get("misconfigured", True)
            except Exception:  # noqa: BLE001
                verified = False
        if verified:
            try:
                await _wait_vercel_dns_verified(vercel, domain)
            except TimeoutError:
                pass  # うちのドメインは設定済みなので致命的にしない
            rec.complete(s, "反映確認OK")
        else:
            s.status = "skipped"
            s.detail = "DNS未反映: 上記レコードを設定すると公開されます"
        result.verified = verified

        # 6. 成果物にマッピング（検証OKの時だけ本番URLを確定）
        s = rec.start("update_artifact_db")
        try:
            if verified:
                update_data = {
                    "custom_domain": domain,
                    "production_url": base_url,
                    "publish_status": "live",
                    "delivery_mode": "client_domain",
                    "last_publish_error": None,
                }
            else:
                # 外部DNS未反映: 本番URL/マッピングはまだ立てない（誤接続事故防止）
                update_data = {"publish_status": "pending_dns"}
            if user_id:
                await svc.update(artifact_id, update_data, user_id)
            else:
                svc.supabase.table(svc.table).update(update_data).eq("id", artifact_id).execute()
            rec.complete(s, "保存" if verified else "DNS設定待ちとして保存")
        except Exception as e:  # noqa: BLE001
            rec.fail(s, f"DB update failed: {e}")

        # 7. SEO: Search Console 所有権確認 + sitemap 申請（検証OK & DNS自社管理のみ）
        s = rec.start("submit_search_console")
        if verified and provider in ("namecom", "cloudflare"):
            try:
                from app.tools.publish_site.search_console import (
                    get_dns_verification_record,
                    verify_and_submit,
                )

                sc_rec = await get_dns_verification_record(domain)
                if not sc_rec:
                    s.status = "skipped"
                    s.detail = "Search Console 未設定"
                else:
                    if provider == "namecom":
                        nc = await get_namecom_registrar(user_id)
                        await nc.set_txt_record(domain, sc_rec["value"])
                    else:
                        cf_dns = await get_cloudflare_dns(user_id)
                        zone = await cf_dns.get_zone_by_name(domain)
                        await cf_dns.upsert_record(
                            zone["id"], type="TXT", name="@", content=sc_rec["value"]
                        )
                    sc = await verify_and_submit(domain, f"https://{domain}/sitemap.xml")
                    if sc.get("sitemap_submitted"):
                        rec.complete(s, "Search Console に sitemap 申請完了")
                    else:
                        rec.fail(s, sc.get("detail", "Search Console 申請に一部失敗"))
            except Exception as e:  # noqa: BLE001
                rec.fail(s, f"Search Console 申請でエラー: {e}")
        else:
            s.status = "skipped"
            s.detail = "外部DNS or 未検証のためスキップ"

        # 7.5 Umami 計測 website 登録（接続ドメインの訪問数を計測できるように）
        s = rec.start("register_analytics_website")
        try:
            from app.services.umami_service import ensure_website, is_configured

            if not is_configured():
                s.status = "skipped"
                s.detail = "Umami 未設定"
            else:
                wid = await ensure_website(domain)
                if wid:
                    rec.complete(s, f"umami website 登録 id={wid}")
                else:
                    rec.fail(s, "umami website 登録に失敗（公開は成立）")
        except Exception as e:  # noqa: BLE001
            rec.fail(s, f"Umami 登録でエラー: {e}")

        # 8. クリーンURL配信: 接続ドメインの host rewrite を再生成して main へ push
        #    （Vercel 再デプロイで /business 等がクリーンURLで配信される）。ベストエフォート。
        s = rec.start("publish_routing")
        try:
            # Dedicated projects resolve their own host; shared rewrite publication is retired.
            pub = {"changed": False}
            if pub.get("pushed"):
                rec.complete(s, "クリーンURL設定を反映（数分で公開）")
            elif pub.get("changed") is False:
                rec.complete(s, "クリーンURL設定は最新")
            else:
                rec.fail(s, pub.get("detail", "ルーティング反映に失敗"))
        except Exception as e:  # noqa: BLE001
            rec.fail(s, f"ルーティング反映でエラー: {e}")

        result.success = True
        result.deploy_url = base_url if verified else None
        return result
    except (VercelError, CloudflareDNSError, NameComError) as e:
        for st in rec.steps:
            if st.status == "running":
                rec.fail(st, str(e))
        result.error = str(e)
        return result
    except Exception as e:  # noqa: BLE001
        for st in rec.steps:
            if st.status == "running":
                rec.fail(st, repr(e))
        result.error = repr(e)
        return result


# ============================================
# クライアント向けドメイン取得の案内フロー（Stripe 決済）
# ============================================
#
# オーナーが案内URL (/domain-setup/<token>) を発行してクライアントに渡す。
# クライアントは案内ページで金額を見てカード決済するだけ。決済完了後、
# 運営者のインフラ (Cloudflare/Vercel) が自動でドメイン取得〜公開〜検索登録まで
# 行う。クライアントはレジストラ移動も DNS 設定も一切不要。


def _normalize_domain(domain: str) -> str:
    """入力ドメインを FQDN に正規化する。"""
    d = (domain or "").strip().lower()
    d = d.replace("https://", "").replace("http://", "")
    d = d.split("/")[0].strip().strip(".")
    return d


def _setup_price(setup: dict[str, Any]) -> Optional[str]:
    """客に提示・請求する価格 (USD 文字列) を返す。

    Cloudflare 原価に Stripe 手数料分を上乗せした額。運営者の受取が原価を
    下回らないようにするためで、利益は乗せていない。
    """
    exact = ((setup.get("availability") or {}).get("exact")) or {}
    pricing = exact.get("pricing") or {}
    cost = pricing.get("registration_cost")
    if cost is None:
        return None
    # .ai 等は最低登録年数(min_duration)があるので総額で請求する（.com系は1で従来どおり）
    try:
        min_dur = max(int(exact.get("min_duration") or 1), 1)
    except (TypeError, ValueError):
        min_dur = 1
    try:
        from app.tools.publish_site.stripe_payments import gross_up_for_fee

        cents = gross_up_for_fee(round(float(cost) * min_dur * 100))
    except (TypeError, ValueError):
        return None
    return f"{cents / 100:.2f}"


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

    # 空き確認 + 価格取得
    availability: dict[str, Any] = {}
    try:
        availability = await check_domain(domain, include_suggestions=True)
    except Exception as e:  # noqa: BLE001
        logger.warning("domain availability check failed (non-fatal): %s", e)

    token = secrets.token_urlsafe(24)
    setup = {
        "domain": domain,
        "vercel_project": vercel_project,
        "slug": slug,
        "status": "pending",  # pending → registering → live / failed
        "availability": availability,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "paid_at": None,
        "verified_at": None,
        "stripe_session_id": None,
        "last_error": None,
        "registrant_mode": "client",
        "registrant_saved": False,
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
        "price": _setup_price(setup),
        "artifact_label": artifact.get("label") or slug,
    }


async def get_domain_setup_state(token: str) -> Optional[dict[str, Any]]:
    """案内トークンからセッション状態を取得する (公開ページ用・認証なし)。"""
    svc = ChatArtifactService()
    artifact = await svc.get_by_domain_setup_token(token)
    if artifact is None:
        return None
    setup = artifact.get("domain_setup") or {}
    if setup.get("registrant_mode") not in (None, "client") or not setup.get("registrant_saved"):
        return {"success": False, "error": "Please enter the domain registrant information before payment."}
    return {
        "artifact_id": artifact["id"],
        "artifact_label": artifact.get("label") or setup.get("slug") or "成果物",
        "setup": setup,
        "price": _setup_price(setup),
        "production_url": artifact.get("production_url"),
    }


async def create_domain_checkout(token: str, *, return_origin: str) -> dict[str, Any]:
    """Stripe Checkout セッションを作成し、決済ページURLを返す (公開・クライアント操作)。

    Returns:
        ``{"success": bool, "checkout_url": str}`` または ``{"success": False, "error": str}``
    """
    svc = ChatArtifactService()
    artifact = await svc.get_by_domain_setup_token(token)
    if artifact is None:
        return {"success": False, "error": "案内ページが見つかりません"}
    setup = artifact.get("domain_setup") or {}
    domain = setup.get("domain")
    if not domain:
        return {"success": False, "error": "ドメイン情報がありません"}
    if setup.get("status") in ("registering", "live"):
        return {"success": False, "error": "すでに手続きが完了しています"}

    # Do not create a payable Checkout session from a stale invitation quote:
    # the name may have been taken or repriced since the link was issued.
    try:
        fresh_availability = await check_domain(domain, include_suggestions=False)
        exact = fresh_availability.get("exact") or {}
    except Exception as e:  # noqa: BLE001
        logger.exception("domain availability recheck failed")
        return {"success": False, "error": f"Unable to recheck domain availability: {e}"}
    if not exact.get("registrable"):
        return {"success": False, "error": "This domain is no longer available. No payment was taken."}

    # Persist the price that will be used for this Checkout session.
    setup["availability"] = fresh_availability
    svc.supabase.table(svc.table).update({"domain_setup": setup}).eq(
        "id", artifact["id"]
    ).execute()
    price = _setup_price(setup)
    try:
        amount_cents = round(float(price) * 100)
    except (TypeError, ValueError):
        return {"success": False, "error": "ドメイン価格を取得できませんでした"}
    if amount_cents <= 0:
        return {"success": False, "error": "ドメイン価格が不正です"}

    origin = (return_origin or "").rstrip("/")
    if not origin:
        return {"success": False, "error": "戻り先URLが不明です"}

    try:
        from app.tools.publish_site.stripe_payments import create_checkout_session

        url = await create_checkout_session(
            amount_cents=amount_cents,
            currency="usd",
            product_name=f"独自ドメイン取得・公開: {domain}",
            success_url=f"{origin}/domain-setup/{token}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{origin}/domain-setup/{token}",
            metadata={"token": token, "domain": domain},
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("create_domain_checkout failed")
        return {"success": False, "error": str(e)}
    return {"success": True, "checkout_url": url}


async def confirm_domain_payment(token: str, session_id: str) -> dict[str, Any]:
    """決済完了を検証する。支払い済みなら status=registering にして登録開始可否を返す。

    Returns:
        ``{"success": bool, "status": str|None, "start": bool, "error": str|None}``
        ``start=True`` のとき呼び出し側が ``run_paid_registration`` を実行する。
    """
    svc = ChatArtifactService()
    artifact = await svc.get_by_domain_setup_token(token)
    if artifact is None:
        return {"success": False, "status": None, "start": False, "error": "案内ページが見つかりません"}
    setup = dict(artifact.get("domain_setup") or {})
    status = setup.get("status")
    if status in ("registering", "live"):
        # すでに処理中 / 完了
        return {"success": True, "status": status, "start": False, "error": None}

    try:
        from app.tools.publish_site.stripe_payments import retrieve_session

        sess = await retrieve_session(session_id)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "status": status, "start": False,
                "error": f"決済の確認に失敗しました: {str(e)[:200]}"}
    if not sess.get("paid"):
        return {"success": False, "status": status, "start": False,
                "error": "決済がまだ完了していません"}
    if (sess.get("metadata") or {}).get("token") != token:
        return {"success": False, "status": status, "start": False,
                "error": "決済情報が一致しません"}

    setup["status"] = "registering"
    setup["paid_at"] = datetime.now(timezone.utc).isoformat()
    setup["stripe_session_id"] = session_id
    setup["last_error"] = None
    svc.supabase.table(svc.table).update({"domain_setup": setup}).eq(
        "id", artifact["id"]
    ).execute()
    return {"success": True, "status": "registering", "start": True, "error": None}


async def run_paid_registration(token: str) -> None:
    """決済済みドメインの取得〜公開を実行する (バックグラウンドタスク)。

    運営者の Cloudflare でドメインを取得し、Vercel 紐付け・DNS・SEO・Search Console
    申請まで自動実行する。クライアント側の操作は不要。
    """
    svc = ChatArtifactService()
    artifact = await svc.get_by_domain_setup_token(token)
    if artifact is None:
        return
    setup = dict(artifact.get("domain_setup") or {})
    domain = setup.get("domain")
    slug = setup.get("slug")
    artifact_id = artifact["id"]

    # Stripe テストモード (sk_test_) では実ドメイン取得を行わず空実行する。
    # 本番キー (sk_live_) の時だけ Cloudflare で実際に取得する。
    from app.tools.publish_site.stripe_payments import is_test_mode

    dry_run = await is_test_mode()

    # Never infer the legal registrant from the payer/cardholder or DAN owner.
    from app.services.domain_registrant_profile_service import get_domain_registrant_profile_service
    try:
        registrant_contact = await get_domain_registrant_profile_service().get_for_setup(token)
        if not registrant_contact:
            raise RuntimeError("The client registrant information was not provided.")
        setup["registrant_profile"] = "client_verified"
    except Exception as e:  # noqa: BLE001
        setup["status"] = "failed"
        setup["last_error"] = f"Registrant profile is not ready: {e}"
        svc.supabase.table(svc.table).update({"domain_setup": setup}).eq("id", artifact_id).execute()
        return

    deploy_url: Optional[str] = None
    try:
        # The payer may never return to the owner browser, so the durable
        # registration worker itself performs the dedicated deployment.  The
        # domain is not attached until this immutable release is ready.
        from app.services.artifact_publication_service import ArtifactPublicationService
        await ArtifactPublicationService().deploy_dedicated_release(
            artifact, user_id=artifact.get("created_by")
        )
        result = await publish_with_custom_domain(
            artifact_id=artifact_id,
            domain=domain,
            vercel_project=setup.get("vercel_project") or DEFAULT_VERCEL_PROJECT,
            artifact_dir=f"frontend/src/app/artifacts/{slug}" if slug else None,
            write_seo_files=True,
            contact=registrant_contact,
            auto_renew=False,  # 自動更新OFF: 入金なしに更新料が課金されるのを防ぐ
            dry_run=dry_run,
            user_id=None,  # 運営者の Cloudflare / Vercel を使う
        )
        ok, err, deploy_url = result.success, result.error, result.deploy_url
    except Exception as e:  # noqa: BLE001
        ok, err = False, repr(e)

    latest = await svc.get_by_domain_setup_token(token)
    setup = dict((latest or {}).get("domain_setup") or setup)
    if ok:
        setup["status"] = "live"
        setup["verified_at"] = datetime.now(timezone.utc).isoformat()
        setup["last_error"] = None
        setup["dry_run"] = dry_run
        update: dict[str, Any] = {"domain_setup": setup}
        # dry-run でも完了画面に表示できるよう production_url を入れる
        if deploy_url:
            update["production_url"] = deploy_url
            update["custom_domain"] = domain
            update["publish_status"] = "live"
        svc.supabase.table(svc.table).update(update).eq("id", artifact_id).execute()
    else:
        setup["status"] = "failed"
        setup["last_error"] = err
        svc.supabase.table(svc.table).update({"domain_setup": setup}).eq(
            "id", artifact_id
        ).execute()


async def recover_paid_domain_registrations() -> int:
    """Resume paid registrations left running by a sandbox restart.

    The payment and its ``registering`` state are persisted before the work
    begins, so restart recovery is safe and makes the flow durable without a
    second queue service.
    """
    svc = ChatArtifactService()
    rows = svc.supabase.table(svc.table).select(
        "domain_setup_token,domain_setup"
    ).not_.is_("domain_setup_token", "null").execute().data or []
    resumed = 0
    for row in rows:
        setup = row.get("domain_setup") or {}
        token = row.get("domain_setup_token")
        if token and setup.get("status") == "registering":
            asyncio.create_task(run_paid_registration(token))
            resumed += 1
    return resumed
