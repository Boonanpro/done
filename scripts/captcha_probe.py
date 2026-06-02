"""Probe a form page for reCAPTCHA type/sitekey + form fields.

Generic investigation: detects v2 / v3 / enterprise / hcaptcha / turnstile.
Usage: python scripts/captcha_probe.py <url>
"""
import asyncio
import json
import sys
from pathlib import Path
from playwright.async_api import async_playwright

OUT = Path(__file__).resolve().parent.parent / ".tmp"
OUT.mkdir(exist_ok=True)
URL = sys.argv[1] if len(sys.argv) > 1 else "https://toaru-d.com/inquiry"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 1200}, locale="ja-JP",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
        )
        page = await ctx.new_page()
        await page.goto(URL, wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(5000)
        print("final url:", page.url, "| title:", await page.title())

        info = await page.evaluate(
            r"""() => {
              const out = {};
              // sitekeys
              out.dataSitekeys = [...document.querySelectorAll('[data-sitekey]')]
                  .map(e => ({sitekey:e.getAttribute('data-sitekey'), cls:e.className, action:e.getAttribute('data-action')}));
              // recaptcha/hcaptcha/turnstile script srcs
              out.scripts = [...document.querySelectorAll('script[src]')].map(s=>s.src)
                  .filter(s=>/recaptcha|hcaptcha|turnstile|gstatic.*captcha/i.test(s));
              // iframes
              out.iframes = [...document.querySelectorAll('iframe[src]')].map(f=>f.src)
                  .filter(s=>/recaptcha|hcaptcha|turnstile/i.test(s));
              // global objects
              out.has_grecaptcha = typeof grecaptcha !== 'undefined';
              out.has_enterprise = (typeof grecaptcha !== 'undefined' && !!grecaptcha.enterprise);
              out.has_hcaptcha = typeof hcaptcha !== 'undefined';
              out.has_turnstile = typeof turnstile !== 'undefined';
              // response fields
              out.responseFields = [...document.querySelectorAll('textarea[name=g-recaptcha-response], textarea#g-recaptcha-response, input[name=h-captcha-response], input[name=cf-turnstile-response]')]
                  .map(e=>({name:e.name, id:e.id, tag:e.tagName}));
              // form fields
              const forms = [...document.querySelectorAll('form')];
              out.forms = forms.map(f => ({
                action: f.action, method: f.method,
                fields: [...f.querySelectorAll('input,textarea,select')]
                  .map(e=>({name:e.name, type:e.type||e.tagName.toLowerCase(), id:e.id, required:e.required, placeholder:e.placeholder})),
                submits: [...f.querySelectorAll('button,[type=submit]')].map(b=>(b.innerText||b.value||'').trim()),
              }));
              return out;
            }"""
        )
        # classify
        cls = "unknown"
        sk = None
        action = None
        scripts = info.get("scripts", [])
        render_sk = None
        for s in scripts:
            if "render=" in s:
                render_sk = s.split("render=")[1].split("&")[0]
        if info.get("has_turnstile") or any("turnstile" in s for s in scripts):
            cls = "turnstile"
        elif info.get("has_hcaptcha"):
            cls = "hcaptcha"
        elif info.get("has_enterprise"):
            cls = "recaptcha_enterprise"
        elif render_sk and render_sk not in ("explicit", "onload"):
            cls = "recaptcha_v3"; sk = render_sk
        elif info.get("dataSitekeys"):
            cls = "recaptcha_v2"; sk = info["dataSitekeys"][0]["sitekey"]
            action = info["dataSitekeys"][0].get("action")
        if not sk and info.get("dataSitekeys"):
            sk = info["dataSitekeys"][0]["sitekey"]

        info["_classified"] = {"type": cls, "sitekey": sk, "action": action, "render_sitekey": render_sk}
        (OUT / "captcha_probe.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
        await page.screenshot(path=str(OUT / "captcha_probe.png"), full_page=True)
        print("CLASSIFIED:", json.dumps(info["_classified"], ensure_ascii=False))
        print("scripts:", scripts)
        print("iframes:", info.get("iframes"))
        print("forms:", len(info.get("forms", [])), "response_fields:", info.get("responseFields"))
        await ctx.close(); await browser.close()


asyncio.run(main())
