"""X記事がタイムラインに出る札（表紙・タイトル・冒頭）の見本画像を作る。

スマホ幅（札の幅 約340px）を2倍で描く。表紙は5:2の真ん中で切り、タイトルは2行、
冒頭は4行（空行も1行、長い行は折り返す）で「…」にする。2026-10-16 にX上の実際の札と比べて合わせた。

  python card_preview.py --cover cover.png --title "タイトル" --lead "1行目\n2行目\n3行目" --out card.png
  python card_preview.py --title "表紙なしの札" --lead "..." --out card.png
  python card_preview.py --stack a.png b.png c.png --out cards.png   # 札を横に並べる
"""
import argparse
from PIL import Image, ImageDraw, ImageFont

S = 2  # 倍率
W = 340 * S
PAD = 12 * S
FONT_B = "C:/Windows/Fonts/meiryob.ttc"
FONT_R = "C:/Windows/Fonts/meiryo.ttc"
NO_HEAD = "。、」』）！？"


def wrap(draw, text, font, width):
    lines = []
    for para in text.split("\n"):
        if para.strip() == "":
            lines.append("")
            continue
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=font) > width:
                if ch in NO_HEAD and cur:  # 句読点・閉じかっこは行頭に置かない
                    ch = cur[-1] + ch; cur = cur[:-1]
                elif cur and cur[-1].isdigit():  # 数字と、その後ろの単位の間で折り返さない
                    k = len(cur)
                    while k > 0 and (cur[k - 1].isdigit() or cur[k - 1] in ",."):
                        k -= 1
                    if 0 < k < len(cur):
                        ch = cur[k:] + ch; cur = cur[:k]
                lines.append(cur)
                cur = ch
            else:
                cur += ch
        lines.append(cur)
    return lines


def clip(draw, lines, font, width, n):
    if len(lines) <= n:
        return lines
    out = lines[:n]
    last = out[-1]
    while last and draw.textlength(last + "…", font=font) > width:
        last = last[:-1]
    out[-1] = last + "…"
    return out


def card(cover, title, lead, name, handle):
    inner = W - 2 * PAD
    fb = ImageFont.truetype(FONT_B, 15 * S)
    fr = ImageFont.truetype(FONT_R, 15 * S)
    fs = ImageFont.truetype(FONT_R, 13 * S)
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    tw = inner - 2 * PAD - (0 if cover else 80 * S)  # 表紙なしは右上に「X Article」が並ぶ
    tl = clip(tmp, wrap(tmp, title, fb, tw), fb, tw, 2)
    ll = clip(tmp, wrap(tmp, lead, fr, inner - 2 * PAD), fr, inner - 2 * PAD, 4)
    lh = int(20 * S)
    ch = int(inner * 2 / 5) if cover else 0
    h = PAD + 22 * S + PAD // 2 + ch + PAD + lh * len(tl) + 6 * S + lh * len(ll) + PAD + PAD
    img = Image.new("RGB", (W, h), "white")
    d = ImageDraw.Draw(img)
    d.text((PAD, PAD), name, font=fb, fill="#0f1419")
    hx = PAD + d.textlength(name, font=fb) + 6 * S
    if hx + d.textlength(handle, font=fs) < W - PAD:
        d.text((hx, PAD + 2 * S), handle, font=fs, fill="#536471")
    y0 = PAD + 22 * S + PAD // 2
    box = [PAD, y0, W - PAD, h - PAD]
    d.rounded_rectangle(box, radius=14 * S, outline="#cfd9de", width=S)
    y = y0
    if cover:
        im = Image.open(cover).convert("RGB")
        r = 5 / 2
        if im.width / im.height > r:
            nw = int(im.height * r); x = (im.width - nw) // 2; im = im.crop((x, 0, x + nw, im.height))
        else:
            nh = int(im.width / r); t = (im.height - nh) // 2; im = im.crop((0, t, im.width, t + nh))
        im = im.resize((inner, ch), Image.LANCZOS)
        mask = Image.new("L", (inner, ch), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, inner, ch + 20 * S], radius=14 * S, fill=255)
        img.paste(im, (PAD, y), mask)
        bx, by = PAD + 8 * S, y + ch - 26 * S
        d.rounded_rectangle([bx, by, bx + 54 * S, by + 18 * S], radius=3 * S, fill=(80, 80, 80))
        d.text((bx + 6 * S, by + 1 * S), "X Article", font=ImageFont.truetype(FONT_B, 10 * S), fill="white")
        y += ch
    else:
        d.text((W - PAD - 70 * S, y + 10 * S), "X Article", font=ImageFont.truetype(FONT_B, 11 * S), fill="#0f1419")
    y += PAD
    for t in tl:
        d.text((PAD * 2, y), t, font=fb, fill="#0f1419"); y += lh
    y += 6 * S
    for t in ll:
        d.text((PAD * 2, y), t, font=fr, fill="#0f1419"); y += lh
    return img


def stack(paths, out, gap=24):
    ims = [Image.open(p) for p in paths]
    h = max(i.height for i in ims)
    canvas = Image.new("RGB", (sum(i.width for i in ims) + gap * (len(ims) + 1), h + 2 * gap), "#eef1f4")
    x = gap
    for i in ims:
        canvas.paste(i, (x, gap)); x += i.width + gap
    canvas.save(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cover")
    ap.add_argument("--title")
    ap.add_argument("--lead", default="")
    ap.add_argument("--name", default="ふくろうP｜YouTube運用丸投げ")
    ap.add_argument("--handle", default="@FukurouKantoku")
    ap.add_argument("--stack", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    if a.stack:
        stack(a.stack, a.out)
    else:
        card(a.cover, a.title, a.lead.replace(chr(92) + "n", chr(10)), a.name, a.handle).save(a.out)
    print(a.out)
