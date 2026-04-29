"""ダン用Notion の scroll 連動を Playwright で実際にテストする"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright

USER_DATA_DIR = str(Path(__file__).parent.parent / ".playwright-dn2")
FRONTEND = "http://localhost:3000"


def main():
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_DIR,
            headless=False,
            slow_mo=300,
        )
        # オーナー token 取得 (credentials DB から 'done' service)
        import json as _json
        from app.services.supabase_client import get_supabase_client
        from app.services.encryption import get_encryption_service
        import requests
        sb = get_supabase_client().client
        enc = get_encryption_service()
        cred = sb.table("credentials").select("*").eq("service_name", "done").execute().data[0]
        d = _json.loads(enc.decrypt(cred["encrypted_data"]))
        r = requests.post(
            "http://localhost:8000/api/v1/chat/login",
            json={"email": d["id"], "password": d["password"]},
        )
        tok = r.json().get("access_token")
        print(f"[INFO] got owner token: {tok[:30]}..." if tok else "[ERR] no token")

        # init script で localStorage と cookie を JS 実行前に注入
        auth_state = {"user": {"id": "2582a188-ff24-4a4f-b989-6063034d90b2", "email": d["id"]}, "token": tok, "isAuthenticated": True}
        init_script = f"""
            window.localStorage.setItem('done-token', {repr(tok)});
            window.localStorage.setItem('done-auth', {repr(_json.dumps({'state': auth_state, 'version': 0}))});
            document.cookie = 'done_access_token=' + {repr(tok)} + '; path=/';
        """
        ctx.add_init_script(init_script)

        page = ctx.new_page()
        page.on("console", lambda msg: print(f"[CONSOLE {msg.type}] {msg.text[:300]}"))
        page.on("pageerror", lambda e: print(f"[PAGEERR] {e}"))

        # /dan-notion へ
        page.goto(f"{FRONTEND}/dan-notion", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.screenshot(path=".playwright-dn2/01-initial.png")
        print("[INFO] /dan-notion opened")

        # デバッグ: localStorage の中身と API 直叩きを確認
        ls_token = page.evaluate("localStorage.getItem('done-token')")
        print(f"[DEBUG] localStorage done-token: {(ls_token or '')[:30]}...")
        api_pages = page.evaluate("""
            async () => {
              const tok = localStorage.getItem('done-token');
              const res = await fetch('/api/v1/dan-notion/pages', { headers: { Authorization: `Bearer ${tok}` } });
              const d = await res.json();
              return { status: res.status, count: Array.isArray(d) ? d.length : 0, sample: Array.isArray(d) ? d[0] : d };
            }
        """)
        print(f"[DEBUG] fetch /pages: {api_pages}")

        # 上部ガントを展開
        try:
            gantt_header = page.get_by_text("エージェント活動").first
            gantt_header.click()
            page.wait_for_timeout(800)
            page.screenshot(path=".playwright-dn2/02-gantt-expanded.png")
            print("[INFO] gantt expanded")
        except Exception as e:
            print(f"[WARN] gantt expand failed: {e}")

        # まずビューポートを広げる
        page.set_viewport_size({"width": 1600, "height": 1000})
        page.wait_for_timeout(500)

        # ガント右端見切れ確認: 直近 run をいくつか試して overflow を検出
        s = page.locator("select").first
        options = s.locator("option").all()
        print(f"[INFO] select has {len(options)} options")
        # 最後のオプション (一番古い) を選択
        val = options[-1].get_attribute("value")
        s.select_option(value=val)
        page.wait_for_timeout(2500)
        gantt_info = page.evaluate("""
            () => {
              const containers = document.querySelectorAll('.relative.px-2');
              const out = [];
              for (const c of containers) {
                const cRect = c.getBoundingClientRect();
                const bars = c.querySelectorAll('.absolute.rounded-sm');
                if (bars.length === 0) continue;
                const info = { container: {w: cRect.width}, bars: [] };
                bars.forEach((b, i) => {
                  const r = b.getBoundingClientRect();
                  info.bars.push({
                    idx: i,
                    left: r.left - cRect.left,
                    right: r.right - cRect.left,
                    width: r.width,
                    overflow: r.right > cRect.right,
                    overflowPx: r.right - cRect.right,
                  });
                });
                out.push(info);
              }
              return out;
            }
        """)
        # === ZOOM テスト ===
        # フレッシュに HMR 適用するため1回リロード
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        # ガント展開
        try:
            page.get_by_text("エージェント活動").first.click()
            page.wait_for_timeout(500)
        except: pass
        # run を再選択
        page.locator("select").first.select_option(value=val)
        page.wait_for_timeout(1500)

        print("\n=== GANTT ZOOM テスト ===")
        # ズーム前の bar 情報
        before = page.evaluate("""
            () => {
              const area = document.querySelector('.relative.px-2 [style*="left: 150px"]');
              if (!area) return null;
              const bars = area.querySelectorAll('.absolute.rounded-sm');
              return {
                areaW: area.getBoundingClientRect().width,
                barCount: bars.length,
                firstBar: bars[0] ? {left: bars[0].getBoundingClientRect().left, width: bars[0].getBoundingClientRect().width} : null
              };
            }
        """)
        print(f"  before zoom: {before}")

        # wheel イベントを直接 dispatch (Playwright mouse.wheel はターゲット狙いが不安定)
        area = page.locator('.relative.px-2 [style*="left: 150px"]').first
        box = area.bounding_box()
        if box:
            cx = box['x'] + box['width'] * 0.3
            cy = box['y'] + box['height'] / 2
            for _ in range(5):
                page.evaluate("""
                    ({cx, cy}) => {
                      const el = document.elementFromPoint(cx, cy);
                      if (!el) { console.log('no el at', cx, cy); return; }
                      const ev = new WheelEvent('wheel', {
                        clientX: cx, clientY: cy, deltaY: -500,
                        bubbles: true, cancelable: true
                      });
                      el.dispatchEvent(ev);
                    }
                """, {"cx": cx, "cy": cy})
                page.wait_for_timeout(150)
        page.wait_for_timeout(500)
        after_zoom = page.evaluate("""
            () => {
              const area = document.querySelector('.relative.px-2 [style*="left: 150px"]');
              if (!area) return null;
              const bars = area.querySelectorAll('.absolute.rounded-sm');
              return {
                areaW: area.getBoundingClientRect().width,
                barCount: bars.length,
                firstBar: bars[0] ? {left: bars[0].getBoundingClientRect().left, width: bars[0].getBoundingClientRect().width} : null
              };
            }
        """)
        print(f"  after zoom in: {after_zoom}")
        page.screenshot(path=".playwright-dn2/gantt-zoomed.png")

        # Drag pan テスト (zoom in 済み状態で)
        if box:
            px = box['x'] + box['width'] * 0.5
            py = box['y'] + box['height'] / 2
            first_before = page.evaluate("""
                () => {
                  const b = document.querySelector('.relative.px-2 [style*="left: 150px"] .absolute.rounded-sm');
                  return b ? b.getBoundingClientRect().left : null;
                }
            """)
            # ドラッグ: 右に 200px
            page.mouse.move(px, py)
            page.mouse.down()
            page.mouse.move(px + 200, py, steps=10)
            page.mouse.up()
            page.wait_for_timeout(400)
            first_after = page.evaluate("""
                () => {
                  const b = document.querySelector('.relative.px-2 [style*="left: 150px"] .absolute.rounded-sm');
                  return b ? b.getBoundingClientRect().left : null;
                }
            """)
            print(f"  drag pan: first bar left {first_before} → {first_after} (shift={first_after-first_before if first_before and first_after else None})")

        # reset via button
        try:
            page.get_by_role("button", name="🔍 全体").click()
            page.wait_for_timeout(400)
            print("  reset button clicked")
        except Exception as e:
            print(f"  reset button not found: {e}")

        print("=== GANTT 右端見切れ調査 ===")
        for g in gantt_info:
            overs = [b for b in g['bars'] if b['overflow']]
            print(f"  container width: {g['container']['w']:.0f}px, total bars: {len(g['bars'])}, overflow: {len(overs)}")
            for b in overs[:10]:
                print(f"    bar[{b['idx']}] right={b['right']:.0f} overflow={b['overflowPx']:.0f}px")
            if g['bars']:
                rightmost = max(g['bars'], key=lambda x: x['right'])
                print(f"  rightmost bar: idx={rightmost['idx']} right={rightmost['right']:.0f} (container width={g['container']['w']:.0f})")
        page.screenshot(path=".playwright-dn2/gantt-overflow.png")

        print("\n=== TEST 1: 一番古い (最後のオプション) を選択 ===")
        val = options[-1].get_attribute("value")
        s.select_option(value=val)
        page.wait_for_timeout(2500)
        info1 = page.evaluate("""
            () => {
              const c = document.querySelector('.flex-1.overflow-y-auto.px-4');
              return c ? {top: c.scrollTop, h: c.scrollHeight, ch: c.clientHeight} : null;
            }
        """)
        print(f"  scrollTop/max/clientH = {info1}")
        page.screenshot(path=".playwright-dn2/test1-oldest.png")

        # テスト2: 中間の run 選択
        print("\n=== TEST 2: 中間オプションを選択 ===")
        mid = options[len(options) // 2].get_attribute("value")
        s.select_option(value=mid)
        page.wait_for_timeout(2500)
        info2 = page.evaluate("""
            () => {
              const c = document.querySelector('.flex-1.overflow-y-auto.px-4');
              return c ? {top: c.scrollTop, h: c.scrollHeight, ch: c.clientHeight} : null;
            }
        """)
        print(f"  scrollTop/max/clientH = {info2}")
        page.screenshot(path=".playwright-dn2/test2-middle.png")

        # テスト3: 最新 (2番目のオプション、先頭は placeholder)
        print("\n=== TEST 3: 最新 run 選択 ===")
        latest = options[1].get_attribute("value")
        s.select_option(value=latest)
        page.wait_for_timeout(2500)
        info3 = page.evaluate("""
            () => {
              const c = document.querySelector('.flex-1.overflow-y-auto.px-4');
              return c ? {top: c.scrollTop, h: c.scrollHeight, ch: c.clientHeight} : null;
            }
        """)
        print(f"  scrollTop/max/clientH = {info3}")
        page.screenshot(path=".playwright-dn2/test3-latest.png")

        # チャットスクロール位置を JS で確認
        scroll_info = page.evaluate("""
            () => {
              // ChatDock 内の overflow-y-auto div を探す
              const els = document.querySelectorAll('.overflow-y-auto');
              const results = [];
              for (const el of els) {
                results.push({
                  tag: el.tagName,
                  classes: el.className.slice(0, 100),
                  scrollTop: el.scrollTop,
                  scrollHeight: el.scrollHeight,
                  clientHeight: el.clientHeight,
                });
              }
              return results;
            }
        """)
        print("[DEBUG] scrollable elements:")
        for s in scroll_info:
            print(f"  {s}")

        page.wait_for_timeout(2000)
        page.screenshot(path=".playwright-dn2/04-final.png")
        print("[INFO] screenshots saved to .playwright-dn2/")
        print("[INFO] waiting 10 seconds for manual inspection...")
        page.wait_for_timeout(10000)

        ctx.close()


if __name__ == "__main__":
    Path(".playwright-dn2").mkdir(exist_ok=True)
    main()
