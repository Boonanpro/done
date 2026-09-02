# -*- coding: utf-8 -*-
"""Instagram DM 受信箱の読み取り（公式APIなしでの検知の土台）。

方式:
    Web版インスタ自身が受信箱一覧・スレッド表示に使う内部エンドポイント
    (`/api/v1/direct_v2/inbox/`, `/api/v1/direct_v2/threads/<id>/`) を、
    ログイン済みブラウザの中から fetch する。

    - 画面のHTML構造に依存しないので、デザイン変更で壊れにくい
    - 1巡回あたりHTTPリクエスト数回。人がアプリを開くより遥かに軽い

ログインについて:
    ダンの自力ログイン基盤（認証情報DB + 2captcha + メールOTP）をそのまま使う。
    Instagram はログイン時に reCAPTCHA チャレンジを挟むことがある（実測 2026-08-07）ので、
    captcha が出たら solve_page_captchas で解いて続行する。ユーザーの手を借りない。
    ログイン結果はプロファイルに永続するので、毎回ログインするわけではない。

このモジュールは「ログインして読む」までを担当する。誰の返事か・どうするかは
instagram_poller が判断する。
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

IG_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
# Web版インスタが自身のAPI呼び出しに付けるアプリID（ブラウザと同じ振る舞いにする）
IG_APP_ID = "936619743392459"

_INBOX_JS = """
async (limit) => {
  const url = '/api/v1/direct_v2/inbox/?persistentBadging=true&limit=' + limit
            + '&thread_message_limit=1';
  const res = await fetch(url, {
    headers: {'X-IG-App-ID': '%s', 'X-Requested-With': 'XMLHttpRequest'},
    credentials: 'include',
  });
  return {
    status: res.status,
    contentType: res.headers.get('content-type') || '',
    body: (await res.text()).slice(0, 500000),
  };
}
""" % IG_APP_ID


_THREAD_JS = """
async (args) => {
  const url = '/api/v1/direct_v2/threads/' + args.threadId + '/?limit=' + args.limit;
  const res = await fetch(url, {
    headers: {'X-IG-App-ID': '%s', 'X-Requested-With': 'XMLHttpRequest'},
    credentials: 'include',
  });
  return {
    status: res.status,
    contentType: res.headers.get('content-type') || '',
    body: (await res.text()).slice(0, 500000),
  };
}
""" % IG_APP_ID

# ログインフォームの実DOM（2026-08-07 実地調査。推測で書かないこと）:
#   #login_form input[name="email"] / input[name="pass"]
#   送信は button[type=submit] が非表示で、実体は div[role=button] の「ログイン」
_LOGIN_USER_SEL = "#login_form input[name='email']"
_LOGIN_PASS_SEL = "#login_form input[name='pass']"
_LOGIN_SUBMIT_SEL = "div[role='button']:has-text('ログイン')"


def profile_dir_for(account: str) -> Path:
    """巡回専用プロファイル。ダンの作業用ブラウザとは分けて衝突を避ける。"""
    safe = "".join(ch for ch in account if ch.isalnum() or ch in "._-")
    return Path.home() / ".ai_secretary" / f"ig_poll--{safe}"


def profile_exists(account: str) -> bool:
    return profile_dir_for(account).exists()


async def fetch_inbox_json(page, limit: int = 20) -> Optional[Dict[str, Any]]:
    """受信箱JSONを取得。未ログイン(HTMLが返る)なら None。"""
    result = await page.evaluate(_INBOX_JS, limit)
    if result.get("status") != 200:
        return None
    if "json" not in (result.get("contentType") or ""):
        return None  # ログインページのHTMLが返っている
    try:
        return json.loads(result["body"])
    except Exception:
        logger.warning("[ig] inbox response was not parseable JSON")
        return None


def parse_threads(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """受信箱JSONを、扱いやすいスレッド要約に落とす。

    返す各要素:
      thread_id, participants(list[str]), read_state(int|None),
      last_ts(int マイクロ秒), last_from(str), last_text(str),
      item_type(str), is_from_me(bool)
    """
    viewer_pk = str(((data.get("viewer") or {}).get("pk")) or "")
    out: List[Dict[str, Any]] = []
    for thread in ((data.get("inbox") or {}).get("threads") or []):
        last = thread.get("last_permanent_item") or {}
        items = thread.get("items") or []
        if not last and items:
            last = items[0]
        sender = str(last.get("user_id") or "")
        out.append({
            "thread_id": str(thread.get("thread_id") or ""),
            "participants": [
                u.get("username") for u in (thread.get("users") or []) if u.get("username")
            ],
            "read_state": thread.get("read_state"),
            "last_ts": int(last.get("timestamp") or 0),
            "last_from": sender,
            "last_text": (last.get("text") or ""),
            "item_type": last.get("item_type") or "",
            "is_from_me": bool(viewer_pk and sender == viewer_pk),
        })
    return out


def viewer_username(data: Dict[str, Any]) -> Optional[str]:
    return ((data.get("viewer") or {}).get("username")) or None


async def fetch_thread_json(page, thread_id: str, limit: int = 15) -> Optional[Dict[str, Any]]:
    """スレッドの直近メッセージを取得（会話の文脈をダンに渡すため）。"""
    result = await page.evaluate(_THREAD_JS, {"threadId": thread_id, "limit": limit})
    if result.get("status") != 200 or "json" not in (result.get("contentType") or ""):
        return None
    try:
        return json.loads(result["body"])
    except Exception:
        return None


def parse_thread_messages(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """スレッドJSONを古い順のメッセージ列にする。"""
    thread = data.get("thread") or {}
    viewer_pk = str(data.get("viewer_id") or "")
    users = {str(u.get("pk")): u.get("username") for u in (thread.get("users") or [])}
    out: List[Dict[str, Any]] = []
    for item in reversed(thread.get("items") or []):
        sender = str(item.get("user_id") or "")
        out.append({
            "ts": int(item.get("timestamp") or 0),
            "from": users.get(sender) or ("自分" if sender == viewer_pk else sender),
            "is_from_me": bool(viewer_pk and sender == viewer_pk),
            "text": item.get("text") or "",
            "item_type": item.get("item_type") or "",
        })
    return out


def _credentials_for(account: str) -> Dict[str, Any]:
    """認証情報DBから id/password を取り出す。"""
    from app.services.supabase_client import get_supabase_client
    client = get_supabase_client()
    # 台帳のアカウント名は "ajp.gdw"、認証情報の service_name は "instagram_ajp_gdw" のように
    # 揺れるので別名を順に試す（2026-08-28 実測: 直名だけだと巡回も送信も LookupError）
    safe = "".join(ch if ch.isalnum() else "_" for ch in account).strip("_")
    candidates = [account, f"instagram_{safe}", safe]
    rows = []
    for name in dict.fromkeys(candidates):
        rows = (
            client.client.table("credentials").select("*")
            .eq("service_name", name).limit(1).execute().data or []
        )
        if rows:
            break
    if not rows:
        raise LookupError(f"認証情報が見つからない: {account}（試行: {', '.join(dict.fromkeys(candidates))}）")
    return json.loads(client.encryption.decrypt(rows[0]["encrypted_data"]))


async def _handle_captcha(page) -> bool:
    """captcha が出ていれば 2captcha で解いて注入する。解いたら True。"""
    try:
        from app.tools.captcha_solver import solve_page_captchas
        result = await solve_page_captchas(page)
        if result.get("count"):
            logger.info("[ig] captcha solved: %s", result.get("count"))
            await page.wait_for_timeout(5000)
            return True
    except Exception as exc:
        logger.warning("[ig] captcha solving failed: %s", exc)
    return False


async def _handle_otp(page, account: str, user_id: Optional[str], login_id: str) -> bool:
    """2FA コード入力欄が出ていれば、メールOTPを自動取得して入力する。"""
    code_input = None
    for selector in ("input[name='verificationCode']", "input[name='security_code']",
                     "input[autocomplete='one-time-code']"):
        try:
            if await page.is_visible(selector, timeout=2000):
                code_input = selector
                break
        except Exception:
            continue
    if not code_input:
        return False

    logger.info("[ig] 2FA code requested; fetching OTP from email")
    try:
        from app.services.otp_service import get_otp_service
        otp_service = get_otp_service()
        email_address = login_id if "@" in login_id else None
        code = await otp_service.wait_for_otp(
            user_id=user_id or "",
            service="instagram",
            source="email",
            timeout_seconds=180,
            email_address=email_address,
        )
    except Exception as exc:
        logger.warning("[ig] OTP retrieval failed: %s", exc)
        return False

    if not code:
        logger.warning("[ig] OTP not received within timeout")
        return False
    await page.fill(code_input, code)
    await page.wait_for_timeout(800)
    try:
        await page.click("div[role='button']:has-text('確認'), button[type='submit']", timeout=8000)
    except Exception:
        await page.keyboard.press("Enter")
    await page.wait_for_timeout(8000)
    return True


async def ensure_logged_in(page, account: str, user_id: Optional[str] = None) -> bool:
    """ログイン済みなら何もしない。未ログインなら自力でログインする。

    ダンの既存の自力ログイン基盤（認証情報DB + 2captcha + メールOTP）を使う。
    ユーザーの手を借りない。成功したら True。
    """
    if await fetch_inbox_json(page, limit=1) is not None:
        return True

    creds = _credentials_for(account)
    login_id = str(creds.get("id") or "")
    password = str(creds.get("password") or "")
    if not login_id or not password:
        logger.error("[ig] %s: 認証情報が不完全", account)
        return False

    logger.info("[ig] %s: logging in as %s", account, login_id)
    await page.goto("https://www.instagram.com/accounts/login/",
                    wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(4000)
    await _handle_captcha(page)  # ログインフォーム自体に captcha が乗るケース

    try:
        await page.fill(_LOGIN_USER_SEL, login_id, timeout=20000)
        await page.wait_for_timeout(500)
        await page.fill(_LOGIN_PASS_SEL, password, timeout=20000)
        await page.wait_for_timeout(500)
        await page.click(_LOGIN_SUBMIT_SEL, timeout=20000)
    except Exception as exc:
        logger.error("[ig] %s: ログインフォーム操作に失敗: %s", account, exc)
        return False

    # 送信後は captcha チャレンジ / 2FA / そのままログイン成功 のいずれか。
    # 最大3周してそれぞれ処理する。
    for _ in range(3):
        await page.wait_for_timeout(8000)
        if await fetch_inbox_json(page, limit=1) is not None:
            logger.info("[ig] %s: ログイン成功", account)
            return True
        if "recaptcha" in page.url or "challenge" in page.url:
            if await _handle_captcha(page):
                continue
        if await _handle_otp(page, account, user_id, login_id):
            continue
        await _handle_captcha(page)

    ok = await fetch_inbox_json(page, limit=1) is not None
    if not ok:
        logger.error("[ig] %s: ログインできなかった (url=%s)", account, page.url)
    return ok


async def open_session(account: str, playwright):
    """巡回用プロファイルでブラウザを開く。画面外に置いて作業の邪魔をしない。

    プロファイルが無ければ作る（初回はここでログインが走る）。
    戻り値: (context, page)。呼び出し側が context.close() すること。
    """
    profile = profile_dir_for(account)
    profile.mkdir(parents=True, exist_ok=True)
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        headless=False,  # headless はインスタに検知されやすいので使わない
        args=[
            "--disable-blink-features=AutomationControlled",
            "--window-position=-32000,-32000",  # 画面外＝勝手にウィンドウが出ない
        ],
        viewport={"width": 1280, "height": 900},
        user_agent=IG_UA,
    )
    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=60000)
    await page.wait_for_timeout(3000)
    return context, page
