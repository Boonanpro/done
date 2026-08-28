"""Instagram への送信アダプタ（DM / コメント）。公式APIなし。

方式は instagram_inbox と同じ: 巡回用プロファイル（ログイン済み）でブラウザを開き、
Web版インスタ自身が使う内部エンドポイントを fetch する。画面のDOMには依存しない。

- DM:      POST /api/v1/direct_v2/threads/broadcast/text/  (thread_ids または recipient_users)
- コメント: POST /api/v1/web/comments/<media_id>/add/        (replied_to_comment_id で返信)

同じプロファイルを poller と同時に開くと Chromium のプロファイルロックで失敗するので、
プロファイル横断のファイルロック（`account_lock`）で直列化する。poller も同じロックを使う。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_LOCK_STALE_SEC = 5 * 60
_LOCK_WAIT_SEC = 120


@contextlib.asynccontextmanager
async def account_lock(account: str):
    """アカウント別のプロセス横断ロック（O_EXCL のロックファイル）。"""
    from app.services.instagram_inbox import profile_dir_for
    d = profile_dir_for(account)
    d.mkdir(parents=True, exist_ok=True)
    lock = d.parent / f"{d.name}.lock"
    deadline = time.time() + _LOCK_WAIT_SEC
    fd = None
    while True:
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > _LOCK_STALE_SEC:
                    lock.unlink(missing_ok=True)
                    continue
            except FileNotFoundError:
                continue
            if time.time() > deadline:
                raise TimeoutError(f"Instagram アカウント {account} のブラウザが使用中です（ロック待ちタイムアウト）")
            await asyncio.sleep(2)
    try:
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock.unlink()


_FETCH_JS = """
async (args) => {
  const csrf = (document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '';
  const headers = {
    'X-IG-App-ID': args.appId,
    'X-Requested-With': 'XMLHttpRequest',
    'X-CSRFToken': csrf,
    'X-Instagram-AJAX': '1',
    'X-ASBD-ID': '129477',
  };
  const init = {method: args.method, headers, credentials: 'include'};
  if (args.form) {
    headers['Content-Type'] = 'application/x-www-form-urlencoded';
    init.body = new URLSearchParams(args.form).toString();
  }
  const res = await fetch(args.url, init);
  return {status: res.status, contentType: res.headers.get('content-type') || '',
          body: (await res.text()).slice(0, 200000)};
}
"""


async def _api(page, method: str, url: str, form: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    from app.services.instagram_inbox import IG_APP_ID
    r = await page.evaluate(_FETCH_JS, {"appId": IG_APP_ID, "method": method, "url": url, "form": form})
    if r.get("status") != 200 or "json" not in (r.get("contentType") or ""):
        raise RuntimeError(f"Instagram API {method} {url} → HTTP {r.get('status')}: {(r.get('body') or '')[:200]}")
    data = json.loads(r["body"])
    if data.get("status") not in (None, "ok"):
        raise RuntimeError(f"Instagram API {url} → {data}")
    return data


async def _user_pk(page, handle: str) -> str:
    h = handle.lstrip("@").strip()
    data = await _api(page, "GET", f"/api/v1/users/web_profile_info/?username={h}")
    pk = ((data.get("data") or {}).get("user") or {}).get("id")
    if not pk:
        raise RuntimeError(f"@{h} のユーザーIDを取得できませんでした")
    return str(pk)


_SHORTCODE_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def media_id_from_url(post_url: str) -> str:
    """投稿URL (/p/<code>/ or /reel/<code>/) → media pk。"""
    m = re.search(r"/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", post_url)
    if not m:
        raise ValueError(f"投稿URLからショートコードを取れません: {post_url}")
    n = 0
    for ch in m.group(1):
        n = n * 64 + _SHORTCODE_ALPHABET.index(ch)
    return str(n)


async def _with_session(account: str, user_id: Optional[str], fn):
    from playwright.async_api import async_playwright
    from app.services.instagram_inbox import ensure_logged_in, open_session
    async with account_lock(account):
        async with async_playwright() as pw:
            context = None
            try:
                context, page = await open_session(account, pw)
                if not await ensure_logged_in(page, account, user_id):
                    raise RuntimeError(f"Instagram {account} にログインできませんでした")
                return await fn(page)
            finally:
                if context is not None:
                    with contextlib.suppress(Exception):
                        await context.close()


async def send_dm(account: str, text: str, *, thread_id: Optional[str] = None,
                  handle: Optional[str] = None, user_id: Optional[str] = None) -> Dict[str, Any]:
    """DM を送る。thread_id（既存スレッド）か handle（相手ユーザーネーム）のどちらか必須。
    戻り値: {thread_id, item_id, handle}"""
    if not thread_id and not handle:
        raise ValueError("thread_id か handle が必要です")

    async def _do(page):
        form = {
            "action": "send_item",
            "text": text,
            "client_context": str(random.randint(10**17, 10**18 - 1)),
            "mutation_token": str(random.randint(10**17, 10**18 - 1)),
            "is_shh_mode": "0",
            "send_attribution": "direct_thread",
            "offline_threading_id": str(random.randint(10**17, 10**18 - 1)),
        }
        if thread_id:
            form["thread_ids"] = json.dumps([str(thread_id)])
        else:
            pk = await _user_pk(page, handle)
            form["recipient_users"] = json.dumps([[pk]])
        data = await _api(page, "POST", "/api/v1/direct_v2/threads/broadcast/text/", form)
        payload = data.get("payload") or {}
        return {"thread_id": str(payload.get("thread_id") or thread_id or ""),
                "item_id": str(payload.get("item_id") or ""), "handle": (handle or "").lstrip("@")}

    return await _with_session(account, user_id, _do)


async def post_comment(account: str, text: str, *, post_url: str,
                       reply_to_comment_id: Optional[str] = None,
                       user_id: Optional[str] = None) -> Dict[str, Any]:
    """投稿にコメント（reply_to_comment_id があればそのコメントへの返信）。
    戻り値: {media_id, comment_id}"""
    media_id = media_id_from_url(post_url)

    async def _do(page):
        form = {"comment_text": text}
        if reply_to_comment_id:
            form["replied_to_comment_id"] = str(reply_to_comment_id)
        data = await _api(page, "POST", f"/api/v1/web/comments/{media_id}/add/", form)
        return {"media_id": media_id, "comment_id": str(data.get("id") or "")}

    return await _with_session(account, user_id, _do)


async def delete_comment(account: str, *, post_url: str, comment_id: str, user_id: Optional[str] = None) -> None:
    media_id = media_id_from_url(post_url)

    async def _do(page):
        await _api(page, "POST", f"/api/v1/web/comments/{media_id}/delete/{comment_id}/", {})

    await _with_session(account, user_id, _do)
