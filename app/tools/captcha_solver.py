"""Generic CAPTCHA solver via the 2captcha service.

Supports reCAPTCHA v2, reCAPTCHA v3, reCAPTCHA Enterprise, hCaptcha and
Cloudflare Turnstile. The flow is:

    1. detect_captchas(page)      -- inspect the live DOM, find every widget
    2. TwoCaptchaClient.solve()   -- relay sitekey+url to 2captcha, poll for a token
    3. inject_token(page, ...)    -- write the token into the page + fire callbacks
    4. solve_page_captchas(page)  -- orchestrate all of the above for a whole page

This lets the browser tool auto-solve captchas instead of handing off to a human.
A single page may carry more than one widget (e.g. Contact Form 7 ships both
reCAPTCHA v3 and Cloudflare Turnstile); every detected widget is solved.

2captcha API reference: https://2captcha.com/2captcha-api
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

IN_URL = "https://2captcha.com/in.php"
RES_URL = "https://2captcha.com/res.php"

# how long to wait for a worker to return a token
DEFAULT_SOLVE_TIMEOUT = 180.0
POLL_INTERVAL = 5.0
FIRST_POLL_DELAY = 15.0


class CaptchaError(RuntimeError):
    """Base error for captcha solving failures."""


class CaptchaNotConfigured(CaptchaError):
    """Raised when no 2captcha API key is configured."""


@dataclass
class DetectedCaptcha:
    type: str  # recaptcha_v2 | recaptcha_v3 | recaptcha_enterprise | hcaptcha | turnstile
    sitekey: str
    action: Optional[str] = None
    response_selector: Optional[str] = None
    min_score: float = 0.3
    enterprise: bool = False
    raw: dict = field(default_factory=dict)
    # フレーム情報。captchaがiframe内に描画されている場合（Instagram/Metaの
    # 「本人確認にご協力ください」は fbsbx.com のiframe内）、2captchaへ渡す
    # pageurl も、トークンを注入する先も、親ページではなくこのフレームになる。
    frame: Any = None
    frame_url: Optional[str] = None

    def key(self) -> tuple:
        return (self.type, self.sitekey)


# --------------------------------------------------------------------------
# Detection
# --------------------------------------------------------------------------

_DETECT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  const push = (o) => {
    const k = o.type + '|' + o.sitekey;
    if (o.sitekey && !seen.has(k)) { seen.add(k); out.push(o); }
  };

  // --- script-derived reCAPTCHA v3 / enterprise sitekeys (api.js?render=KEY) ---
  const scripts = [...document.querySelectorAll('script[src]')].map(s => s.src);
  for (const src of scripts) {
    const m = src.match(/recaptcha\/(?:enterprise|api)\.js\?[^"']*render=([^&"'\s]+)/i);
    if (m && m[1] && m[1] !== 'explicit' && m[1] !== 'onload') {
      const isEnt = /enterprise\.js/i.test(src);
      push({ type: isEnt ? 'recaptcha_enterprise' : 'recaptcha_v3',
             sitekey: m[1], enterprise: isEnt, source: 'script-render' });
    }
  }
  const hasEnterprise = (typeof grecaptcha !== 'undefined' && !!grecaptcha.enterprise);

  // --- element-derived widgets ([data-sitekey]) ---
  for (const el of document.querySelectorAll('[data-sitekey]')) {
    const sitekey = el.getAttribute('data-sitekey');
    if (!sitekey) continue;
    const cls = (el.className || '') + '';
    const action = el.getAttribute('data-action') || null;
    if (/cf-turnstile/i.test(cls) || /^0x/.test(sitekey)) {
      push({ type: 'turnstile', sitekey, action, source: 'data-sitekey' });
    } else if (/h-captcha/i.test(cls)) {
      push({ type: 'hcaptcha', sitekey, source: 'data-sitekey' });
    } else {
      // g-recaptcha or generic: treat as v2 (visible/invisible checkbox)
      push({ type: hasEnterprise ? 'recaptcha_enterprise' : 'recaptcha_v2',
             sitekey, action, enterprise: hasEnterprise, source: 'data-sitekey' });
    }
  }

  // --- hcaptcha / turnstile via scripts when no data-sitekey element seen ---
  if ([...document.querySelectorAll('iframe[src]')].some(f => /hcaptcha\.com/i.test(f.src))) {
    const f = [...document.querySelectorAll('iframe[src]')].find(f => /hcaptcha\.com/i.test(f.src));
    const m = f && f.src.match(/sitekey=([^&]+)/);
    if (m) push({ type: 'hcaptcha', sitekey: m[1], source: 'iframe' });
  }

  // --- child recaptcha anchor iframes (widget rendered by the JS API, no
  //     [data-sitekey] element present) ---
  for (const f of document.querySelectorAll('iframe[src*="/recaptcha/"]')) {
    const src = f.src || '';
    const m = src.match(/[?&]k=([^&]+)/);
    if (!m) continue;
    const isEnt = /recaptcha\/enterprise\/(anchor|bframe)/i.test(src);
    push({ type: isEnt ? 'recaptcha_enterprise' : 'recaptcha_v2',
           sitekey: m[1], enterprise: isEnt, source: 'anchor-iframe' });
  }

  // --- response field presence (helps injection) ---
  const fields = {
    recaptcha: !!document.querySelector('textarea[name="g-recaptcha-response"], textarea#g-recaptcha-response, textarea[id^="g-recaptcha-response"]'),
    hcaptcha: !!document.querySelector('textarea[name="h-captcha-response"], input[name="h-captcha-response"]'),
    turnstile: !!document.querySelector('input[name="cf-turnstile-response"]'),
  };
  return { url: location.href, items: out, fields };
}
"""


async def _iter_frames(page) -> list:
    """Return every frame of the page, main frame first.

    Works with three page flavours:
      * a real Playwright Page      -> page.frames
      * the executor page proxy     -> await page.get_frames()
      * anything else               -> [page] (main document only)
    """
    getter = getattr(page, "get_frames", None)
    if getter is not None:
        try:
            frames = await getter()
            if frames:
                return list(frames)
        except Exception:
            logger.warning("get_frames() failed; falling back to main frame", exc_info=True)
        return [page]
    frames = getattr(page, "frames", None)
    if frames:
        return list(frames)
    return [page]


async def detect_captchas(page) -> list[DetectedCaptcha]:
    """Inspect the live DOM of every frame and return each captcha widget found.

    Scanning child frames matters: Instagram/Meta render their reCAPTCHA inside
    a cross-origin `iframe` (www.fbsbx.com), so a main-frame-only scan reports
    "no captcha detected" while the checkbox is plainly visible on screen.
    """
    result: list[DetectedCaptcha] = []
    seen: set[tuple] = set()
    for frame in await _iter_frames(page):
        try:
            raw = await frame.evaluate(_DETECT_JS)
        except Exception as exc:  # detached / restricted frame
            logger.debug("detect_captchas: frame eval failed: %s", exc)
            continue
        if not isinstance(raw, dict):
            continue
        frame_url = raw.get("url") or getattr(frame, "url", None) or None
        for it in raw.get("items") or []:
            if not isinstance(it, dict) or not it.get("sitekey"):
                continue
            k = (it["type"], it["sitekey"])
            if k in seen:
                continue
            seen.add(k)
            result.append(
                DetectedCaptcha(
                    type=it["type"],
                    sitekey=it["sitekey"],
                    action=it.get("action"),
                    enterprise=bool(it.get("enterprise")),
                    raw=it,
                    frame=frame,
                    frame_url=frame_url,
                )
            )
    logger.info("detect_captchas: found %d widget(s): %s",
                len(result), [(c.type, c.sitekey[:12], c.frame_url) for c in result])
    return result


# --------------------------------------------------------------------------
# 2captcha API client
# --------------------------------------------------------------------------

class TwoCaptchaClient:
    def __init__(self, api_key: Optional[str] = None, timeout: float = DEFAULT_SOLVE_TIMEOUT):
        self.api_key = api_key or settings.TWOCAPTCHA_API_KEY
        self.timeout = timeout
        if not self.api_key:
            raise CaptchaNotConfigured(
                "TWOCAPTCHA_API_KEY is not configured (set it in .env)."
            )

    async def get_balance(self) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(RES_URL, params={
                "key": self.api_key, "action": "getbalance", "json": 1})
            return r.json().get("request", "")

    async def solve_image(self, base64_image: str, **opts: Any) -> str:
        """Solve a classic image-to-text captcha (distorted letters).

        base64_image: the captcha image as base64 (no data: prefix).
        opts: optional 2captcha hints e.g. regsense=1, numeric=1/2/3/4,
              min_len, max_len, phrase, lang, language.
        """
        params: dict[str, Any] = {"method": "base64", "body": base64_image}
        params.update(opts)
        return await self.solve(params)

    async def solve(self, in_params: dict[str, Any]) -> str:
        """Submit a task and poll until a token is ready. Returns the token."""
        params = {"key": self.api_key, "json": 1, **in_params}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(IN_URL, data=params)
            data = r.json()
            if data.get("status") != 1:
                raise CaptchaError(f"2captcha submit failed: {data.get('request')}")
            cid = data["request"]
            logger.info("2captcha task submitted id=%s method=%s", cid, in_params.get("method"))

            deadline = asyncio.get_event_loop().time() + self.timeout
            await asyncio.sleep(FIRST_POLL_DELAY)
            while True:
                rr = await client.get(RES_URL, params={
                    "key": self.api_key, "action": "get", "id": cid, "json": 1})
                rd = rr.json()
                if rd.get("status") == 1:
                    logger.info("2captcha task id=%s solved", cid)
                    return rd["request"]
                req = rd.get("request")
                if req != "CAPCHA_NOT_READY":
                    raise CaptchaError(f"2captcha solve error (id={cid}): {req}")
                if asyncio.get_event_loop().time() > deadline:
                    raise CaptchaError(f"2captcha solve timeout (id={cid})")
                await asyncio.sleep(POLL_INTERVAL)


def build_in_params(c: DetectedCaptcha, page_url: str) -> dict[str, Any]:
    """Translate a DetectedCaptcha into 2captcha in.php parameters."""
    if c.type in ("recaptcha_v2", "recaptcha_v3", "recaptcha_enterprise"):
        p: dict[str, Any] = {
            "method": "userrecaptcha",
            "googlekey": c.sitekey,
            "pageurl": page_url,
        }
        if c.type == "recaptcha_v3":
            p["version"] = "v3"
            p["min_score"] = c.min_score
            if c.action:
                p["action"] = c.action
        if c.type == "recaptcha_enterprise" or c.enterprise:
            p["enterprise"] = 1
            if c.action:
                p["action"] = c.action
        return p
    if c.type == "hcaptcha":
        return {"method": "hcaptcha", "sitekey": c.sitekey, "pageurl": page_url}
    if c.type == "turnstile":
        p = {"method": "turnstile", "sitekey": c.sitekey, "pageurl": page_url}
        if c.action:
            p["action"] = c.action
        return p
    raise CaptchaError(f"Unsupported captcha type: {c.type}")


# --------------------------------------------------------------------------
# Token injection
# --------------------------------------------------------------------------

_INJECT_RECAPTCHA_JS = r"""
(token) => {
  // fill every g-recaptcha-response field
  const fields = document.querySelectorAll(
    'textarea[name="g-recaptcha-response"], textarea#g-recaptcha-response, textarea[id^="g-recaptcha-response"]');
  fields.forEach(f => { f.value = token; f.innerHTML = token;
    f.dispatchEvent(new Event('input', {bubbles:true}));
    f.dispatchEvent(new Event('change', {bubbles:true})); });
  // override grecaptcha.execute/getResponse so flows that re-read the answer at
  // submit time get our pre-solved token instead of generating a new one.
  try {
    const make = (g) => {
      if (!g || g.__danPatched) return;
      g.execute = function() { return Promise.resolve(token); };
      g.getResponse = function() { return token; };
      g.__danPatched = true;
      if (g.enterprise) make(g.enterprise);
    };
    if (typeof grecaptcha !== 'undefined') make(grecaptcha);
  } catch (e) {}
  // v2 checkbox: fire the callback the site handed to grecaptcha.render().
  // Filling the textarea alone leaves the submit button disabled on sites that
  // wait for that callback (Instagram/Meta's verification dialog does).
  let fired = 0;
  try {
    const cfg = window.___grecaptcha_cfg;
    const roots = [];
    if (cfg && cfg.clients) { for (const k in cfg.clients) roots.push(cfg.clients[k]); }
    const visited = new Set();
    const walk = (o, depth) => {
      if (!o || depth > 6 || typeof o !== 'object' || visited.has(o)) return;
      visited.add(o);
      for (const k in o) {
        let v;
        try { v = o[k]; } catch (e) { continue; }
        if (typeof v === 'function') {
          if (/callback/i.test(k)) { try { v(token); fired++; } catch (e) {} }
        } else if (v && typeof v === 'object') {
          walk(v, depth + 1);
        }
      }
    };
    roots.forEach(r => walk(r, 0));
  } catch (e) {}
  return { filled: fields.length, callbacks: fired };
}
"""

_INJECT_HCAPTCHA_JS = r"""
(token) => {
  const sels = ['textarea[name="h-captcha-response"]','input[name="h-captcha-response"]',
                'textarea[name="g-recaptcha-response"]'];
  let n = 0;
  sels.forEach(s => document.querySelectorAll(s).forEach(f => {
    f.value = token; n++;
    f.dispatchEvent(new Event('input',{bubbles:true}));
    f.dispatchEvent(new Event('change',{bubbles:true}));
  }));
  return n;
}
"""

_INJECT_TURNSTILE_JS = r"""
(token) => {
  let n = 0;
  document.querySelectorAll('input[name="cf-turnstile-response"], input[id^="cf-chl-widget"]').forEach(f => {
    f.value = token; n++;
    f.dispatchEvent(new Event('input',{bubbles:true}));
    f.dispatchEvent(new Event('change',{bubbles:true}));
  });
  // some plugins disable the submit button until turnstile resolves -> re-enable
  document.querySelectorAll('button[disabled], input[type=submit][disabled]').forEach(b => {
    b.disabled = false; b.removeAttribute('disabled');
  });
  return n;
}
"""


async def inject_token(page, c: DetectedCaptcha, token: str) -> dict:
    """Write the token into the frame that actually hosts the widget."""
    target = c.frame or page
    if c.type in ("recaptcha_v2", "recaptcha_v3", "recaptcha_enterprise"):
        res = await target.evaluate(_INJECT_RECAPTCHA_JS, token)
        return res if isinstance(res, dict) else {"filled": res, "callbacks": 0}
    if c.type == "hcaptcha":
        return {"filled": await target.evaluate(_INJECT_HCAPTCHA_JS, token), "callbacks": 0}
    if c.type == "turnstile":
        return {"filled": await target.evaluate(_INJECT_TURNSTILE_JS, token), "callbacks": 0}
    raise CaptchaError(f"Unsupported captcha type: {c.type}")


# --------------------------------------------------------------------------
# Image (distorted-text) captcha
# --------------------------------------------------------------------------

# Capture the *displayed* captcha image as base64 via canvas. We must NOT
# re-fetch the src (captcha images are one-time; re-fetching yields a different
# challenge). Returns null when no image is found, {ok:false} when the canvas
# is tainted (cross-origin), {ok:true,data:...} otherwise.
_EXTRACT_IMG_JS = r"""
(selector) => {
  let img = selector ? document.querySelector(selector) : null;
  if (!img) {
    const imgs = [...document.querySelectorAll('img')];
    img = imgs.find(e => /captcha|vcode|authcode|seccode|verif|nocache/i.test(
              ((e.src||'')+(e.alt||'')+(e.className||'')+(e.id||''))));
    if (!img) img = imgs.find(e => {
      const w = e.naturalWidth || e.width, h = e.naturalHeight || e.height;
      return w > 40 && w < 360 && h > 14 && h < 130 && e.closest('form');
    });
  }
  if (!img) return null;
  try {
    const c = document.createElement('canvas');
    c.width = img.naturalWidth || img.width;
    c.height = img.naturalHeight || img.height;
    c.getContext('2d').drawImage(img, 0, 0);
    return { ok: true, data: c.toDataURL('image/png') };
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}
"""

_FILL_INPUT_JS = r"""
(args) => {
  const { selector, value } = args;
  let inp = selector ? document.querySelector(selector) : null;
  if (!inp) {
    const inputs = [...document.querySelectorAll('input[type=text], input:not([type]), input[type=tel]')]
      .filter(e => e.offsetParent !== null);
    inp = inputs.find(e => /captcha|vcode|authcode|seccode|verif/i.test(
              ((e.name||'')+(e.id||'')+(e.placeholder||''))))
        || inputs.find(e => !e.value);
  }
  if (!inp) return 0;
  inp.focus();
  inp.value = value;
  inp.dispatchEvent(new Event('input', { bubbles: true }));
  inp.dispatchEvent(new Event('change', { bubbles: true }));
  return 1;
}
"""


async def solve_image_captcha(
    page,
    image_selector: Optional[str] = None,
    input_selector: Optional[str] = None,
    api_key: Optional[str] = None,
    fill: bool = True,
    **opts: Any,
) -> dict[str, Any]:
    """Solve a distorted-text image captcha and (optionally) fill its input.

    Returns {"found": bool, "text": str|None, "filled": int}.
    Raises CaptchaError if an image is found but cannot be captured/solved.
    """
    # 画像CAPTCHAもiframe内に置かれることがあるので、見つかるまで全フレームを見る。
    target = None
    extracted = None
    for frame in await _iter_frames(page):
        try:
            found = await frame.evaluate(_EXTRACT_IMG_JS, image_selector)
        except Exception:
            continue
        if found:
            target, extracted = frame, found
            break
    if not extracted:
        return {"found": False, "text": None, "filled": 0}
    if not extracted.get("ok"):
        raise CaptchaError(
            f"画像CAPTCHAを取得できませんでした（canvasがcross-originで汚染）: {extracted.get('error')}"
        )
    data_url = extracted["data"]
    b64 = data_url.split(",", 1)[1] if "," in data_url else data_url

    client = TwoCaptchaClient(api_key=api_key)
    text = await client.solve_image(b64, **opts)
    filled = 0
    if fill:
        filled = await target.evaluate(_FILL_INPUT_JS, {"selector": input_selector, "value": text})
    logger.info("image captcha solved: %r (filled %d input)", text, filled)
    return {"found": True, "text": text, "filled": filled}


# --------------------------------------------------------------------------
# High-level orchestration
# --------------------------------------------------------------------------

async def solve_page_captchas(
    page,
    page_url: Optional[str] = None,
    api_key: Optional[str] = None,
    raise_on_empty: bool = False,
) -> dict[str, Any]:
    """Detect, solve and inject every captcha on the page.

    Returns a summary dict: {"solved": [...], "count": n, "tokens": {type: token}}.
    """
    page_url = page_url or page.url
    detected = await detect_captchas(page)
    if not detected:
        if raise_on_empty:
            raise CaptchaError("No captcha detected on the page.")
        return {"solved": [], "count": 0, "tokens": {}, "message": "no captcha detected"}

    client = TwoCaptchaClient(api_key=api_key)
    solved, tokens = [], {}
    for c in detected:
        # 2captcha must be told the URL of the document the widget lives in.
        # For an in-iframe widget that is the frame URL, not the top page URL.
        target_url = c.frame_url or page_url
        params = build_in_params(c, target_url)
        token = await client.solve(params)
        injected = await inject_token(page, c, token)
        solved.append({
            "type": c.type,
            "sitekey": c.sitekey,
            "pageurl": target_url,
            "injected_fields": injected.get("filled", 0),
            "callbacks_fired": injected.get("callbacks", 0),
        })
        tokens[c.type] = token
        logger.info("solved+injected %s at %s (%s field(s), %s callback(s))",
                    c.type, target_url, injected.get("filled"), injected.get("callbacks"))

    return {"solved": solved, "count": len(solved), "tokens": tokens}


async def get_balance(api_key: Optional[str] = None) -> str:
    return await TwoCaptchaClient(api_key=api_key).get_balance()
