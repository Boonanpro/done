"""Meta (Instagram/Facebook) 広告 CLI — ダンが広告出稿・運用を行うための薄いラッパー。

Meta Marketing API / Graph API を raw REST（requests）で叩く。公式 CLI は存在しないため自前。
facebook-business SDK には依存しない（requests のみ）。

マルチテナント設計（SaaS / client-owns）:
  - Meta Developer App は運営者が1つ（`connect-app` で登録、または env META_APP_ID/META_APP_SECRET）。
  - 各テナント（クライアント）は自分の広告アカウントを `connect` で接続し、自分のトークンを持つ。
  - user_id は既定で $DAN_USER_ID（無ければ owner にフォールバック）。--account でアカウント選択。

⚠️ 課金ゲート: `publish`（キャンペーン有効化＝課金開始）と `ig-post`（公開投稿）は --confirm 必須。
  --confirm 無しでは承認待ちプロンプトを返して何もしない。

全コマンドは JSON を stdout に出力する（ok / error を含む）。

使用例:
  # 0) 運営者アプリ（1回だけ）
  python scripts/meta_ads_cli.py connect-app --app-id <ID> --app-secret <SECRET>
  # 1) テナント接続（短期ユーザートークン → 長期に交換して保存）
  python scripts/meta_ads_cli.py connect --short-token <TOKEN> --ad-account-id <ID> --page-id <ID> --ig-user-id <ID>
  # 2) 動作確認
  python scripts/meta_ads_cli.py whoami
  python scripts/meta_ads_cli.py remote-accounts        # トークンが触れる広告アカウント一覧
  # 3) ドラフト作成（全て PAUSED で作られる）
  python scripts/meta_ads_cli.py campaign --name "夏キャンペーン" --objective OUTCOME_TRAFFIC
  python scripts/meta_ads_cli.py adset --campaign-id <ID> --name "AdSet1" --daily-budget 1000 --link https://example.com
  python scripts/meta_ads_cli.py ad --adset-id <ID> --name "Ad1" --message "本文" --headline "見出し" --link https://example.com --image /path/img.jpg --cta LEARN_MORE
  # 4) 承認の上で出稿（課金開始）
  python scripts/meta_ads_cli.py publish --campaign-id <ID> --confirm
  # 5) 運用
  python scripts/meta_ads_cli.py insights --campaign-id <ID> --date-preset last_7d
  python scripts/meta_ads_cli.py pause --campaign-id <ID>
  # 6) Instagram オーガニック投稿
  python scripts/meta_ads_cli.py ig-post --caption "本文" --image-url https://.../img.jpg --confirm
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Windows コンソール(cp932)でも日本語の help / JSON を出せるよう UTF-8 に固定
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except Exception:
        pass

API_VERSION = os.getenv("META_API_VERSION", "v21.0")
GRAPH = f"https://graph.facebook.com/{API_VERSION}"

# 小数を持たない通貨（最小単位＝1）。それ以外は cents（×100）。
ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW", "VND", "CLP", "ISK", "HUF", "TWD"}

VALID_OBJECTIVES = {
    "OUTCOME_TRAFFIC", "OUTCOME_LEADS", "OUTCOME_ENGAGEMENT",
    "OUTCOME_SALES", "OUTCOME_AWARENESS", "OUTCOME_APP_PROMOTION",
}


# ----------------------------------------------------------------------------
# 出力ヘルパー
# ----------------------------------------------------------------------------
def out(obj: dict, code: int = 0):
    print(json.dumps(obj, ensure_ascii=False, indent=2))
    sys.exit(code)


def fail(msg: str, **extra):
    out({"ok": False, "error": msg, **extra}, code=1)


# ----------------------------------------------------------------------------
# Graph API 呼び出し（requests は遅延 import：--help を依存なしで通すため）
# ----------------------------------------------------------------------------
def _graph(method: str, path: str, token: str, params=None, data=None, files=None):
    import requests

    url = path if path.startswith("http") else f"{GRAPH}/{path.lstrip('/')}"
    params = dict(params or {})
    if files is None:
        params["access_token"] = token
    else:
        data = dict(data or {})
        data["access_token"] = token

    resp = requests.request(method, url, params=params, data=data, files=files, timeout=60)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text}
    if resp.status_code >= 400 or (isinstance(body, dict) and body.get("error")):
        err = body.get("error", {}) if isinstance(body, dict) else {}
        raise MetaApiError(err.get("message", resp.text), err)
    return body


class MetaApiError(Exception):
    def __init__(self, message, payload=None):
        super().__init__(message)
        self.payload = payload or {}


# ----------------------------------------------------------------------------
# user_id / アカウント解決
# ----------------------------------------------------------------------------
def resolve_user_id(arg_user):
    if arg_user:
        return arg_user
    env = os.getenv("DAN_USER_ID")
    if env:
        return env
    from app.services.owner import resolve_owner_user_id
    return resolve_owner_user_id()


def get_service():
    from app.services.meta_ads_service import get_meta_ads_service
    return get_meta_ads_service()


def require_account(svc, user_id, label):
    acct = svc.get_account(user_id, label)
    if not acct or not acct.get("access_token"):
        fail(
            f"アカウント '{label}' が未接続です。先に connect してください。",
            hint="python scripts/meta_ads_cli.py connect --short-token <TOKEN> --ad-account-id <ID> ...",
        )
    return acct


def budget_to_minor(amount: float, currency: str) -> int:
    cur = (currency or "JPY").upper()
    factor = 1 if cur in ZERO_DECIMAL_CURRENCIES else 100
    return int(round(amount * factor))


# ============================================================================
# コマンド実装
# ============================================================================
def cmd_connect_app(args, svc, user_id):
    if not args.app_id or not args.app_secret:
        fail("--app-id と --app-secret が必要です。")
    svc.save_app_config(user_id, args.app_id, args.app_secret)
    out({"ok": True, "message": "運営者 Meta App を保存しました。", "app_id": args.app_id})


def cmd_connect(args, svc, user_id):
    """短期トークンを長期に交換して保存。--system-token 指定時はそのまま保存（無期限）。"""
    label = args.account
    token = None
    token_type = "user"
    expires_at = None

    if args.system_token:
        token = args.system_token
        token_type = "system_user"
    elif args.short_token:
        cfg = svc.get_app_config(user_id)
        if not cfg or not cfg.get("app_id"):
            fail("運営者 App 未設定。先に connect-app するか env META_APP_ID/META_APP_SECRET を設定してください。")
        try:
            r = _graph("GET", "oauth/access_token", token="", params={
                "grant_type": "fb_exchange_token",
                "client_id": cfg["app_id"],
                "client_secret": cfg["app_secret"],
                "fb_exchange_token": args.short_token,
            })
        except MetaApiError as e:
            fail(f"トークン交換に失敗: {e}", detail=e.payload)
        token = r.get("access_token")
        token_type = "user_long_lived"
        if r.get("expires_in"):
            expires_at = (datetime.now(timezone.utc) + timedelta(seconds=int(r["expires_in"]))).isoformat()
    else:
        fail("--short-token または --system-token のいずれかが必要です。")

    # トークンの妥当性確認＋通貨の自動取得
    currency = args.currency
    try:
        me = _graph("GET", "me", token=token, params={"fields": "id,name"})
    except MetaApiError as e:
        fail(f"トークンが無効です: {e}", detail=e.payload)
    if args.ad_account_id and not currency:
        try:
            acc = _graph("GET", f"act_{args.ad_account_id}", token=token, params={"fields": "currency,name"})
            currency = acc.get("currency")
        except MetaApiError:
            pass

    svc.save_account(
        user_id=user_id, account_label=label, access_token=token,
        ad_account_id=args.ad_account_id, page_id=args.page_id, ig_user_id=args.ig_user_id,
        currency=currency, token_type=token_type, expires_at=expires_at,
        display_name=args.display_name or me.get("name"),
    )
    out({
        "ok": True, "message": f"アカウント '{label}' を接続しました。",
        "account": label, "fb_user": me.get("name"), "token_type": token_type,
        "ad_account_id": args.ad_account_id, "currency": currency,
        "token_expires_at": expires_at or "never",
    })


def cmd_whoami(args, svc, user_id):
    acct = require_account(svc, user_id, args.account)
    try:
        me = _graph("GET", "me", token=acct["access_token"], params={"fields": "id,name"})
        dbg = _graph("GET", "debug_token", token=acct["access_token"], params={"input_token": acct["access_token"]})
    except MetaApiError as e:
        fail(f"確認に失敗: {e}", detail=e.payload)
    data = dbg.get("data", {})
    out({
        "ok": True, "account": args.account, "fb_user": me, "valid": data.get("is_valid"),
        "scopes": data.get("scopes"), "expires_at": data.get("expires_at"),
        "ad_account_id": acct.get("ad_account_id"), "currency": acct.get("currency"),
        "page_id": acct.get("page_id"), "ig_user_id": acct.get("ig_user_id"),
    })


def cmd_accounts(args, svc, user_id):
    out({"ok": True, "accounts": svc.list_accounts(user_id)})


def cmd_remote_accounts(args, svc, user_id):
    acct = require_account(svc, user_id, args.account)
    try:
        r = _graph("GET", "me/adaccounts", token=acct["access_token"],
                   params={"fields": "account_id,name,currency,account_status"})
    except MetaApiError as e:
        fail(f"取得に失敗: {e}", detail=e.payload)
    out({"ok": True, "ad_accounts": r.get("data", [])})


def cmd_campaign(args, svc, user_id):
    acct = require_account(svc, user_id, args.account)
    if not acct.get("ad_account_id"):
        fail("ad_account_id が未設定。connect 時に --ad-account-id を指定してください。")
    if args.objective not in VALID_OBJECTIVES:
        fail(f"objective は次のいずれか: {sorted(VALID_OBJECTIVES)}")
    special = json.loads(args.special_ad_categories) if args.special_ad_categories else []
    try:
        r = _graph("POST", f"act_{acct['ad_account_id']}/campaigns", token=acct["access_token"], params={
            "name": args.name,
            "objective": args.objective,
            "status": "PAUSED",  # 常に一時停止で作成。出稿は publish で。
            "special_ad_categories": json.dumps(special),
        })
    except MetaApiError as e:
        fail(f"キャンペーン作成に失敗: {e}", detail=e.payload)
    out({"ok": True, "campaign_id": r.get("id"), "status": "PAUSED",
         "note": "ドラフト作成（停止中）。publish --confirm で出稿。"})


def cmd_adset(args, svc, user_id):
    acct = require_account(svc, user_id, args.account)
    if args.targeting_file:
        targeting = json.loads(Path(args.targeting_file).read_text(encoding="utf-8"))
    else:
        countries = [c.strip().upper() for c in (args.countries or "JP").split(",")]
        targeting = {"geo_locations": {"countries": countries}}
        if args.age_min:
            targeting["age_min"] = args.age_min
        if args.age_max:
            targeting["age_max"] = args.age_max

    params = {
        "name": args.name,
        "campaign_id": args.campaign_id,
        "billing_event": args.billing_event,
        "optimization_goal": args.optimization_goal,
        "targeting": json.dumps(targeting),
        "status": "PAUSED",
        "daily_budget": budget_to_minor(args.daily_budget, acct.get("currency")),
    }
    if args.start_time:
        params["start_time"] = args.start_time
    if args.end_time:
        params["end_time"] = args.end_time
    if args.bid_amount:
        params["bid_amount"] = budget_to_minor(args.bid_amount, acct.get("currency"))
    else:
        params["bid_strategy"] = "LOWEST_COST_WITHOUT_CAP"
    try:
        r = _graph("POST", f"act_{acct['ad_account_id']}/adsets", token=acct["access_token"], params=params)
    except MetaApiError as e:
        fail(f"広告セット作成に失敗: {e}", detail=e.payload)
    out({"ok": True, "adset_id": r.get("id"), "status": "PAUSED",
         "daily_budget_minor": params["daily_budget"], "currency": acct.get("currency"),
         "targeting": targeting})


def _upload_image(acct, token, image_path):
    with open(image_path, "rb") as f:
        r = _graph("POST", f"act_{acct['ad_account_id']}/adimages", token=token,
                   files={"filename": f})
    images = r.get("images", {})
    first = next(iter(images.values()), {})
    return first.get("hash")


def cmd_ad(args, svc, user_id):
    acct = require_account(svc, user_id, args.account)
    if not acct.get("page_id"):
        fail("page_id が未設定。connect 時に --page-id を指定してください（クリエイティブに必須）。")
    token = acct["access_token"]

    link_data = {"link": args.link, "message": args.message}
    if args.headline:
        link_data["name"] = args.headline
    if args.description:
        link_data["description"] = args.description
    if args.cta:
        link_data["call_to_action"] = {"type": args.cta, "value": {"link": args.link}}
    if args.image:
        try:
            img_hash = _upload_image(acct, token, args.image)
        except MetaApiError as e:
            fail(f"画像アップロードに失敗: {e}", detail=e.payload)
        if not img_hash:
            fail("画像 hash の取得に失敗しました。")
        link_data["image_hash"] = img_hash
    elif args.image_hash:
        link_data["image_hash"] = args.image_hash

    object_story_spec = {"page_id": acct["page_id"], "link_data": link_data}
    if acct.get("ig_user_id"):
        # Instagram 配置を有効化（新仕様は instagram_user_id）
        object_story_spec["instagram_user_id"] = acct["ig_user_id"]

    try:
        cr = _graph("POST", f"act_{acct['ad_account_id']}/adcreatives", token=token, params={
            "name": f"{args.name} creative",
            "object_story_spec": json.dumps(object_story_spec),
        })
        creative_id = cr.get("id")
        ad = _graph("POST", f"act_{acct['ad_account_id']}/ads", token=token, params={
            "name": args.name,
            "adset_id": args.adset_id,
            "creative": json.dumps({"creative_id": creative_id}),
            "status": "PAUSED",
        })
    except MetaApiError as e:
        fail(f"広告作成に失敗: {e}", detail=e.payload)
    out({"ok": True, "ad_id": ad.get("id"), "creative_id": creative_id, "status": "PAUSED",
         "note": "ドラフト作成（停止中）。publish --confirm で出稿。"})


def _set_status(token, object_id, status):
    return _graph("POST", object_id, token=token, params={"status": status})


def cmd_publish(args, svc, user_id):
    acct = require_account(svc, user_id, args.account)
    target = args.campaign_id or args.adset_id or args.ad_id
    if not target:
        fail("--campaign-id / --adset-id / --ad-id のいずれかが必要です。")
    level = "campaign" if args.campaign_id else ("adset" if args.adset_id else "ad")

    if not args.confirm:
        out({
            "ok": False,
            "needs_approval": True,
            "level": level,
            "object_id": target,
            "approval_prompt": (
                f"この {level} を有効化すると広告課金が始まります。"
                f"予算上限と期間を確認の上、承認しますか？（承認時は --confirm を付けて再実行）"
            ),
        }, code=2)

    try:
        r = _set_status(acct["access_token"], target, "ACTIVE")
    except MetaApiError as e:
        fail(f"出稿（有効化）に失敗: {e}", detail=e.payload)
    svc.touch_last_used(user_id, args.account)
    out({"ok": True, "published": True, "level": level, "object_id": target, "status": "ACTIVE",
         "result": r})


def cmd_pause(args, svc, user_id):
    acct = require_account(svc, user_id, args.account)
    target = args.campaign_id or args.adset_id or args.ad_id
    if not target:
        fail("--campaign-id / --adset-id / --ad-id のいずれかが必要です。")
    try:
        r = _set_status(acct["access_token"], target, "PAUSED")
    except MetaApiError as e:
        fail(f"停止に失敗: {e}", detail=e.payload)
    out({"ok": True, "paused": True, "object_id": target, "status": "PAUSED", "result": r})


def cmd_insights(args, svc, user_id):
    acct = require_account(svc, user_id, args.account)
    target = args.campaign_id or args.adset_id or args.ad_id
    if target:
        path = f"{target}/insights"
    else:
        if not acct.get("ad_account_id"):
            fail("対象IDも ad_account_id も無いため insights を取得できません。")
        path = f"act_{acct['ad_account_id']}/insights"
    params = {
        "fields": "spend,impressions,clicks,ctr,cpc,cpm,reach,actions,cost_per_action_type",
        "date_preset": args.date_preset,
    }
    if args.level:
        params["level"] = args.level
    try:
        r = _graph("GET", path, token=acct["access_token"], params=params)
    except MetaApiError as e:
        fail(f"insights 取得に失敗: {e}", detail=e.payload)
    out({"ok": True, "date_preset": args.date_preset, "data": r.get("data", [])})


def cmd_ig_post(args, svc, user_id):
    """Instagram オーガニック投稿（3ステップ: container → 待機 → publish）。"""
    acct = require_account(svc, user_id, args.account)
    ig = acct.get("ig_user_id")
    if not ig:
        fail("ig_user_id が未設定。connect 時に --ig-user-id を指定してください。")
    if not args.image_url and not args.video_url:
        fail("--image-url または --video-url が必要です。")

    if not args.confirm:
        out({
            "ok": False, "needs_approval": True,
            "approval_prompt": "Instagram に公開投稿します。内容を確認の上、承認しますか？（--confirm を付けて再実行）",
            "caption": args.caption, "media": args.image_url or args.video_url,
        }, code=2)

    token = acct["access_token"]
    create_params = {"caption": args.caption or ""}
    if args.video_url:
        create_params["media_type"] = "REELS"
        create_params["video_url"] = args.video_url
    else:
        create_params["image_url"] = args.image_url

    try:
        container = _graph("POST", f"{ig}/media", token=token, params=create_params)
        creation_id = container.get("id")
        # 動画は処理完了まで待つ
        if args.video_url:
            for _ in range(30):
                st = _graph("GET", creation_id, token=token, params={"fields": "status_code"})
                if st.get("status_code") == "FINISHED":
                    break
                if st.get("status_code") == "ERROR":
                    fail("メディア処理でエラー（status_code=ERROR）", creation_id=creation_id)
                time.sleep(5)
        pub = _graph("POST", f"{ig}/media_publish", token=token, params={"creation_id": creation_id})
    except MetaApiError as e:
        fail(f"Instagram 投稿に失敗: {e}", detail=e.payload)
    svc.touch_last_used(user_id, args.account)
    out({"ok": True, "published": True, "ig_media_id": pub.get("id"), "creation_id": creation_id})


# ============================================================================
# argparse
# ============================================================================
def build_parser():
    p = argparse.ArgumentParser(description="Meta (Instagram/Facebook) 広告 CLI")
    p.add_argument("--user", default=None, help="ユーザーID（既定: $DAN_USER_ID → owner）")
    p.add_argument("--account", default="default", help="接続アカウントのラベル（既定: default）")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("connect-app", help="運営者の Meta Developer App を登録（1回）")
    s.add_argument("--app-id", required=True)
    s.add_argument("--app-secret", required=True)

    s = sub.add_parser("connect", help="テナントの広告アカウントを接続")
    s.add_argument("--short-token", help="Graph API Explorer等で取得した短期ユーザートークン（長期に交換して保存）")
    s.add_argument("--system-token", help="システムユーザートークン（無期限。そのまま保存）")
    s.add_argument("--ad-account-id", help="広告アカウントID（数値部分のみ。act_ は不要）")
    s.add_argument("--page-id", help="Facebook ページID（広告クリエイティブに必須）")
    s.add_argument("--ig-user-id", help="Instagram ビジネスアカウントの IG User ID")
    s.add_argument("--currency", help="通貨（未指定なら自動取得）")
    s.add_argument("--display-name")

    sub.add_parser("whoami", help="トークン妥当性とスコープを確認")
    sub.add_parser("accounts", help="ローカル保存済みの接続アカウント一覧")
    sub.add_parser("remote-accounts", help="トークンがアクセスできる広告アカウント一覧")

    s = sub.add_parser("campaign", help="キャンペーンをドラフト作成（PAUSED）")
    s.add_argument("--name", required=True)
    s.add_argument("--objective", default="OUTCOME_TRAFFIC")
    s.add_argument("--special-ad-categories", help='JSON配列。例 \'["HOUSING"]\'')

    s = sub.add_parser("adset", help="広告セットをドラフト作成（PAUSED）")
    s.add_argument("--campaign-id", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--daily-budget", type=float, required=True, help="1日予算（アカウント通貨の単位。JPYなら円）")
    s.add_argument("--billing-event", default="IMPRESSIONS")
    s.add_argument("--optimization-goal", default="LINK_CLICKS")
    s.add_argument("--countries", help="ターゲット国（カンマ区切り、既定 JP）")
    s.add_argument("--age-min", type=int)
    s.add_argument("--age-max", type=int)
    s.add_argument("--targeting-file", help="ターゲティングJSONファイル（指定時 countries 等を無視）")
    s.add_argument("--bid-amount", type=float, help="入札上限（通貨単位）。未指定なら LOWEST_COST_WITHOUT_CAP")
    s.add_argument("--start-time", help="ISO8601")
    s.add_argument("--end-time", help="ISO8601")
    s.add_argument("--link", help="（メモ用、未使用）")

    s = sub.add_parser("ad", help="広告（クリエイティブ＋Ad）をドラフト作成（PAUSED）")
    s.add_argument("--adset-id", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--link", required=True, help="遷移先URL")
    s.add_argument("--message", required=True, help="本文（プライマリテキスト）")
    s.add_argument("--headline", help="見出し")
    s.add_argument("--description", help="説明")
    s.add_argument("--cta", help="CTAタイプ 例 LEARN_MORE / SHOP_NOW / SIGN_UP")
    s.add_argument("--image", help="ローカル画像パス（アップロードして使用）")
    s.add_argument("--image-hash", help="アップロード済み画像のhash（--image と排他）")

    s = sub.add_parser("publish", help="⚠️出稿（有効化＝課金開始）。--confirm 必須")
    s.add_argument("--campaign-id")
    s.add_argument("--adset-id")
    s.add_argument("--ad-id")
    s.add_argument("--confirm", action="store_true", help="課金開始を承認")

    s = sub.add_parser("pause", help="停止（キルスイッチ）")
    s.add_argument("--campaign-id")
    s.add_argument("--adset-id")
    s.add_argument("--ad-id")

    s = sub.add_parser("insights", help="成果（spend/impressions/CTR/CPA等）取得")
    s.add_argument("--campaign-id")
    s.add_argument("--adset-id")
    s.add_argument("--ad-id")
    s.add_argument("--date-preset", default="last_7d")
    s.add_argument("--level", help="account/campaign/adset/ad")

    s = sub.add_parser("ig-post", help="⚠️Instagram オーガニック投稿（公開）。--confirm 必須")
    s.add_argument("--caption")
    s.add_argument("--image-url", help="公開画像URL")
    s.add_argument("--video-url", help="公開動画URL（Reelsとして投稿）")
    s.add_argument("--confirm", action="store_true", help="公開投稿を承認")

    return p


DISPATCH = {
    "connect-app": cmd_connect_app,
    "connect": cmd_connect,
    "whoami": cmd_whoami,
    "accounts": cmd_accounts,
    "remote-accounts": cmd_remote_accounts,
    "campaign": cmd_campaign,
    "adset": cmd_adset,
    "ad": cmd_ad,
    "publish": cmd_publish,
    "pause": cmd_pause,
    "insights": cmd_insights,
    "ig-post": cmd_ig_post,
}


def main():
    args = build_parser().parse_args()
    try:
        svc = get_service()
        user_id = resolve_user_id(args.user)
    except Exception as e:
        fail(f"初期化に失敗: {e}")
    DISPATCH[args.command](args, svc, user_id)


if __name__ == "__main__":
    main()
