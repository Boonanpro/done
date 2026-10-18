"""Count lines and blocks that will wrap or stack up on the X article phone view.

The phone view shows about 21 full-width characters per line (390px wide, 17px text).
Half-width characters (digits, Latin) count as 0.5. Headings, image/video lines, URLs,
tables and copy boxes are skipped.

  python layout_check.py draft.md [--max-line 20] [--max-block 60] [--seen seen.txt]

--seen: the "既出" list, one item per line ("種類：文"). Prints every item whose text
shares a run of 10 or more characters with the draft (after removing spaces and
punctuation), so the same example, formula or catchphrase can be replaced.
Exit code 1 when anything is over or matched.
"""
import argparse, re, sys, unicodedata


def width(s):
    return sum(1 if unicodedata.east_asian_width(c) in 'WFA' else 0.5 for c in s)


def skip(line):
    s = line.strip()
    return (not s or s.startswith(('#', '![', '|', 'http', '```', '---', '▶', '▼'))
            or re.fullmatch(r'https?://\S+', s) is not None)


def norm(s):
    return re.sub(r'[\s　、。・「」『』（）()！？!?\*：:，,．.\-ー〜~]', '', s)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    ap = argparse.ArgumentParser()
    ap.add_argument('file')
    ap.add_argument('--max-line', type=float, default=20)
    ap.add_argument('--max-block', type=float, default=60)
    ap.add_argument('--seen')
    ap.add_argument('--run', type=int, default=10)
    a = ap.parse_args()
    text = open(a.file, encoding='utf-8').read()
    lines, in_code = [], False
    for i, line in enumerate(text.splitlines(), 1):
        if line.strip().startswith('```'):
            in_code = not in_code
            continue
        lines.append((i, line, in_code))
    long_lines = [(i, l.strip()) for i, l, c in lines if not c and not skip(l) and width(l.strip().replace('**', '')) > a.max_line]
    blocks, cur = [], []
    for i, l, c in lines:
        if c or not l.strip() or skip(l):
            if cur:
                blocks.append(cur)
            cur = []
        else:
            cur.append((i, l.strip()))
    if cur:
        blocks.append(cur)
    long_blocks = [b for b in blocks if width(''.join(x for _, x in b).replace('**', '')) > a.max_block]
    body = [l.strip() for _, l, c in lines if not c and not skip(l)]
    widths = [width(x.replace('**', '')) for x in body] or [0]
    bw = [width(''.join(x for _, x in b).replace('**', '')) for b in blocks] or [0]
    print(f'lines {len(body)} avg {sum(widths)/len(widths):.1f} max {max(widths):.1f} | blocks {len(blocks)} avg {sum(bw)/len(bw):.1f} max {max(bw):.1f}')
    print(f'lines over {a.max_line:g}: {len(long_lines)}')
    for i, l in long_lines:
        print(f'  L{i} ({width(l):g}) {l}')
    print(f'blocks over {a.max_block:g}: {len(long_blocks)}')
    for b in long_blocks:
        print(f'  L{b[0][0]}-L{b[-1][0]} ({width("".join(x for _, x in b)):g}) {b[0][1][:30]}…')
    hits = []
    if a.seen:
        draft = norm(text)
        for item in open(a.seen, encoding='utf-8').read().splitlines():
            t = norm(item.split('：', 1)[-1])
            runs = {t[k:k + a.run] for k in range(len(t) - a.run + 1)}
            if any(r in draft for r in runs):
                hits.append(item.strip())
        print(f'seen items found in draft: {len(hits)}')
        for h in hits:
            print(f'  {h}')
    sys.exit(1 if long_lines or long_blocks or hits else 0)


if __name__ == '__main__':
    main()
