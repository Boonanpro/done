"""hCaptcha のチャレンジ内部を読み取り専用で観測する。

この部屋の常駐ブラウザに CDP で外から繋ぎ、
  1) hcaptcha のネットワーク応答（/getcaptcha 等）を保存
  2) チャレンジ iframe が現れたら中の DOM ツリーを丸ごと保存
する。クリック・遷移・送信は一切しない。

狙いは「画像解析で当てにいく」のをやめて、パズルを構成している
要素（運ぶ図形・置き場所）の座標をブラウザから直接取れるかを見極めること。
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.async_api import async_playwright

ROOM_PROFILE = Path.home() / ".ai_secretary" / "browser_data--38461f5a-6ded-464a-adb9-92a7de46b288-96152237"
OUT = Path(__file__).resolve().parent.parent / ".tmp" / "hcap"
OUT.mkdir(parents=True, exist_ok=True)

# 要素ツリーを走査する。shadow DOM も辿る（hCaptcha は使う可能性がある）。
# canvas は toDataURL が通るか（＝中身を読めるか）まで見る。
DUMP_JS = r"""
() => {
  const MAX = 3000;
  const nodes = [];
  const rectOf = (el) => {
    const r = el.getBoundingClientRect();
    return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)];
  };
  const walk = (root, depth) => {
    if (nodes.length > MAX) return;
    for (const el of root.children) {
      if (nodes.length > MAX) return;
      const cls = el.getAttribute ? (el.getAttribute('class') || '') : '';
      const st = el.getAttribute ? (el.getAttribute('style') || '') : '';
      const e = {d: depth, tag: el.tagName.toLowerCase(), rect: rectOf(el)};
      if (el.id) e.id = el.id;
      if (cls) e.cls = cls.slice(0, 120);
      if (st) e.style = st.slice(0, 200);
      const aria = el.getAttribute && el.getAttribute('aria-label');
      if (aria) e.aria = aria.slice(0, 80);
      const role = el.getAttribute && el.getAttribute('role');
      if (role) e.role = role;
      if (el.draggable) e.draggable = true;
      for (const a of (el.attributes || [])) {
        if (a.name.startsWith('data-')) {
          e.data = e.data || {};
          e.data[a.name] = String(a.value).slice(0, 80);
        }
      }
      if (el.tagName === 'CANVAS') {
        e.canvas = {w: el.width, h: el.height};
        try { el.toDataURL(); e.canvas.readable = true; }
        catch (err) { e.canvas.readable = false; e.canvas.err = String(err).slice(0, 90); }
      }
      if (el.tagName === 'IMG') e.img = (el.getAttribute('src') || '').slice(0, 160);
      if (el.children.length === 0 && el.textContent) {
        const t = el.textContent.trim();
        if (t) e.txt = t.slice(0, 60);
      }
      nodes.push(e);
      if (el.shadowRoot) {
        nodes.push({d: depth + 1, tag: '#shadow-root'});
        walk(el.shadowRoot, depth + 2);
      }
      walk(el, depth + 1);
    }
  };
  walk(document.documentElement, 0);
  return {url: location.href, viewport: [innerWidth, innerHeight], count: nodes.length, nodes: nodes};
}
"""


def read_port() -> int:
    return int((ROOM_PROFILE / "dan_cdp_port.txt").read_text(encoding="utf-8").strip())


async def main(timeout_s: int = 240):
    port = read_port()
    print(f"CDP port: {port}", flush=True)
    responses = []

    async with async_playwright() as p:
        browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        pages = [pg for c in browser.contexts for pg in c.pages]
        target = next((pg for pg in pages if "epicgames" in pg.url), None) or pages[0]
        print("watching:", target.url, flush=True)

        async def on_response(resp):
            u = resp.url
            if "hcaptcha.com" not in u:
                return
            if not any(k in u for k in ("getcaptcha", "checkcaptcha", "check", "/hsw")):
                return
            rec = {"url": u.split("?")[0], "status": resp.status, "t": time.time()}
            try:
                body = await resp.text()
                rec["len"] = len(body)
                rec["body"] = body[:200000]
            except Exception as exc:
                rec["err"] = str(exc)[:120]
            responses.append(rec)
            print(f"[net] {rec['url']} status={rec['status']} len={rec.get('len')}", flush=True)

        target.on("response", lambda r: asyncio.create_task(on_response(r)))

        deadline = time.time() + timeout_s
        dumped = set()
        while time.time() < deadline:
            for fr in target.frames:
                u = fr.url or ""
                if "hcaptcha.com" not in u:
                    continue
                kind = "challenge" if "frame=challenge" in u else (
                    "checkbox" if "frame=checkbox" in u else "other")
                if kind != "challenge" or u in dumped:
                    continue
                await asyncio.sleep(2.0)  # 描画完了を待つ
                try:
                    data = await fr.evaluate(DUMP_JS)
                except Exception as exc:
                    print("dump failed:", str(exc)[:200], flush=True)
                    continue
                dumped.add(u)
                stamp = int(time.time())
                path = OUT / f"challenge_dom_{stamp}.json"
                path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"[dom] dumped {data['count']} nodes -> {path}", flush=True)
                try:
                    shot = OUT / f"challenge_{stamp}.png"
                    el = await fr.frame_element()
                    await el.screenshot(path=str(shot))
                    print(f"[dom] screenshot -> {shot}", flush=True)
                except Exception as exc:
                    print("frame screenshot failed:", str(exc)[:120], flush=True)
            await asyncio.sleep(1.0)

        if responses:
            path = OUT / f"responses_{int(time.time())}.json"
            path.write_text(json.dumps(responses, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[net] saved {len(responses)} responses -> {path}", flush=True)
        await browser.close()  # CDP を切るだけ。Chrome は動き続ける
        print("done", flush=True)


asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 240))
