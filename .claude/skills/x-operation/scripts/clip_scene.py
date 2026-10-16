"""Cut a few seconds out of a long video and burn in where they sit in the whole.

The bottom strip shows the whole video as a bar, the cut part filled in, a playhead
moving through it, and "3:12-3:40 / 15:39". Prints the YouTube URL that resumes at the
same moment when --youtube is given.

  python clip_scene.py --src video.mp4 --start 3:12 --end 3:40 --out clip.mp4 [--youtube URL]
"""
import argparse, json, os, subprocess, sys, tempfile
from PIL import Image, ImageDraw, ImageFont

FONT = 'C:/Windows/Fonts/YuGothB.ttc'


def seconds(v):
    parts = [float(p) for p in str(v).split(':')]
    s = 0.0
    for p in parts:
        s = s * 60 + p
    return s


def clock(s):
    s = int(round(s))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f'{h}:{m:02d}:{sec:02d}' if h else f'{m}:{sec:02d}'


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,width,height',
                          '-of', 'json', path], capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    v = next(s for s in d['streams'] if s['codec_type'] == 'video')
    return float(d['format']['duration']), v['width'], v['height'], any(s['codec_type'] == 'audio' for s in d['streams'])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True)
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--width', type=int, default=1280)
    ap.add_argument('--youtube')
    ap.add_argument('--total', help='length shown on the page (e.g. 15:39) when the download rounds differently')
    a = ap.parse_args()
    start, end = seconds(a.start), seconds(a.end)
    total, sw, sh, has_audio = probe(a.src)
    if a.total:
        total = seconds(a.total)
    if not (0 <= start < end <= total):
        sys.exit(f'start/end must be inside 0..{clock(total)}')
    if end - start > 140:
        sys.exit('keep the clip short (X plays clips; the point is to show only the part being explained)')
    dur = end - start
    w = min(a.width, sw) // 2 * 2
    vh = int(sh * w / sw) // 2 * 2
    strip = max(56, w // 16) // 2 * 2
    pad, bar_h = w // 40, max(10, strip // 5)
    font = ImageFont.truetype(FONT, int(strip * 0.42))
    label = f'{clock(start)}〜{clock(end)} / {clock(total)}'
    tw = int(font.getlength(label))
    bx0, bx1 = pad, w - pad * 2 - tw
    by0 = (strip - bar_h) // 2
    seg0 = bx0 + (bx1 - bx0) * start / total
    seg1 = max(seg0 + 4, bx0 + (bx1 - bx0) * end / total)

    tmp = tempfile.mkdtemp()
    bar = Image.new('RGBA', (w, strip), (15, 15, 15, 255))
    d = ImageDraw.Draw(bar)
    d.rounded_rectangle([bx0, by0, bx1, by0 + bar_h], radius=bar_h // 2, fill=(90, 90, 90, 255))
    d.rectangle([seg0, by0, seg1, by0 + bar_h], fill=(255, 0, 51, 255))
    d.text((w - pad - tw, strip // 2), label, font=font, fill=(255, 255, 255, 255), anchor='lm')
    bar_png = os.path.join(tmp, 'bar.png')
    bar.save(bar_png)
    head = Image.new('RGBA', (max(4, bar_h // 2), bar_h + 8), (255, 255, 255, 255))
    head_png = os.path.join(tmp, 'head.png')
    head.save(head_png)

    hx = f'{seg0:.1f}+({seg1 - seg0:.1f})*t/{dur:.3f}'
    fc = (f'[0:v]scale={w}:{vh},setsar=1,pad={w}:{vh + strip}:0:0:black[v];'
          f'[v][1:v]overlay=0:{vh}[b];'
          f'[b][2:v]overlay=x=\'{hx}\':y={vh + by0 - 4}:eval=frame,format=yuv420p[o]')
    cmd = ['ffmpeg', '-y', '-v', 'error', '-ss', f'{start:.3f}', '-t', f'{dur:.3f}', '-i', a.src,
           '-loop', '1', '-i', bar_png, '-loop', '1', '-i', head_png,
           '-filter_complex', fc, '-map', '[o]']
    if has_audio:
        cmd += ['-map', '0:a:0', '-c:a', 'aac', '-b:a', '128k']
    cmd += ['-t', f'{dur:.3f}', '-c:v', 'libx264', '-preset', 'medium', '-crf', '22', '-movflags', '+faststart', a.out]
    subprocess.run(cmd, check=True)
    sys.stdout.reconfigure(encoding='utf-8')
    print(json.dumps({'out': a.out, 'label': label, 'seconds': round(dur, 2),
                      'resume_url': (f"{a.youtube}{'&' if '?' in a.youtube else '?'}t={int(start)}" if a.youtube else None)},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()
