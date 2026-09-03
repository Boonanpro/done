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
import base64
import logging
import random
import re
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
    # hCaptcha Enterprise の署名付きデータ。Epic(Talon) のようにこれを使うサイトでは、
    # トークンが「rqdata を発行したセッション」に紐づくため、これを 2captcha へ
    # 渡さずに解いたトークンは画像を全問正解しても無効になる。
    rqdata: Optional[str] = None
    invisible: bool = False
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
  const seen = new Map();
  const push = (o) => {
    const k = o.type + '|' + o.sitekey;
    if (!o.sitekey) return;
    const prev = seen.get(k);
    if (prev) {
      // A widget is discovered more than once (checkbox frame + challenge
      // frame). Keep the richest record: rqdata appears on only one of them and
      // dropping it would silently produce an unusable Enterprise token.
      if (o.rqdata && !prev.rqdata) prev.rqdata = o.rqdata;
      if (o.invisible) prev.invisible = true;
      return;
    }
    seen.set(k, o);
    out.push(o);
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

  // --- hcaptcha via its own iframes (JS-rendered widget, no [data-sitekey]) ---
  // invisible hCaptcha renders TWO iframes: the checkbox one carries no sitekey,
  // the challenge one does. Scan every hcaptcha frame instead of only the first,
  // otherwise a visible challenge is reported as "no captcha detected".
  //
  // Enterprise widgets also carry `rqdata`, a signed blob that binds the answer
  // to this session. A token solved WITHOUT it is rejected no matter how well
  // the images were answered (Epic's Talon works this way), so capture it here
  // and hand it to the solver.
  for (const f of document.querySelectorAll('iframe[src]')) {
    if (!/hcaptcha\.com/i.test(f.src)) continue;
    const m = f.src.match(/sitekey=([^&#]+)/);
    if (!m) continue;
    const rq = f.src.match(/[?&]rqdata=([^&#]+)/);
    const inv = /[?&]size=invisible/i.test(f.src);
    push({ type: 'hcaptcha', sitekey: decodeURIComponent(m[1]),
           rqdata: rq ? decodeURIComponent(rq[1]) : null,
           invisible: inv, source: 'iframe' });
  }

  // --- hcaptcha rqdata rendered through the JS API (not in any iframe src) ---
  // Sites that call hcaptcha.render(el, {rqdata}) keep the blob in a config
  // object or a data attribute instead of the frame URL.
  try {
    for (const el of document.querySelectorAll('[data-hcaptcha-rqdata], [data-rqdata]')) {
      const rq = el.getAttribute('data-hcaptcha-rqdata') || el.getAttribute('data-rqdata');
      if (!rq) continue;
      const sk = el.getAttribute('data-sitekey');
      if (sk) {
        push({ type: 'hcaptcha', sitekey: sk, rqdata: rq, source: 'data-rqdata' });
      } else {
        // rqdata without a sitekey of its own: attach it to the hCaptcha widget
        // already found, otherwise the blob is lost.
        for (const o of out) { if (o.type === 'hcaptcha' && !o.rqdata) o.rqdata = rq; }
      }
    }
  } catch (e) {}

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
                    rqdata=it.get("rqdata") or None,
                    invisible=bool(it.get("invisible")),
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

def _parse_coordinates(raw: Any) -> list[dict[str, int]]:
    """Turn 2captcha's coordinate answer into click points.

    Two shapes come back depending on the response mode. With ``json=1`` a
    coordinates task returns ``request`` already decoded as a list of dicts —
    ``[{"x": "87", "y": "129"}]``, with the numbers as strings. Plain-text mode
    returns ``coordinates:x=87,y=129;x=245,y=64`` (the ``coordinates:`` prefix
    is not always present). Handle both rather than assuming one exact shape.
    """
    if not raw:
        return []
    if isinstance(raw, dict):
        raw = raw.get("coordinates") or raw.get("request") or []
    if isinstance(raw, (list, tuple)):
        points: list[dict[str, int]] = []
        for it in raw:
            if not isinstance(it, dict):
                continue
            try:
                points.append({"x": int(float(it["x"])), "y": int(float(it["y"]))})
            except (KeyError, TypeError, ValueError):
                continue
        return points
    body = str(raw).split("coordinates:", 1)[-1]
    points: list[dict[str, int]] = []
    for chunk in re.split(r"[;|]", body):
        xs = re.search(r"x\s*=\s*(-?\d+)", chunk, re.I)
        ys = re.search(r"y\s*=\s*(-?\d+)", chunk, re.I)
        if xs and ys:
            points.append({"x": int(xs.group(1)), "y": int(ys.group(1))})
    return points


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

    async def solve_coordinates(
        self,
        base64_image: str,
        instruction: str = "",
        lang: str = "en",
    ) -> list[dict[str, int]]:
        """Ask a human worker WHERE to click on this image.

        Token methods ("solve this hCaptcha for sitekey X") fail when the
        challenge is a variant the workers have no scripted answer for — Epic's
        drag-to-fit and count-the-animals puzzles come back
        ERROR_CAPTCHA_UNSOLVABLE. This method sidesteps the challenge *type*
        entirely: it hands over a screenshot plus the on-screen instruction and
        gets back click points, which works for any puzzle a person can read.

        Returns a list of {"x": int, "y": int} in image pixel coordinates.
        """
        params: dict[str, Any] = {
            "method": "base64",
            "body": base64_image,
            "coordinatescaptcha": 1,
            "lang": lang,
        }
        if instruction:
            # textinstructions is what the worker is shown alongside the image.
            params["textinstructions"] = instruction[:900]
        raw = await self.solve(params)
        return _parse_coordinates(raw)

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


def build_in_params(
    c: DetectedCaptcha, page_url: str, user_agent: Optional[str] = None
) -> dict[str, Any]:
    """Translate a DetectedCaptcha into 2captcha in.php parameters.

    user_agent: 解答ワーカーに使わせるUA。hCaptcha/reCAPTCHAのトークンは発行時の
    UAに紐づくため、こちらのブラウザと違うUAで解かれるとサイト側で弾かれる。
    """
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
        p = {"method": "hcaptcha", "sitekey": c.sitekey, "pageurl": page_url}
        if user_agent:
            p["userAgent"] = user_agent
        if c.rqdata:
            # Enterprise hCaptcha: the answer is only valid when bound to the
            # session that issued this blob. Solving without it returns a token
            # the site rejects — which reads as "the puzzle keeps coming back".
            p["data"] = c.rqdata
            p["invisible"] = 1 if c.invisible else 0
        elif c.invisible:
            p["invisible"] = 1
        return p
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

  // Make the site's own reads return our token, for flows that ask hCaptcha for
  // the answer at submit time instead of trusting the field.
  try {
    if (typeof hcaptcha !== 'undefined' && !hcaptcha.__danPatched) {
      hcaptcha.getResponse = function() { return token; };
      hcaptcha.execute = function() { return Promise.resolve({ response: token }); };
      hcaptcha.__danPatched = true;
    }
  } catch (e) {}

  // Fire the callback the site registered with hcaptcha.render(). Filling the
  // field alone leaves the host unaware that the challenge was solved, so its
  // internal state never advances and the puzzle is presented again — this is
  // exactly how Epic's Talon behaves. reCAPTCHA already does this; hCaptcha did
  // not, which is why solved tokens appeared to do nothing.
  let fired = 0;
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
  try {
    const roots = [];
    // hCaptcha keeps rendered widget configs here; Talon/Epic wrap it further.
    if (window.hcaptcha && window.hcaptcha.__widgets) roots.push(window.hcaptcha.__widgets);
    for (const key of ['___hcaptcha_cfg', 'hcaptchaConfig', 'talon', 'Talon', '__talon']) {
      if (window[key]) roots.push(window[key]);
    }
    // data-callback="fnName" is the documented plain-HTML form.
    document.querySelectorAll('[data-callback]').forEach(el => {
      const name = el.getAttribute('data-callback');
      if (name && typeof window[name] === 'function') {
        try { window[name](token); fired++; } catch (e) {}
      }
    });
    roots.forEach(r => walk(r, 0));
  } catch (e) {}

  return { filled: n, callbacks: fired };
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
        res = await target.evaluate(_INJECT_HCAPTCHA_JS, token)
        return res if isinstance(res, dict) else {"filled": res, "callbacks": 0}
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

def _png_size(data: bytes) -> Optional[tuple[int, int]]:
    """Read width/height straight out of a PNG's IHDR (no image library)."""
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def _image_size(data: bytes) -> Optional[tuple[int, int]]:
    """Width/height of the screenshot, whatever format it came back as.

    The browser hands screenshots to the model as *downscaled JPEG* by default
    (DAN_BROWSER_SHOT_FORMAT), so a PNG-header-only reader returns None and the
    scale silently falls back to 1.0 — which puts every click ~13% off target.
    """
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(data)) as img:
            return img.width, img.height
    except Exception:
        return _png_size(data)


_CHALLENGE_PROMPT_JS = r"""
() => {
  // The instruction the user is meant to follow ("select all animals ...").
  // Worker accuracy depends on receiving it verbatim.
  const texts = [];
  const grab = (root) => {
    root.querySelectorAll('.prompt-text, .challenge-prompt, [class*="prompt"], h2, .challenge-text')
        .forEach(e => { const t = (e.innerText || '').trim(); if (t) texts.push(t); });
  };
  grab(document);
  return texts.join(' / ').slice(0, 500);
}
"""


async def solve_visual_challenge(
    page,
    api_key: Optional[str] = None,
    instruction: str = "",
) -> dict[str, Any]:
    """Solve whatever puzzle is on screen by asking a human where to click.

    Used when token solving returns ERROR_CAPTCHA_UNSOLVABLE: the challenge is a
    variant with no scripted answer (drag-to-fit, count-the-animals), but a
    person looking at a screenshot can still point at the right spots.

    Screenshot pixels and CSS pixels are not the same on a scaled display, so the
    returned points are converted with the measured ratio before clicking —
    clicking raw screenshot coordinates lands in the wrong place.
    """
    client = TwoCaptchaClient(api_key=api_key)

    shot = await page.screenshot_base64()
    # The page proxy returns {"base64": ..., "media_type": ...}, not a bare string.
    shot_b64 = shot.get("base64", "") if isinstance(shot, dict) else shot
    raw = base64.b64decode(shot_b64)
    size = _image_size(raw)
    viewport = await page.evaluate(
        "() => ({w: window.innerWidth, h: window.innerHeight})"
    )
    scale = 1.0
    if size and viewport and viewport.get("w"):
        scale = size[0] / float(viewport["w"])

    if not instruction:
        try:
            instruction = await page.evaluate(_CHALLENGE_PROMPT_JS)
        except Exception:
            instruction = ""

    # A drag puzzle needs an origin and a destination, and a worker told only
    # "click the right spot" sends back one point, which is unusable. Ask for the
    # pair explicitly so the answer matches what we can actually perform.
    dragging = bool(re.search(r"ドラッグ|drag|移動|move it", instruction or "", re.I))
    sent = instruction
    if dragging:
        sent = (instruction + " ／ 2点をこの順にクリックしてください: "
                "(1) 動かす図形の中心 (2) 置き場所の中心").strip()

    points = await client.solve_coordinates(shot_b64, instruction=sent, lang="ja")
    if not points:
        raise CaptchaError("2captcha returned no coordinates for the visual challenge")

    def to_css(p: dict[str, int]) -> tuple[float, float]:
        return p["x"] / scale, p["y"] / scale

    # Drive the pointer like a hand, not like a script. hCaptcha scores the
    # approach as well as the answer: a teleport to the exact pixel, an
    # instantaneous grab-and-drop, or a constant-speed slide all read as
    # automation, which is how a correctly-placed piece still comes back as
    # "誤った返答が提供されました".
    from app.tools.human_pointer import HumanPointer

    pointer = HumanPointer(page)
    clicked = []
    if dragging and len(points) >= 2:
        (x1, y1), (x2, y2) = to_css(points[0]), to_css(points[1])
        await pointer.drag(x1, y1, x2, y2)
        clicked = [{"x": round(x1), "y": round(y1), "drag": "from"},
                   {"x": round(x2), "y": round(y2), "drag": "to"}]
    else:
        for p in points:
            x, y = to_css(p)
            await pointer.click(x, y)
            clicked.append({"x": round(x), "y": round(y)})
            await asyncio.sleep(random.uniform(0.28, 0.62))

    logger.info(
        "visual challenge: %s %d point(s) (scale=%.3f, instruction=%r)",
        "dragged" if dragging and len(points) >= 2 else "clicked",
        len(clicked), scale, instruction[:80],
    )
    return {
        "method": "drag" if dragging and len(points) >= 2 else "coordinates",
        "clicked": clicked,
        "scale": round(scale, 3),
        "instruction": instruction,
    }


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
    try:
        user_agent = await page.evaluate("() => navigator.userAgent")
    except Exception:
        user_agent = None
    for c in detected:
        # 2captcha must be told the URL of the document the widget lives in.
        # For an in-iframe widget that is the frame URL, not the top page URL.
        target_url = c.frame_url or page_url
        params = build_in_params(c, target_url, user_agent=user_agent)
        try:
            token = await client.solve(params)
        except CaptchaError as exc:
            # ERROR_CAPTCHA_UNSOLVABLE means the workers had no scripted answer
            # for this challenge variant — not that the puzzle is unsolvable by a
            # human. Fall back to showing them the screen and asking where to
            # click, which is independent of the challenge type.
            if "UNSOLVABLE" not in str(exc).upper() and "TIMEOUT" not in str(exc).upper():
                raise
            logger.warning("token solve failed (%s); falling back to visual clicks", exc)
            visual = await solve_visual_challenge(page, api_key=api_key)
            solved.append({
                "type": c.type,
                "sitekey": c.sitekey,
                "pageurl": target_url,
                "fallback": "coordinates",
                **visual,
            })
            continue
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
