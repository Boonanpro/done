# -*- coding: utf-8 -*-
"""画像LPの文字を本物のテキストに置き換える（実テキスト化）ツール。

清書済みタイルの文字を検出→消去→同じ見た目のwebフォント文字を重ねた
編集可能ページ(EditableText)を生成する。方式はA案=全文字フォント統一
（2026-08-23確定。混在は違和感を生むため、置換する行は全部フォントにする）。

使い方:
    python scripts/lp_textify.py --spec textify_spec.json run

spec（ダンが清書時の文言から書き起こす）:
{
  "slug": "example",                     # 出力先 artifacts/<slug>/ の名前
  "editid_prefix": "example",            # editIdの接頭辞
  "tiles": [
    { "image": "tmp/xxx/tile1.png",
      "regions": [
        { "box": [x0,y0,x1,y1],          # 文字ブロックを囲む領域(タイル画像のピクセル座標。以下同)
          "erase": "fill",               # fill=塗り / generative=生成消去 / none=消さない(検証用)
          "halo": "#FFFFFF",             # 光彩(CSS再現。省略可)。他に shadow/stroke/grad も可(deco_css参照)
          "erase_prompt": null,          # 生成消去プロンプトの差し替え(既定=グリフだけ消し装飾は残す)
          "lines": [                     # 上から順に、行ごとのテキスト
            [["窓の冷気を、", null]],     # [文字列, 色hex(null=自動)] のセグメント列
            [["貼るだけで止める。", null]]
          ],
          "force": null,                 # "keep"=絵のまま残す(ロゴ等の装飾文字) / null=置換(既定)
          "overrides": {"0": {"y": 105, "h": 152,    # 行番号(0始まり)→手動上書き
                              "ebox": [x0,y0,x1,y1]}}  # 対応キー: x/y/w/h(配置)・color・
                                                       # wt(100-900)/fam(フォント名)・stretch(横スケール。
                                                       # 元フォントとの字幅差の吸収)・ebox(消去範囲の明示。面塗り)
        } ] } ]
}

出力:
- frontend/public/scratch/<slug>/bg_tileN.png   消去済み背景
- frontend/src/app/artifacts/<slug>/page.tsx + page-body.tsx  編集可能ページ
- レポート(置換数・装飾注意の助言)を標準出力へ。keepは自動では行わない
  — force:"keep" を書いた場合のみ。「装飾注意」は目視判断のきっかけに使う

既知の限界（手動overridesで対処）:
- 高さの差が25%未満の連続行は1段落に併合され、1行目のスタイルが全行に適用される
  → サイズの違う行は別regionに分けるか、overridesでhを揃える
- 発光ハロー付きの見出しは行検出が乱れる → y/h を目視実測で上書き
- 枠(チップ)内の文字の縦センタリングは枠を検出しない → y を上書き
- force:"keep" で絵のまま残した装飾文字の編集は従来の部分修正で行う
- 生成消去キャッシュのキーはタイル名+box+プロンプト。タイル画像自体を
  差し替えた時は workdir の gencache_*.png を削除しないと古い結果が貼られる

検証ゲート(実行のたび自動):
- 元タイルと配信ページを文字ブロックごとに低周波diffで機械比較
- FAIL(>=0.12)=確実な劣化。直すまで不合格 / WARN(0.035-0.12)=workdir/verify/ の
  比較画像を全部ズームで目視して判断 / devサーバーに繋がらない時は「検証未実施」
"""
from __future__ import annotations
import argparse, io, json, os, subprocess, sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent

FONT_CSS = "https://fonts.googleapis.com/css2?family=Noto+Serif+JP:wght@500&family=Noto+Sans+JP:wght@400;500;700;900&display=swap"
PROFILE_KEEP_THRESHOLD = 0.18   # 5a検証: 文字ごとの大きさリズム距離がこれ以上なら装飾=絵のまま残す


def contrast_ink(g, sat, x0, y0, x1, y1):
    """行ごとの背景との差でインク画素を取る（明暗どちらの背景でも動く）"""
    sub = g[y0:y1, x0:x1].astype(float)
    row = np.median(sub, axis=1)[:, None]
    ink = np.abs(sub - row) > 45
    ss = sat[y0:y1, x0:x1]
    sr = np.median(ss, axis=1)[:, None]
    return ink | (np.abs(ss - sr) > 60)


def detect_lines(im, region):
    g = np.asarray(im.convert("L")).astype(int)
    rgb = np.asarray(im).astype(int)
    sat = rgb.max(axis=2) - rgb.min(axis=2)
    x0, y0, x1, y1 = region["box"]
    ink = contrast_ink(g, sat, x0, y0, x1, y1)
    prof = ink.mean(axis=1)
    bands = []
    s = None
    for y, v in enumerate(prof):
        if v > 0.01 and s is None:
            s = y
        elif v <= 0.01 and s is not None:
            if y - s > 16:
                bands.append((y0 + s, y0 + y))
            s = None
    if s is not None:
        bands.append((y0 + s, y1))
    lines = region["lines"]
    # バンド不足: いちばん高いバンドを谷(インク最小行)で割る
    while len(bands) < len(lines):
        bi = max(range(len(bands)), key=lambda i: bands[i][1] - bands[i][0])
        b0, b1 = bands[bi]
        r0, r1 = b0 - y0, b1 - y0
        m = int(0.2 * (r1 - r0))
        cut = y0 + r0 + m + int(np.argmin(prof[r0 + m:r1 - m]))
        bands[bi:bi + 1] = [(b0, cut), (cut, b1)]
    if len(bands) > len(lines):
        print(f"  !! 行数警告: 検出{len(bands)} > 指定{len(lines)} box={region['box']} -> 背の高い順に採用")
        bands = sorted(sorted(bands, key=lambda b: b[0] - b[1])[:len(lines)])
    out = []
    for band, segs in zip(bands, lines):
        by0, by1 = band
        seg_ink = contrast_ink(g, sat, x0, by0, x1, by1)
        cols = np.where(seg_ink.any(axis=0))[0]
        lx0, lx1 = x0 + int(cols.min()), x0 + int(cols.max())
        a = np.asarray(im)[by0:by1, lx0:lx1 + 1]
        m2 = seg_ink[:, cols.min():cols.max() + 1]
        ink_px = a[m2].astype(float)
        # 部分色の行: 明示色セグメントの画素を除いて地色を測る
        # （色付き語が行の過半だと中央値が汚染され、白のはずの部分まで色が付く事故対策）
        expl = [c for _, c in segs if c]
        if expl and any(c is None for _, c in segs):
            keep = np.ones(len(ink_px), bool)
            for hexc in expl:
                ec = np.array([int(hexc[i:i + 2], 16) for i in (1, 3, 5)], float)
                keep &= np.abs(ink_px - ec).sum(axis=1) > 120
            if keep.sum() > len(ink_px) * 0.1:
                ink_px = ink_px[keep]
        color = "#%02X%02X%02X" % tuple(int(v) for v in np.median(ink_px, axis=0))
        out.append(dict(y=int(by0), h=int(by1 - by0), x=int(lx0), w=int(lx1 - lx0),
                        ey=int(by0), eh=int(by1 - by0), ex=int(lx0), ew=int(lx1 - lx0),
                        color=color, density=float(m2.mean()), segs=segs))
    return out


def glyph_profile(mask, min_h_ratio=0.15):
    lab, n = ndimage.label(mask)
    H = mask.shape[0]
    boxes = []
    for sl in ndimage.find_objects(lab):
        hh = sl[0].stop - sl[0].start
        if hh < H * min_h_ratio and (sl[1].stop - sl[1].start) < H * 0.1:
            continue
        boxes.append([sl[1].start, sl[1].stop, sl[0].start, sl[0].stop])
    boxes.sort()
    merged = []
    for b in boxes:
        if merged and b[0] < merged[-1][1] - 2:
            m = merged[-1]
            m[1] = max(m[1], b[1]); m[2] = min(m[2], b[2]); m[3] = max(m[3], b[3])
        else:
            merged.append(list(b))
    hs = np.array([m[3] - m[2] for m in merged], dtype=float)
    return (hs / hs.max()) if len(hs) else None


def font_for(density):
    if density < 0.17:
        return "Noto Serif JP", 500
    if density < 0.27:
        return "Noto Sans JP", 500
    if density < 0.36:
        return "Noto Sans JP", 700
    return "Noto Sans JP", 900


def group_lines(lines):
    """同サイズ・行間一定・横位置が重なる連続行を段落に束ねる。
    整列は3択: 左揃え(既定) / 中央揃え(各行の中心が揃う) / どちらでもない→行単位に分割
    （揃っていないのに段落へ束ねると行のxが再現できない。実測: 中央揃え誤判定で
    行が勝手にセンタリングされた事故 2026-08-24 safeguard）"""
    groups = []
    for l in lines:
        if groups:
            p = groups[-1][-1]
            ox = max(0, min(p["x"] + p["w"], l["x"] + l["w"]) - max(p["x"], l["x"]))
            xov = ox / max(1, min(p["w"], l["w"]))
            same = (abs(p["h"] - l["h"]) < 0.25 * max(p["h"], l["h"])
                    and 0 < l["y"] - (p["y"] + p["h"]) < 1.6 * max(p["h"], l["h"])
                    and xov > 0.4)
            if same:
                groups[-1].append(l)
                continue
        groups.append([l])
    # 整列判定: 左端も中心も揃わないグループは行単位にばらす
    split = []
    for g in groups:
        if len(g) == 1:
            split.append(g)
            continue
        lefts = [x["x"] for x in g]
        centers = [x["x"] + x["w"] / 2 for x in g]
        left_ok = max(lefts) - min(lefts) <= 12
        center_ok = max(centers) - min(centers) <= 12
        if left_ok or center_ok:
            g[0]["_centered"] = (not left_ok) and center_ok
            split.append(g)
        else:
            split.extend([x] for x in g)
    groups = split
    for g in groups:
        d = float(np.median([x["density"] for x in g]))
        fam, wt = font_for(d)
        for x in g:
            # overridesの明示指定(wt/fam)は密度分類より優先
            x["fam"] = x.get("fam") if isinstance(x.get("fam"), str) else fam
            x["wt"] = x.get("wt") if isinstance(x.get("wt"), int) else wt
    return groups


def line_text(l):
    return "".join(s[0] for s in l["segs"])


def est_size_ls(l):
    size = max(8, round(l["h"] / 1.16))
    n = sum(0.55 if ord(c) < 0x3000 else 1 for c in line_text(l))
    ls = max(0, round((l["w"] / n - size) / size, 3))
    if ls > 0.35:
        ls = 0.04
    return size, ls


def calibrate_and_judge(all_groups, workdir):
    """各グループ1行目を実際に描いて測る: 位置較正 + 置換/keep判定(5a)を一度に"""
    from playwright.sync_api import sync_playwright
    rows = []
    flat = [g for _, _, gs in all_groups for g in gs]
    for gi, g in enumerate(flat):
        l = g[0]
        size, ls = est_size_ls(l)
        l["_size0"], l["_ls0"] = size, ls
        rows.append(f'<div class="c" id="g{gi}" style="font:{l["wt"]} {size}px/1.3 \'{l["fam"]}\';letter-spacing:{ls}em">{line_text(l)}</div>')
    html = ('<!doctype html><html><head><meta charset="utf-8"><style>'
            f"@import url('{FONT_CSS}');"
            "body{margin:0;background:#fff}.c{color:#000;display:block;margin:40px;white-space:nowrap;width:max-content}"
            '</style></head><body>' + "\n".join(rows) + "</body></html>")
    page_path = Path(workdir) / "calib.html"
    io.open(page_path, "w", encoding="utf-8").write(html)
    meas = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1900, "height": 1600})
        pg.goto(page_path.resolve().as_uri())
        # webフォント読込完了を必ず待つ。待たないとフォールバック字形で採寸し
        # サイズ・字間・位置が全部狂う(実行ごとに揺れる非決定性の原因)
        try:
            pg.wait_for_function("document.fonts.status === 'loaded'", timeout=15000)
        except Exception:
            print("  !! webフォント読込を確認できないまま採寸(結果が狂う可能性)")
        pg.wait_for_timeout(500)
        for gi in range(len(flat)):
            el = pg.query_selector(f"#g{gi}")
            shot = Path(workdir) / f"_c{gi}.png"
            el.screenshot(path=str(shot))
            a = np.asarray(Image.open(shot).convert("L"))
            ys, xs = np.where(a < 128)
            meas.append(dict(top=int(ys.min()), h=int(ys.max() - ys.min() + 1),
                             left=int(xs.min()), w=int(xs.max() - xs.min() + 1), mask=(a < 128)))
        b.close()
    return flat, meas


def rowfill_erase(arr, orig, l):
    """行の左マージン色で行ごとに塗る（チップ・ボタン内でも背景色を正しく拾う）。
    消去は必ず検出座標(ey/eh/ex/ew)で行う — overridesは配置専用で消去位置を動かさない"""
    if l.get("eflat"):
        # 明示ebox: 箱内の非文字ピクセルの中央値で面塗り（無地下地専用）
        x0, y0 = l["ex"], l["ey"]
        x1, y1 = x0 + l["ew"], y0 + l["eh"]
        sub = orig[y0:y1, x0:x1].astype(float)
        lum = sub.mean(axis=2)
        ink = np.abs(lum - np.median(lum)) > 45
        fill = np.median(sub[~ink].reshape(-1, 3), axis=0) if (~ink).any() else np.median(sub.reshape(-1, 3), axis=0)
        arr[y0:y1, x0:x1] = fill.astype(np.uint8)
        return
    lx0, lx1 = l["ex"], l["ex"] + l["ew"]
    X0, X1 = max(0, lx0 - 10), min(orig.shape[1], lx1 + 10)
    # 左右マージンのうち「その行の背景色」に近い側から塗り色を取る
    band = orig[max(0, l["ey"] - 4):l["ey"] + l["eh"] + 4, X0:X1]
    bg_est = np.median(band.reshape(-1, 3), axis=0)
    for yy in range(max(0, l["ey"] - 4), min(orig.shape[0], l["ey"] + l["eh"] + 4)):
        lm = np.median(orig[yy, X0:X0 + 6], axis=0)
        rm = np.median(orig[yy, max(0, X1 - 6):X1], axis=0)
        fill = lm if np.abs(lm - bg_est).sum() <= np.abs(rm - bg_est).sum() else rm
        arr[yy, X0:X1] = fill


def generative_erase(tile_path, region, out_path, quality="low", cache_dir=None, tname=""):
    """gpt_image + lp_image_patch で領域内の文字を生成消去。
    結果の領域cropをキャッシュし、同じbox指定の再実行ではAPIを呼ばず貼り戻す
    （spec調整の反復でコストと非決定性を出さないため）"""
    x0, y0, x1, y1 = region["box"]
    # 消すのはグリフだけ。光彩・下地・帯などの装飾は元デザインの一部なので背景側に残す
    # （残った装飾の上にwebフォント文字を重ねれば装飾はCSSで作り直さなくて済む）
    prompt = region.get("erase_prompt") or (
        "添付画像の指定領域にある文字（グリフ）だけを消してください。"
        "文字の周りにある白い光彩・ぼかし・下地・帯などの装飾はそのまま残してください。"
        "文字があった場所は、その装飾や背景の続きとして自然に描いてください。"
        "文字と重なっていない要素は一切変えないでください。\n")
    import hashlib
    ph = hashlib.md5(prompt.encode("utf-8")).hexdigest()[:8]
    cache = Path(cache_dir) / f"gencache_{tname}_{x0}_{y0}_{x1}_{y1}_{ph}.png" if cache_dir else None
    if cache and cache.exists():
        base = Image.open(out_path).convert("RGB")
        base.paste(Image.open(cache).convert("RGB"), (x0, y0))
        base.save(out_path)
        print(f"  (生成消去キャッシュ再利用: {cache.name})")
        return
    im = Image.open(tile_path)
    w, h = im.size
    tmp = str(out_path) + ".genraw.png"
    r = subprocess.run([sys.executable, "scripts/gpt_image.py", "--image", str(tile_path),
                        "--size", f"{w}x{h}", "--quality", quality, "--out", tmp],
                       input=prompt.encode("utf-8"), capture_output=True, cwd=str(ROOT))
    if not os.path.exists(tmp):
        raise RuntimeError(f"生成消去に失敗: {r.stdout[-300:]} {r.stderr[-300:]}")
    subprocess.run([sys.executable, "scripts/lp_image_patch.py", "--original", str(tile_path),
                    "--edited", tmp, "--region", f"{x0},{y0},{x1},{y1}", "--out", str(out_path)],
                   capture_output=True, cwd=str(ROOT))
    if cache:
        Image.open(out_path).convert("RGB").crop((x0, y0, x1, y1)).save(cache)


def deco_css(region):
    """regionの装飾指定→CSS。文言を編集しても装飾が付いてくるのがCSS再現の利点。
    - halo: "#FFF" or {"color","blur"(em基準,既定0.5)} → 光彩(text-shadowの重ね)
    - shadow: {"color","x","y","blur"}(px) → ドロップシャドウ
    - stroke: {"color","width"}(px) → 縁取り(-webkit-text-stroke。太い縁は苦手)
    - grad: {"from","to","angle"(既定180deg)} → グラデ文字
    """
    out = ""
    halo = region.get("halo")
    if halo:
        hc = halo if isinstance(halo, str) else halo.get("color", "#FFFFFF")
        bl = 0.5 if isinstance(halo, str) else float(halo.get("blur", 0.5))
        # 各半径2重掛けで濃度を出す(1重だとtext-shadowの光彩は薄く負ける)
        layers = ", ".join(f"0 0 {round(bl*m,2)}em {hc}" for m in (0.3, 0.3, 0.8, 0.8, 1.6, 1.6, 2.6, 2.6))
        out += f', textShadow:"{layers}"'
    sh = region.get("shadow")
    if sh:
        out += f', textShadow:"{sh.get("x",0)}px {sh.get("y",4)}px {sh.get("blur",8)}px {sh.get("color","rgba(0,0,0,.35)")}"'
    st = region.get("stroke")
    if st:
        out += f', WebkitTextStroke:"{st.get("width",2)}px {st.get("color","#FFFFFF")}"'
    gr = region.get("grad")
    if gr:
        out += (f', background:"linear-gradient({gr.get("angle","180deg")}, {gr["from"]}, {gr["to"]})", '
                f'WebkitBackgroundClip:"text", backgroundClip:"text", color:"transparent"')
    return out


def emit_page(spec, tiles_data, out_dir_pages, slug, prefix):
    blocks = []
    eid = 0
    total_h = 0
    for tname, (w, h), groups in tiles_data:
        total_h += h
        els = []
        for g in groups:
            if g[0].get("_keep"):
                continue
            l = g[0]
            size1, top, left, ls = l["_size1"], l["_top"], l["_left"], l["_ls1"]
            lh = round((g[1]["y"] - g[0]["y"]) / size1, 2) if len(g) > 1 else 1.25
            centered = bool(g[0].get("_centered"))
            span = max(x["x"] + x["w"] for x in g) - min(x["x"] for x in g)
            # 部分色: 行色と違う明示色セグメントは<span>で色を付ける(編集で上書きされるまで有効)
            parts = []  # [text, colorOrNone]
            for li, x in enumerate(g):
                if li:
                    parts.append(["\n", None])
                for t, c in x["segs"]:
                    cc = c if (c and c.upper() != l["color"].upper()) else None
                    if parts and parts[-1][1] == cc:
                        parts[-1][0] += t
                    else:
                        parts.append([t, cc])
            child = "".join(
                ("{" + json.dumps(t, ensure_ascii=False) + "}") if c is None else
                (f'<span style={{{{ color:"{c}" }}}}>{{{json.dumps(t, ensure_ascii=False)}}}</span>')
                for t, c in parts)
            style = (f'position:"absolute", top:{top}, left:{left}, margin:0, whiteSpace:"pre", '
                     f'font:"{l["wt"]} {size1}px/{lh} \'{l["fam"]}\'", letterSpacing:"{ls}em", color:"{l["color"]}"')
            if centered:
                style += f', width:{span + 24}, textAlign:"center"'
            if float(l.get("stretch", 1.0)) != 1.0:
                # 元デザインのフォントとwebフォントの字幅比を横スケールで吸収
                style += f', transform:"scaleX({l["stretch"]})", transformOrigin:"left top"'
            style += deco_css(l["_region"])
            els.append(f'        <EditableText as="p" editId="{prefix}-{tname}-g{eid}" '
                       f'style={{{{ {style} }}}}>{child}</EditableText>')
            eid += 1
        blocks.append((tname, w, h, els))
    tile_html = []
    for tname, w, h, els in blocks:
        tile_html.append(f'''      <div style={{{{ position:"relative", width:{w}, height:{h} }}}}>
        {{/* eslint-disable-next-line @next/next/no-img-element */}}
        <img src="/scratch/{slug}/bg_{tname}.png" alt="{tname}" style={{{{ position:"absolute", inset:0, pointerEvents:"none" }}}} />
{chr(10).join(els)}
      </div>''')
    body = f'''"use client";

import {{ useEffect }} from "react";
import {{ EditableText }} from "@/components/dan/editable";

/** lp_textify.py 自動生成: 画像LPの編集可能版（全文字フォント統一） */

const W = 1520;
const H = {total_h};

export function PageBody() {{
  useEffect(() => {{
    const fit = () => {{
      const s = Math.min(1, document.documentElement.clientWidth / W);
      const w = document.getElementById("textify-wrap");
      const o = document.getElementById("textify-outer");
      if (w) w.style.transform = `scale(${{s}})`;
      if (o) o.style.height = `${{H * s}}px`;
    }};
    fit();
    window.addEventListener("resize", fit);
    return () => window.removeEventListener("resize", fit);
  }}, []);

  return (
    <div id="textify-outer" style={{{{ width: "100%", overflow: "hidden" }}}}>
      <div id="textify-wrap" style={{{{ width: W, transformOrigin: "top left" }}}}>
{chr(10).join(tile_html)}
      </div>
    </div>
  );
}}
'''
    os.makedirs(out_dir_pages, exist_ok=True)
    io.open(Path(out_dir_pages) / "page-body.tsx", "w", encoding="utf-8").write(body)
    page = '''import { EditableProvider } from "@/components/dan/editable";
import { toEditableOverrides, type ReleaseOverrides } from "@/lib/editable-release";
import releaseJson from "./release.gen.json";
import { PageBody } from "./page-body";

export default function Page() {
  return (
    <EditableProvider overrides={toEditableOverrides(releaseJson as ReleaseOverrides)}>
      <PageBody />
    </EditableProvider>
  );
}
'''
    pp = Path(out_dir_pages) / "page.tsx"
    if not pp.exists():
        io.open(pp, "w", encoding="utf-8").write(page)
    rp = Path(out_dir_pages) / "release.gen.json"
    if not rp.exists():
        io.open(rp, "w", encoding="utf-8").write("{}")


VERIFY_FAIL = 0.12    # 確実な劣化(edittest較正: 光彩欠落0.20)→修正するまで不合格
VERIFY_WARN = 0.035   # 要目視(較正: 良好0.03〜0.09が混在する帯。比較画像を必ず見る)


def _lowfreq_diff(a_img, b_img, glyph_h):
    """フォント形状の違いを均して装飾・位置・色の劣化だけを測る低周波diff(0..1)。
    - 縮小率は文字高で正規化(グリフ高→約8px)。固定率だと文字サイズで感度が変わる
    - 約1グリフ幅の短冊ごとに±1px(縮小後)の局所シフトを許容。フォント字形差による
      文字ごとの微小な位置ずれ(視覚的に合格の水準)を罰しないため。
      装飾欠落・ゴースト・帯はグリフ形と無関係に面で残るのでシフトでは消えない"""
    f = max(1.0, glyph_h / 8.0)
    w = max(16, round(a_img.width / f))
    h = max(16, round(a_img.height / f))
    a = np.asarray(a_img.resize((w, h), Image.BILINEAR)).astype(float)
    b = np.asarray(b_img.resize((w, h), Image.BILINEAR)).astype(float)
    total = 0.0
    n = 0
    for sx in range(0, w, 8):
        aa = a[:, sx:sx + 8]
        best = None
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                bx0 = sx + dx
                if bx0 < 0 or bx0 + aa.shape[1] > w:
                    continue
                bb = b[max(0, dy):h + min(0, dy), bx0:bx0 + aa.shape[1]]
                a2 = aa[max(0, -dy):h + min(0, -dy), :]
                d = float(np.abs(a2 - bb).mean())
                best = d if best is None else min(best, d)
        total += best * aa.shape[1]
        n += aa.shape[1]
    return total / max(1, n) / 255.0


def _suggest_deco(orig_arr, l):
    """不合格ブロックの元画像から装飾の候補を推定して提案文を返す(適用はしない)"""
    x0 = max(0, l["x"] - 6); y0 = max(0, l["y"] - 6)
    x1 = min(orig_arr.shape[1], l["x"] + l["w"] + 6); y1 = min(orig_arr.shape[0], l["y"] + l["h"] + 6)
    sub = orig_arr[y0:y1, x0:x1].astype(float)
    lum = sub.mean(axis=2)
    ink = np.abs(lum - np.median(lum)) > 45
    ring = ndimage.binary_dilation(ink, iterations=10) & ~ndimage.binary_dilation(ink, iterations=2)
    if not ring.any():
        return None
    ring_med = np.median(sub[ring], axis=0)
    # 遠景(ブロック外周リング)と比較して、文字周りだけ明るければ光彩、暗ければ影
    px0 = max(0, x0 - 40); py0 = max(0, y0 - 40)
    far = orig_arr[py0:y1 + 40, px0:x1 + 40].astype(float)
    far_med = np.median(far.reshape(-1, 3), axis=0)
    d = ring_med.mean() - far_med.mean()
    hexc = "#%02X%02X%02X" % tuple(int(v) for v in ring_med)
    if d > 18:
        return f'"halo": "{hexc}" (文字周りが遠景より+{d:.0f}明るい=光彩の疑い)'
    if d < -18:
        return f'"shadow": {{...}} または "stroke" (文字周りが遠景より{d:.0f}暗い=影/縁取りの疑い)'
    return None


def verify(spec, tiles_data, workdir, slug, origin):
    """忠実度ゲート: 元タイルと実際に配信されるページを文字ブロックごとに機械比較。
    再現できていないブロック(装飾欠落・ゴースト・ズレ)を数値と比較画像で列挙する。
    これが通らない限り納品しない — 「黙って劣化」をなくすのがこのツールの契約"""
    from playwright.sync_api import sync_playwright
    url = f"{origin}/preview/{slug}"
    shot = Path(workdir) / "verify_render.png"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            # 1520より広く取る: ぴったりだとスクロールバー分で fit() が全体を1%縮小し
            # 低周波diffが全ブロックで底上げされる
            pg = b.new_page(viewport={"width": 1600, "height": 1200})
            pg.goto(url, timeout=20000)
            try:
                pg.wait_for_function("document.fonts.status === 'loaded'", timeout=15000)
            except Exception:
                print("  !! webフォント読込を確認できないまま検証(スコアが狂う可能性)")
            pg.wait_for_timeout(1500)
            pg.screenshot(path=str(shot), full_page=True)
            b.close()
    except Exception as e:
        print(f"!! 検証未実施: {url} を開けない ({type(e).__name__})。devサーバー起動後に再実行するまで合格ではない")
        return None
    render = Image.open(shot).convert("RGB")
    vdir = Path(workdir) / "verify"
    os.makedirs(vdir, exist_ok=True)
    for old in vdir.glob("*.png"):  # 前回の結果が残ると判断を誤らせる
        old.unlink()
    results = []
    y_off = 0
    for (tname, (tw, th), groups), tile in zip(tiles_data, spec["tiles"]):
        orig = Image.open(ROOT / tile["image"]).convert("RGB")
        orig_arr = np.asarray(orig)
        for gi, g in enumerate(groups):
            if g[0].get("_keep"):
                continue
            x0 = max(0, min(x["x"] for x in g) - 25)
            y0 = max(0, min(x["y"] for x in g) - 25)
            x1 = min(tw, max(x["x"] + x["w"] for x in g) + 25)
            y1 = min(th, max(x["y"] + x["h"] for x in g) + 25)
            a = orig.crop((x0, y0, x1, y1))
            b = render.crop((x0, y_off + y0, x1, y_off + y1))
            score = _lowfreq_diff(a, b, max(x["h"] for x in g))
            label = line_text(g[0])[:14]
            status = "FAIL" if score >= VERIFY_FAIL else ("WARN" if score >= VERIFY_WARN else "ok")
            results.append((status, score, tname, label))
            if status != "ok":
                cmp_img = Image.new("RGB", (a.width * 2 + 12, a.height + 30), "white")
                cmp_img.paste(a, (0, 30)); cmp_img.paste(b, (a.width + 12, 30))
                cmp_img.save(vdir / f"{status}_{tname}_g{gi}.png")
                sug = _suggest_deco(orig_arr, g[0])
                extra = f" 候補: {sug}" if sug else ""
                print(f"  [{status}] {tname} {label} diff={score:.3f}{extra}")
        y_off += th
    n_fail = sum(1 for s, *_ in results if s == "FAIL")
    n_warn = sum(1 for s, *_ in results if s == "WARN")
    if n_fail or n_warn:
        print(f"検証: FAIL {n_fail} / WARN {n_warn} / ok {len(results)-n_fail-n_warn} — 比較画像: {vdir}")
        if n_fail:
            print("→ FAIL=確実な劣化。specに装飾(halo/shadow/stroke/grad)や overrides を足して再実行するまで不合格")
        if n_warn:
            print("→ WARN=機械では白黒つかない帯。比較画像を全部ズームで目視し、劣化が無いと確認できて初めて合格")
    else:
        print(f"検証: 全{len(results)}ブロック合格（低周波diff < {VERIFY_WARN}）")
    return results


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--spec", required=True)
    ap.add_argument("--workdir", default=None, help="中間ファイル置き場(既定: specと同じ場所)")
    ap.add_argument("--preview-origin", default="http://localhost:3000")
    ap.add_argument("--no-verify", action="store_true", help="忠実度ゲートを飛ばす(デバッグ用。納品判断には使わない)")
    ap.add_argument("cmd", choices=["run"], nargs="?", default="run")
    args = ap.parse_args()
    spec = json.load(io.open(args.spec, encoding="utf-8"))
    workdir = Path(args.workdir or Path(args.spec).parent)
    slug = spec["slug"]
    prefix = spec.get("editid_prefix", slug)
    bg_dir = ROOT / "frontend/public/scratch" / slug
    os.makedirs(bg_dir, exist_ok=True)

    # 1. 検出
    tiles_data = []
    for ti, tile in enumerate(spec["tiles"], 1):
        tname = f"tile{ti}"
        im = Image.open(ROOT / tile["image"]).convert("RGB")
        lines_all = []
        for region in tile["regions"]:
            ls = detect_lines(im, region)
            for i, l in enumerate(ls):
                segc = {c for _, c in l["segs"] if c}
                if len(segc) == 1 and all(c for _, c in l["segs"]):
                    l["color"] = segc.pop()  # 行の全セグメントが同一明示色
                # 部分色(一部セグメントだけ色指定)は emit のスパンが担う。行色は自動検出のまま
                ov = (region.get("overrides") or {}).get(str(i))
                if ov:
                    eb = ov.pop("ebox", None)
                    l.update(ov)
                    if eb:  # 消去範囲の明示指定(枠内テキスト等の特殊ケース用)
                        l["ex"], l["ey"] = eb[0], eb[1]
                        l["ew"], l["eh"] = eb[2] - eb[0], eb[3] - eb[1]
                        l["eflat"] = True  # 明示boxは面塗り(チップ等の無地下地を想定)
                l["_region"] = region
            lines_all.extend(ls)
        groups = group_lines(lines_all)
        tiles_data.append((tname, im.size, groups))
        print(f"{tname}: {len(lines_all)}行 / {len(groups)}グループ")

    # 2. 較正 + 置換/keep判定
    flat, meas = calibrate_and_judge(tiles_data, workdir)
    for g, m in zip(flat, meas):
        l = g[0]
        size0 = l["_size0"]
        size1 = max(8, round(size0 * l["h"] / max(m["h"], 1)))
        k = size1 / size0
        l["_size1"] = size1
        l["_top"] = round(l["y"] - m["top"] * k)
        l["_left"] = round(min(x["x"] for x in g) - m["left"] * k)
        # 字間: 較正レンダの実測幅を検出幅に一致させる（和文で係数推定が広がる系統誤差の根治）
        gaps = max(1, len(line_text(l)) - 1)
        stretch = float(l.get("stretch", 1.0))
        ls1 = max(-0.1, round(l["_ls0"] + (l["w"] / stretch - m["w"] * k) / gaps / size1, 3))
        if ls1 > 0.35:  # 検出幅の汚染(ハロー等)の兆候。広げず警告して spec の w 実測上書きを促す
            print(f"  !! 字間異常(ls={ls1}em): {line_text(l)[:14]} -> 検出幅w={l['w']}が怪しい。overridesでwを実測上書き推奨")
            ls1 = 0.04
        l["_ls1"] = ls1
        # 装飾度チェックは助言のみ（自動keepは過検知が多く廃止 2026-08-23）。
        # keepにするのは spec の force:"keep" だけ = 判断はspec作者(ダン)が行う
        force = l["_region"].get("force")
        if force == "keep":
            l["_keep"] = True
            continue
        po = None
        try:
            orig_im = None
            for tname, _, gs in tiles_data:
                if g in gs:
                    ti = int(tname[4:]) - 1
                    orig_im = Image.open(ROOT / spec["tiles"][ti]["image"]).convert("RGB")
                    break
            garr = np.asarray(orig_im.convert("L")).astype(int)
            rgb = np.asarray(orig_im).astype(int)
            sat = rgb.max(axis=2) - rgb.min(axis=2)
            om = contrast_ink(garr, sat, l["x"], l["y"], l["x"] + l["w"], l["y"] + l["h"])
            po = glyph_profile(om)
        except Exception:
            pass
        pc = glyph_profile(m["mask"])
        if po is not None and pc is not None:
            n = min(len(po), len(pc))
            ro = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(po)), po)
            rc = np.interp(np.linspace(0, 1, n), np.linspace(0, 1, len(pc)), pc)
            dist = float(np.abs(ro - rc).mean())
            if dist > PROFILE_KEEP_THRESHOLD:
                print(f"  !! 装飾注意(dist={dist:.2f}): {line_text(l)[:14]} -> 見た目が再現できていなければ force:\"keep\" を検討")

    # 3. 消去
    for (tname, size, groups), tile in zip(tiles_data, spec["tiles"]):
        im = Image.open(ROOT / tile["image"]).convert("RGB")
        arr = np.asarray(im).copy()
        origa = np.asarray(im)
        gen_regions = []
        for g in groups:
            if g[0].get("_keep"):
                continue
            region = g[0]["_region"]
            mode = region.get("erase", "fill")
            if mode == "generative":
                if region not in gen_regions:
                    gen_regions.append(region)
            elif mode == "fill":
                for l in g:
                    rowfill_erase(arr, origa, l)
        bg_path = bg_dir / f"bg_{tname}.png"
        Image.fromarray(arr).save(bg_path)
        for region in gen_regions:
            generative_erase(bg_path, region, bg_path, cache_dir=workdir, tname=tname)
            print(f"  {tname}: 生成消去 {region['box']}")

    # 4. ページ出力
    out_pages = ROOT / "frontend/src/app/artifacts" / slug
    emit_page(spec, tiles_data, out_pages, slug, prefix)
    n_keep = sum(1 for _, _, gs in tiles_data for g in gs if g[0].get("_keep"))
    n_rep = sum(1 for _, _, gs in tiles_data for g in gs if not g[0].get("_keep"))
    print(f"完了: 置換{n_rep}ブロック / 絵のまま{n_keep}ブロック → {out_pages}")

    # 5. 忠実度ゲート
    if args.no_verify:
        print("!! 検証スキップ(--no-verify)。納品判断には使えない")
    else:
        verify(spec, tiles_data, workdir, slug, args.preview_origin)
    print("次: FAIL/WARNの比較画像を目視 → specを補正して再実行。全ブロック合格まで納品しない")


if __name__ == "__main__":
    main()
