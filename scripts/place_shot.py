"""場所の地図どおりに画面を開いて撮り、表示できるはずの物が本当に見えるかを測る（直す前と後を並べる）。

  python scripts/place_shot.py artifact:dev-lead --tag before     直す前に撮る
  python scripts/place_shot.py artifact:dev-lead --tag after      直した後に撮る（before があれば前と後を並べた絵も作る）
  python scripts/place_shot.py dev-lead-room                      共通の場所の地図でも開ける（--tag 省略は now）
  python scripts/place_shot.py x-operation --base http://127.0.0.1:3012   slug だけでも artifact:<slug> になる

開くのはテスト用アカウント（dan-test@example.com）。入館証はこの場で作り（30分）、持ち主の画面や履歴には触れない。
既定の行き先は成果物の開発サーバー（3001。成果物のファイルそのものを出す。本人の /preview/<slug> もここから来る）。
作業場所で直した画面は、その作業場所で立てた画面のサーバーを --base で渡す。

地図（app/agent/place_map.py）の前書きの使う所:
  open:   開く道（/preview/<slug> など）
  ready:  開けたと分かる CSS の印（省略時は body）
  probe:  吹き出しなどの見本を入れる入れ物。{module: style, scope: app, bubble: md} は CSS モジュールの名前、
          {classes: "prose prose-dan"} はそのままのクラス名
  shows:  その入れ物で見えるはずの物（番号の並び・点の並び・表・見出し・太字・コード）。1つずつ見本を入れて測る

証拠は <作業場所>/.data/place_shots/<場所>/ に残す（片付けで消さない）:
  <tag>.png（見本の吹き出し）、<tag>-page.png（画面全体）、<tag>.json（測った結果）、compare.png（前と後）
最後の行: [place_shot] place=<場所> tag=<tag> result=OK|NG|UNREACHABLE
終了コード: 0=OK / 1=NG / 2=開けなかった
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent import place_map as pm  # noqa: E402

TEST_USER = {"id": "1f53bb2a-51da-4a2a-be9e-4c5a0f74d5f1", "email": "dan-test@example.com", "name": "テスト用"}
DEFAULT_BASE = os.environ.get("DAN_PLACE_SHOT_BASE") or "http://127.0.0.1:3001"
REFUSED_BASES = ("dan.paina.info", ":8000", ":9000")

# 見本: react-markdown＋remark-gfm が返事の Markdown から作るのと同じ形の HTML。
SAMPLES = {
    "番号の並び": ("<ol><li>一つ目</li><li>二つ目</li><li>三つ目</li></ol>", "ol > li"),
    "点の並び": ("<ul><li>りんご</li><li>みかん</li></ul>", "ul > li"),
    "表": ("<table><thead><tr><th>項目</th><th>値</th></tr></thead><tbody><tr><td>費用</td><td>0円</td></tr></tbody></table>", "td"),
    "見出し": ("<h3>見出し</h3>", "h3"),
    "太字": ("<p>ふつうの字と<strong>太字</strong></p>", "strong"),
    "コード": ("<p><code>place_map.py</code></p>", "code"),
}

PROBE_JS = r"""
({probe, samples}) => {
  // CSS モジュールの名前（style.module.css の .md など）を、読み込まれた CSS から本物のクラス名に引き当てる
  const names = new Set();
  const walk = (rules) => { for (const r of rules) { if (r.selectorText) for (const m of r.selectorText.matchAll(/\.([A-Za-z0-9_-]+)/g)) names.add(m[1]); if (r.cssRules) walk(r.cssRules); } };
  for (const sh of document.styleSheets) { try { walk(sh.cssRules); } catch (e) {} }
  const find = (local) => {
    if (!local) return '';
    const mod = (probe.module || '').toLowerCase();
    const hits = [...names].filter((n) => n.split(/_+|--/).includes(local));
    return hits.find((n) => mod && n.toLowerCase().startsWith(mod)) || hits[0] || '';
  };
  const scope = probe.classes ? '' : find(probe.scope);
  const bubble = probe.classes ? probe.classes : find(probe.bubble);
  if (!bubble || (probe.scope && !probe.classes && !scope)) return {error: `CSS の名前が見つからない: scope=${probe.scope || ''}→${scope} bubble=${probe.bubble || ''}→${bubble}`};
  document.getElementById('__place_probe')?.remove();
  const outer = document.createElement('div');
  outer.id = '__place_probe';
  if (scope) outer.className = scope;
  outer.style.cssText = 'position:fixed;inset:auto;left:12px;top:12px;width:560px;height:auto;max-height:none;overflow:visible;z-index:2147483647;background:#fff;padding:18px 20px;box-shadow:0 2px 14px rgba(0,0,0,.25);border-radius:12px;display:block';
  const inner = document.createElement('div');
  inner.className = bubble;
  inner.innerHTML = samples.map(([name, html]) => `<p><b>【${name}】</b></p>${html}`).join('');
  outer.appendChild(inner);
  document.body.appendChild(outer);
  const results = {};
  for (const [name, html, sel] of samples) {
    const el = inner.querySelector(sel);
    if (!el) { results[name] = {ok: false, why: '見本が入らなかった'}; continue; }
    const cs = getComputedStyle(el), base = getComputedStyle(inner);
    let ok = cs.display !== 'none' && cs.visibility !== 'hidden' && el.getBoundingClientRect().height > 0, why = '';
    if (sel.endsWith('li')) {
      ok = ok && cs.display === 'list-item' && cs.listStyleType !== 'none';
      why = `display=${cs.display} list-style-type=${cs.listStyleType}`;
    } else if (sel === 'td') {
      ok = ok && parseFloat(cs.borderTopWidth) > 0;
      why = `border=${cs.borderTopWidth} ${cs.borderTopStyle}`;
    } else if (sel === 'h3' || sel === 'strong') {
      ok = ok && (parseInt(cs.fontWeight) >= 600 || parseFloat(cs.fontSize) > parseFloat(base.fontSize) * 1.15);
      why = `font-weight=${cs.fontWeight} font-size=${cs.fontSize}`;
    } else if (sel === 'code') {
      ok = ok && (cs.backgroundColor !== base.backgroundColor || cs.fontFamily !== base.fontFamily);
      why = `font=${cs.fontFamily.slice(0, 30)} bg=${cs.backgroundColor}`;
    }
    results[name] = {ok, why};
  }
  const r = outer.getBoundingClientRect();
  return {scope, bubble, results, rect: {x: r.x, y: r.y, width: r.width, height: r.height}};
}
"""


def token() -> str:
    """テスト用アカウントの入館証。作業場所には .env が無いので、鍵は動いているダンの .env から読む（work.py try と同じ）。"""
    if not (ROOT / ".env").exists() and not os.environ.get("JWT_SECRET_KEY"):
        sys.path.insert(0, str(ROOT / "scripts"))
        from follow_github import live_root
        from work import _env_file
        for key, value in _env_file(live_root() / ".env").items():
            if key in ("JWT_SECRET_KEY", "APP_SECRET_KEY", "JWT_ALGORITHM", "ACCESS_TOKEN_EXPIRE_MINUTES"):
                os.environ.setdefault(key, value)
    from app.services.auth_service import create_access_token
    return create_access_token(TEST_USER["id"], TEST_USER["email"], expires_delta=timedelta(minutes=30))


def place_id(arg: str) -> str:
    if arg.startswith("artifact:") or arg in pm.common_places():
        return arg
    return f"artifact:{arg}"


def compare(out: Path) -> Path | None:
    from PIL import Image, ImageDraw, ImageFont
    a, b = out / "before.png", out / "after.png"
    if not (a.exists() and b.exists()):
        return None
    ia, ib = Image.open(a).convert("RGB"), Image.open(b).convert("RGB")
    pad, head = 24, 56
    w, h = ia.width + ib.width + pad * 3, max(ia.height, ib.height) + head + pad
    img = Image.new("RGB", (w, h), "#eceae4")
    font = None
    for f in ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", "/System/Library/Fonts/Hiragino Sans GB.ttc", "C:/Windows/Fonts/meiryob.ttc"):
        try:
            font = ImageFont.truetype(f, 30)
            break
        except OSError:
            continue
    d = ImageDraw.Draw(img)
    for x, label, im in ((pad, "前", ia), (pad * 2 + ia.width, "後", ib)):
        d.text((x, 12), label, fill="#222", font=font)
        img.paste(im, (x, head))
    path = out / "compare.png"
    img.save(path)
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("place")
    ap.add_argument("--tag", default="now", choices=["before", "after", "now"])
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--path", help="地図の open の代わりに開く道")
    ap.add_argument("--out", help="証拠を置く所（既定 .data/place_shots/<場所>）")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    a = ap.parse_args(argv)

    pid = place_id(a.place)
    tail = f"place={pid} tag={a.tag}"
    m = pm.place_map(pid)
    if not m:
        print(f"地図がありません（{pid}）。成果物なら python scripts/place_map.py draft {pid.split(':', 1)[-1]}")
        print(f"[place_shot] {tail} result=UNREACHABLE")
        return 2
    meta = m["meta"]
    path = a.path or meta.get("open")
    if not path:
        print(f"この場所はブラウザでは開けません: {meta.get('reach') or '地図の「行き方」を見る'}")
        print(f"[place_shot] {tail} result=UNREACHABLE")
        return 2
    base = a.base.rstrip("/")
    if any(x in base for x in REFUSED_BASES):
        print(f"本番の受け口（{base}）には試験で入りません。3001 か作業場所の画面のサーバーを使ってください。")
        print(f"[place_shot] {tail} result=UNREACHABLE")
        return 2
    out = Path(a.out) if a.out else ROOT / ".data" / "place_shots" / pid.replace(":", "_")
    out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright
    tok = token()
    auth = json.dumps({"state": {"user": {**TEST_USER, "full_name": TEST_USER["name"]}, "token": tok, "isAuthenticated": True}, "version": 0})
    host = base.split("://", 1)[-1].split("/")[0].split(":")[0]
    record: dict = {"place": pid, "tag": a.tag, "url": base + path, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(viewport={"width": a.width, "height": a.height}, device_scale_factor=1, locale="ja-JP")
            ctx.add_cookies([{"name": "done_access_token", "value": tok, "domain": host, "path": "/"}])
            ctx.add_init_script(f"try{{localStorage.setItem('done-token',{json.dumps(tok)});localStorage.setItem('done-auth',{json.dumps(auth)});}}catch(e){{}}")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)[:200]))
            try:
                page.goto(base + path, wait_until="domcontentloaded", timeout=90_000)
                if meta.get("ready"):
                    page.wait_for_selector(meta["ready"], timeout=60_000)
            except Exception as e:  # noqa: BLE001 - 開けなかった理由をそのまま残す
                record["error"] = f"開けなかった: {str(e).splitlines()[0][:200]}"
            try:   # 画面は数十秒ごとに読み直し、開発サーバーは更新の知らせをつなぎっぱなしにするので、静まるまでは待ち切らない
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:  # noqa: BLE001
                pass
            record["final_url"] = page.url
            if "/login" in page.url and "/login" not in path:
                record["error"] = "ログイン画面に戻された（テスト用アカウントの入館証が効いていない）"
            page.screenshot(path=str(out / f"{a.tag}-page.png"))
            probe = meta.get("probe")
            shows = [s for s in (meta.get("shows") or []) if s in SAMPLES]
            if probe and shows and "error" not in record:
                res = page.evaluate(PROBE_JS, {"probe": probe, "samples": [[s, *SAMPLES[s]] for s in shows]})
                record["probe"] = res
                if res.get("rect"):
                    r = res["rect"]
                    page.screenshot(path=str(out / f"{a.tag}.png"), clip={"x": r["x"], "y": r["y"], "width": r["width"], "height": min(r["height"], 4000)})
            elif "error" not in record:
                shutil.copyfile(out / f"{a.tag}-page.png", out / f"{a.tag}.png")
            record["page_errors"] = errors[:5]
        finally:
            browser.close()

    (out / f"{a.tag}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"開いた: {record.get('final_url') or record['url']}")
    if record.get("error"):
        print(record["error"])
        print(f"証拠: {out}")
        print(f"[place_shot] {tail} result=UNREACHABLE")
        return 2
    bad = []
    probe = record.get("probe") or {}
    if probe.get("error"):
        bad.append(probe["error"])
    for name, r in (probe.get("results") or {}).items():
        print(f"  {'○' if r['ok'] else '×'} {name}（{r['why']}）")
        if not r["ok"]:
            bad.append(f"{name}が見えない（{r['why']}）")
    print(f"撮った: {out / (a.tag + '.png')}")
    if a.tag == "after":
        c = compare(out)
        if c:
            print(f"前と後: {c}")
    for e in record.get("page_errors") or []:
        print(f"  画面のエラー: {e}")
    if bad:
        print("見えるはずの物が見えていません: " + " / ".join(bad))
    print(f"[place_shot] {tail} result={'NG' if bad else 'OK'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
