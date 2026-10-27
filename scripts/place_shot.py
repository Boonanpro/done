"""場所の地図どおりに画面を開いて撮り、本当にみきさんに見える形になっているかを測る（直す前と後を並べる）。

  python scripts/place_shot.py artifact:dev-lead --tag before     直す前に撮る
  python scripts/place_shot.py artifact:dev-lead --tag after      直した後に撮る（before があれば前と後を並べた絵も作る）
  python scripts/place_shot.py dev-lead-room --base http://127.0.0.1:3012   共通の場所の地図でも開ける
  python scripts/place_shot.py x-operation                        slug だけでも artifact:<slug> になる
  python scripts/place_shot.py x-operation --tag before --phone --expect-shows 番号の並び
                                    みきさんの「番号が出ていない」を、スマホの幅で、直す前に出してみる（再現）

不具合の知らせ（2026-10-27 付箋「不具合を先に再現する」）: みきさんが「動かない」「出ていない」と言ったら、直す前に
みきさんが見ている物を --expect-… で書いて --tag before で撮る。見えるはずの物が見えなければ「再現した」（repro=YES）。
直した後に同じ --expect-… で --tag after を撮り、OK なら前と後の絵（compare.png）を返事に貼る。
再現しなければ（repro=NO）、直さずに artifact_seen.py でみきさんの画面の版を確かめる。
  --expect-shows 名前   地図の shows の見本（番号の並び・点の並び・表・見出し・太字・コード）が見えるはず
  --expect-visible CSS  その部品が見えるはず（×ボタンなら '[aria-label="閉じる"]' など）
  --expect-text 字      その字が画面に出るはず
  --expect-no-text 字   その字が画面に出ないはず（エラーの文など）
  --phone               スマホの幅（360×780・指で触る端末）で開く。みきさんがスマホで見た話の時

開くのはテスト用アカウント（dan-test@example.com）。入館証はこの場で作り（30分）、持ち主の画面や履歴には触れない。
既定の行き先は成果物の開発サーバー（3001。成果物のファイルそのものを出す。本人の /preview/<slug> もここから来る）。
作業場所で直した画面は、その作業場所で立てた画面のサーバーを --base で渡す。

測るのは3つで、1つでも NG なら全体が NG（2026-10-25 確かめ役の指摘: 見本だけ測ると、画面が白紙でもエラーでも OK になった）:
  1. 着いたか: 開いた道のままか（/login・/collab などへ移されていないか）、地図の ready の部品が見えるか
  2. 本物の画面: 画面のエラー（Application error・地図の errors の文）が出ていないか、白紙でないか、
     地図の probe の入れ物が本物の画面にあれば、それが透明・隠れになっていないか
  3. 見本: 地図の shows の物（番号の並び・表など）の見本を probe の入れ物に入れ、印・罫線・太さと、透けていないか
地図に open が無い場所（スマホのアプリなど）は UNREACHABLE。

証拠は <木>/.data/place_shots/<場所>/ に残す（片付けで消さない）:
  <tag>.png（見本の吹き出し、無ければ画面全体）、<tag>-page.png（画面全体）、<tag>.json（測った結果）、compare.png（前と後）
最後の行: [place_shot] place=<場所> covers=<同じ画面を指す場所> tag=<tag> result=OK|NG|UNREACHABLE root=<木>
          （--expect-… を付けた時は後ろに expect=<数> repro=YES|NO。YES は、みきさんの言う崩れがこの画面でも出た）
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
AWAY_PATHS = ("/login", "/collab", "/register")
ERROR_TEXTS = ["Application error", "Unhandled Runtime Error", "Internal Server Error", "This page could not be found",
               "エラーが続いています", "問題が発生しました", "読み込めませんでした"]

# 見本: react-markdown＋remark-gfm が返事の Markdown から作るのと同じ形の HTML。
SAMPLES = {
    "番号の並び": ("<ol><li>一つ目</li><li>二つ目</li><li>三つ目</li></ol>", "ol > li"),
    "点の並び": ("<ul><li>りんご</li><li>みかん</li></ul>", "ul > li"),
    "表": ("<table><thead><tr><th>項目</th><th>値</th></tr></thead><tbody><tr><td>費用</td><td>0円</td></tr></tbody></table>", "td"),
    "見出し": ("<h3>見出し</h3>", "h3"),
    "太字": ("<p>ふつうの字と<strong>太字</strong></p>", "strong"),
    "コード": ("<p><code>place_map.py</code></p>", "code"),
}

# 透けていないか: 自分から上の要素の不透明度の積・visibility・display、本当にその位置に描かれているか
SEEN_JS = r"""
const shown = (el) => {
  if (!el || !el.isConnected) return {ok: false, why: '無い'};
  const r = el.getBoundingClientRect();
  if (r.width < 1 || r.height < 1) return {ok: false, why: '大きさが0'};
  let op = 1;
  for (let x = el; x && x.nodeType === 1; x = x.parentElement) {
    const cs = getComputedStyle(x);
    if (cs.display === 'none') return {ok: false, why: 'display=none'};
    op *= parseFloat(cs.opacity || '1');
  }
  const cs = getComputedStyle(el);
  if (cs.visibility === 'hidden' || cs.visibility === 'collapse') return {ok: false, why: 'visibility=' + cs.visibility};
  if (op < 0.2) return {ok: false, why: `透けている（不透明度 ${op.toFixed(2)}）`};
  if (cs.color && /rgba\([^)]*,\s*0\)$/.test(cs.color)) return {ok: false, why: '字の色が透明'};
  const cx = Math.min(innerWidth - 1, Math.max(0, r.left + Math.min(r.width / 2, 20))), cy = Math.min(innerHeight - 1, Math.max(0, r.top + Math.min(r.height / 2, 10)));
  const hit = document.elementFromPoint(cx, cy);
  if (hit && hit !== el && !el.contains(hit) && !hit.contains(el)) return {ok: false, why: '上に別の物が重なっている'};
  return {ok: true, why: ''};
};
"""

PAGE_JS = r"""
({errors, probe}) => {
""" + SEEN_JS + r"""
  const text = document.body ? document.body.innerText || '' : '';
  const found = errors.filter((e) => text.includes(e));
  // 開発サーバーの隅の印（Issue の数）は読み込み失敗の記録でも増えるので数えない。開いたエラーの画面だけを数える
  const portal = document.querySelector('nextjs-portal')?.shadowRoot;
  if (portal && portal.querySelector('[data-nextjs-dialog], [data-nextjs-dialog-overlay]')) found.push('Next のエラーの画面: ' + (portal.querySelector('[data-nextjs-dialog]')?.innerText || '').split('\n')[0].slice(0, 80));
  const media = document.querySelectorAll('img,canvas,svg,video').length;
  let real = null;
  if (probe && probe.real) {
    const els = [...document.querySelectorAll(probe.real)].filter((e) => e.id !== '__place_probe' && !e.closest('#__place_probe'));
    real = els.length ? Object.assign({count: els.length}, shown(els[0])) : {count: 0, ok: true, why: '本物の入れ物は画面に無い（中身が無い）'};
  }
  return {textLength: text.trim().length, media, errors: found, real};
}
"""

PROBE_JS = r"""
({probe, samples}) => {
""" + SEEN_JS + r"""
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
  outer.style.cssText = 'position:fixed;inset:auto;left:12px;top:12px;width:560px;height:auto;max-height:none;overflow:visible;z-index:2147483647;background:#fff;padding:18px 20px;box-shadow:0 2px 14px rgba(0,0,0,.25);border-radius:12px;display:block;opacity:1;visibility:visible';
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
    const vis = shown(el);
    let ok = vis.ok, why = vis.why;
    if (sel.endsWith('li')) {
      ok = ok && cs.display === 'list-item' && cs.listStyleType !== 'none';
      why = [why, `display=${cs.display} list-style-type=${cs.listStyleType}`].filter(Boolean).join(' ');
    } else if (sel === 'td') {
      // 表として並んでいて、どこかに罫線がある（枠の表も、行の下線だけの表も）
      const line = (x) => x && ['Top', 'Bottom', 'Left', 'Right'].some((k) => parseFloat(getComputedStyle(x)['border' + k + 'Width']) > 0 && getComputedStyle(x)['border' + k + 'Style'] !== 'none');
      const lined = [el, el.parentElement, inner.querySelector('th'), inner.querySelector('thead')].some(line);
      ok = ok && cs.display === 'table-cell' && lined;
      why = [why, `display=${cs.display} 罫線=${lined ? 'あり' : '無し'}`].filter(Boolean).join(' ');
    } else if (sel === 'h3' || sel === 'strong') {
      ok = ok && (parseInt(cs.fontWeight) >= 600 || parseFloat(cs.fontSize) > parseFloat(base.fontSize) * 1.15);
      why = [why, `font-weight=${cs.fontWeight} font-size=${cs.fontSize}`].filter(Boolean).join(' ');
    } else if (sel === 'code') {
      ok = ok && (cs.backgroundColor !== base.backgroundColor || cs.fontFamily !== base.fontFamily);
      why = [why, `font=${cs.fontFamily.slice(0, 30)} bg=${cs.backgroundColor}`].filter(Boolean).join(' ');
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


def blank_ratio(png: Path) -> float:
    """画面の中で、いちばん多い色と違う画素の割合（白紙なら 0 に近い）。"""
    from PIL import Image
    im = Image.open(png).convert("RGB").resize((240, 150))
    colors = im.getcolors(240 * 150) or []
    if not colors:
        return 1.0
    top = max(colors)[0]
    return 1 - top / (240 * 150)


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


EXPECT_JS = r"""
({visible, texts, noTexts}) => {
""" + SEEN_JS + r"""
  const text = document.body ? document.body.innerText || '' : '';
  const out = [];
  for (const sel of visible) {
    let els = [];
    try { els = [...document.querySelectorAll(sel)].filter((e) => !e.closest('#__place_probe')); } catch (e) { out.push({what: sel, ok: false, why: 'CSS が読めない: ' + e.message}); continue; }
    const vis = els.map(shown);
    const ok = vis.some((v) => v.ok);
    out.push({what: sel, ok, why: ok ? '' : (els.length ? vis[0].why : '無い')});
  }
  for (const t of texts) out.push({what: `「${t}」が出る`, ok: text.includes(t), why: text.includes(t) ? '' : '出ていない'});
  for (const t of noTexts) out.push({what: `「${t}」が出ない`, ok: !text.includes(t), why: text.includes(t) ? '出ている' : ''});
  return out;
}
"""

PHONE = {"viewport": {"width": 360, "height": 780}, "device_scale_factor": 3, "is_mobile": True, "has_touch": True,
         "user_agent": "Mozilla/5.0 (Linux; Android 14; SM-S921Q) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"}


def expectations(a) -> list[str]:
    return ([f"見本:{x}" for x in a.expect_shows] + [f"部品:{x}" for x in a.expect_visible]
            + [f"字:{x}" for x in a.expect_text] + [f"無い字:{x}" for x in a.expect_no_text])


def judge(record: dict, path: str) -> dict[str, list[str]]:
    """測った結果 → 項目ごとの NG の理由（空なら OK）。--expect-… を付けた時は「みきさんの言う所」も。"""
    reach, real, sample = [], [], []
    final = record.get("final_path") or ""
    if record.get("error"):
        reach.append(record["error"])
    if record.get("status") and record["status"] >= 400:
        reach.append(f"応答が {record['status']}")
    if final and not final.startswith(path.split("?")[0]):
        reach.append(f"{final} に移された")
    elif any(final.startswith(a) for a in AWAY_PATHS) and not path.startswith(final):
        reach.append(f"{final} に移された")
    page = record.get("page") or {}
    if page.get("errors"):
        real.append("画面にエラーが出ている: " + "、".join(page["errors"]))
    for e in record.get("page_errors") or []:
        real.append(f"画面のエラー: {e}")
    if record.get("blank") is not None and record["blank"] < 0.003 and page.get("textLength", 0) < 5:
        real.append("白紙")
    if page.get("real") and not page["real"].get("ok"):
        real.append(f"本物の入れ物が見えない（{page['real'].get('why')}）")
    probe = record.get("probe") or {}
    if probe.get("error"):
        sample.append(probe["error"])
    for name, r in (probe.get("results") or {}).items():
        if not r["ok"]:
            sample.append(f"{name}が見えない（{r['why']}）")
    if record.get("probe_blank") is not None and record["probe_blank"] < 0.01:
        sample.append("見本の吹き出しが白紙")
    out = {"着いたか": reach, "本物の画面": real, "見本": sample}
    if record.get("expect") is not None:
        out["みきさんの言う所"] = [f"{e['what']}：{e['why']}" for e in record["expect"] if not e["ok"]]
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("place")
    ap.add_argument("--tag", default="now", choices=["before", "after", "now"])
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--path", help="地図の open の代わりに開く道")
    ap.add_argument("--out", help="証拠を置く所（既定 .data/place_shots/<場所>）")
    ap.add_argument("--width", type=int, default=1440)
    ap.add_argument("--height", type=int, default=900)
    ap.add_argument("--no-login", action="store_true", help="入館証を入れずに開く（試験用）")
    ap.add_argument("--phone", action="store_true", help="スマホの幅（360×780・指で触る端末）で開く")
    ap.add_argument("--expect-shows", action="append", default=[], metavar="名前", help="この見本が見えるはず（地図の shows の名前）")
    ap.add_argument("--expect-visible", action="append", default=[], metavar="CSS", help="この部品が見えるはず")
    ap.add_argument("--expect-text", action="append", default=[], metavar="字", help="この字が画面に出るはず")
    ap.add_argument("--expect-no-text", action="append", default=[], metavar="字", help="この字が画面に出ないはず")
    a = ap.parse_args(argv)
    unknown = [x for x in a.expect_shows if x not in SAMPLES]
    if unknown:
        ap.error(f"--expect-shows の名前は {'・'.join(SAMPLES)} のどれか（{'・'.join(unknown)} は無い）")
    expects = expectations(a)

    pid = pm.place_id(a.place)
    m = pm.place_map(pid)
    covers = [c for c in ((m or {}).get("meta", {}).get("covers") or []) if c != pid]
    tail = f"place={pid} covers={','.join(covers)} tag={a.tag}"
    root = f"root={pm.tree_of(pid).as_posix()}"
    if not m:
        print(f"地図がありません（{pid}）。成果物なら python scripts/place_map.py draft {pid.split(':', 1)[-1]}")
        print(f"[place_shot] {tail} result=UNREACHABLE {root}")
        return 2
    meta = m["meta"]
    path = a.path or meta.get("open")
    if not path:
        print(f"この場所はブラウザでは開けません: {meta.get('reach') or '地図の「行き方」を見る'}")
        print(f"[place_shot] {tail} result=UNREACHABLE {root}")
        return 2
    base = a.base.rstrip("/")
    if any(x in base for x in REFUSED_BASES):
        print(f"本番の受け口（{base}）には試験で入りません。3001 か作業場所の画面のサーバーを使ってください。")
        print(f"[place_shot] {tail} result=UNREACHABLE {root}")
        return 2
    out = Path(a.out) if a.out else ROOT / ".data" / "place_shots" / pid.replace(":", "_")
    out.mkdir(parents=True, exist_ok=True)

    from playwright.sync_api import sync_playwright
    tok = "" if a.no_login else token()
    auth = json.dumps({"state": {"user": {**TEST_USER, "full_name": TEST_USER["name"]}, "token": tok, "isAuthenticated": True}, "version": 0})
    host = base.split("://", 1)[-1].split("/")[0].split(":")[0]
    record: dict = {"place": pid, "tag": a.tag, "url": base + path, "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    probe = meta.get("probe") or {}
    shows = [s for s in (meta.get("shows") or []) if s in SAMPLES]
    shows += [s for s in a.expect_shows if s not in shows]
    if a.expect_shows and not probe:
        print("この場所の地図に probe（吹き出しの入れ物）が無いので、見本は入れられません。--expect-visible で部品を指してください。")
        print(f"[place_shot] {tail} result=UNREACHABLE {root}")
        return 2
    if a.phone:
        record["device"] = "phone 360x780"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            ctx = browser.new_context(**(PHONE if a.phone else {"viewport": {"width": a.width, "height": a.height}, "device_scale_factor": 1}),
                                      locale="ja-JP")
            if tok:
                ctx.add_cookies([{"name": "done_access_token", "value": tok, "domain": host, "path": "/"}])
                ctx.add_init_script(f"try{{localStorage.setItem('done-token',{json.dumps(tok)});localStorage.setItem('done-auth',{json.dumps(auth)});}}catch(e){{}}")
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e).splitlines()[0][:200]))
            try:
                resp = page.goto(base + path, wait_until="domcontentloaded", timeout=90_000)
                record["status"] = resp.status if resp else 0
                if meta.get("ready") and pm.TODO not in str(meta["ready"]):
                    page.wait_for_selector(meta["ready"], state="visible", timeout=60_000)
            except Exception as e:  # noqa: BLE001 - 開けなかった理由をそのまま残す
                record["error"] = f"開けなかった・目当ての部品が出なかった: {str(e).splitlines()[0][:200]}"
            try:   # 画面は数十秒ごとに読み直し、開発サーバーは更新の知らせをつなぎっぱなしにするので、静まるまでは待ち切らない
                page.wait_for_load_state("networkidle", timeout=8_000)
            except Exception:  # noqa: BLE001
                pass
            page.wait_for_timeout(800)
            record["final_path"] = "/" + page.url.split("://", 1)[-1].split("/", 1)[-1] if "://" in page.url else page.url
            record["page"] = page.evaluate(PAGE_JS, {"errors": ERROR_TEXTS + list(meta.get("errors") or []), "probe": probe})
            if expects:
                record["expect"] = page.evaluate(EXPECT_JS, {"visible": a.expect_visible, "texts": a.expect_text, "noTexts": a.expect_no_text})
            page.screenshot(path=str(out / f"{a.tag}-page.png"))
            record["blank"] = blank_ratio(out / f"{a.tag}-page.png")
            if probe and shows:
                res = page.evaluate(PROBE_JS, {"probe": probe, "samples": [[s, *SAMPLES[s]] for s in shows]})
                record["probe"] = res
                if expects:
                    for name in a.expect_shows:
                        r = (res.get("results") or {}).get(name) or {"ok": False, "why": res.get("error") or "見本が入らなかった"}
                        record["expect"].insert(0, {"what": f"見本の{name}", "ok": r["ok"], "why": r["why"]})
                if res.get("rect"):
                    r = res["rect"]
                    page.screenshot(path=str(out / f"{a.tag}.png"), clip={"x": r["x"], "y": r["y"], "width": r["width"], "height": min(r["height"], 4000)})
                    record["probe_blank"] = blank_ratio(out / f"{a.tag}.png")
            else:
                shutil.copyfile(out / f"{a.tag}-page.png", out / f"{a.tag}.png")
            record["page_errors"] = errors[:5]
        finally:
            browser.close()

    checks = judge(record, path)
    if expects:
        # みきさんの言う崩れがここでも出たか。出たら「見本」の欄では数えず、「みきさんの言う所」だけで数える（同じ物を2回 NG にしない）
        record["repro"] = "YES" if checks.get("みきさんの言う所") else "NO"
        if a.expect_shows:
            checks["見本"] = [w for w in checks["見本"] if not any(w.startswith(n + "が見えない") for n in a.expect_shows)]
    record["checks"] = checks
    (out / f"{a.tag}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"開いた: {base}{record.get('final_path') or path}")
    for name, why in checks.items():
        print(f"  {'○' if not why else '×'} {name}" + ("" if not why else "：" + " / ".join(why)))
    for name, r in ((record.get("probe") or {}).get("results") or {}).items():
        print(f"      {'○' if r['ok'] else '×'} {name}（{r['why']}）")
    print(f"撮った: {out / (a.tag + '.png')}")
    if a.tag == "after":
        c = compare(out)
        if c:
            print(f"前と後: {c}")
    bad = any(checks.values())
    if expects:
        print("再現した（みきさんの言う崩れがこの画面でも出た）" if record["repro"] == "YES" else "再現しなかった（この画面ではみきさんの言う物が見えている）")
    extra = f" expect={len(expects)} repro={record['repro']}" if expects else ""
    print(f"[place_shot] {tail} result={'NG' if bad else 'OK'} {root}{extra}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
