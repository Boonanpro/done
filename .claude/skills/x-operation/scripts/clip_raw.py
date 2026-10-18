"""Cut a part of a video and hand it over as it is: no frame, no background, no bar.

Optional: burn subtitles only (from an .srt you checked, or transcribed here), and a
one-line credit in the corner ("出典：〇〇公式 2026.03.22").

  # 1) cut only (the source already has its own captions, or the picture tells it)
  python clip_raw.py --src video.mp4 --start 3:12 --end 4:30 --out clip.mp4
  # 2) write subtitles to check/fix first, then burn them
  python clip_raw.py --src video.mp4 --start 3:12 --end 4:30 --srt-only clip.srt
  python clip_raw.py --src video.mp4 --start 3:12 --end 4:30 --subs clip.srt --credit "出典：PIVOT公式 2026.03.22" --out clip.mp4
  # --src may be a URL the rights holder allows to reuse; only the cut part is downloaded.

The first frame is the thumbnail on the timeline: start on the person or the screen, not
on a title card or a black frame (look at a 1 fps contact sheet around --start first).
"""
import argparse, json, os, shutil, subprocess, sys, tempfile

FONT_NAME = 'Yu Gothic UI Bold'
FONT_FILE = 'C:/Windows/Fonts/YuGothB.ttc'


def seconds(v):
    s = 0.0
    for p in str(v).split(':'):
        s = s * 60 + float(p)
    return s


def probe(path):
    out = subprocess.run(['ffprobe', '-v', 'error', '-show_entries', 'format=duration:stream=codec_type,width,height',
                          '-of', 'json', path], capture_output=True, text=True, check=True).stdout
    d = json.loads(out)
    v = next(s for s in d['streams'] if s['codec_type'] == 'video')
    return float(d['format']['duration']), v['width'], v['height'], any(s['codec_type'] == 'audio' for s in d['streams'])


def fetch(url, start, end, tmp):
    """Download only start..end (plus a small margin) of a URL with yt-dlp. Returns (path, offset)."""
    import yt_dlp
    from yt_dlp.utils import download_range_func
    margin = min(start, 2.0)
    opts = {'outtmpl': os.path.join(tmp, 'src.%(ext)s'), 'quiet': True, 'noprogress': True,
            'format': 'bv*[height<=1080][ext=mp4]+ba[ext=m4a]/b[ext=mp4]/b',
            'merge_output_format': 'mp4',
            'download_ranges': download_range_func(None, [(start - margin, end + 1.0)]),
            'force_keyframes_at_cuts': True}
    with yt_dlp.YoutubeDL(opts) as y:
        info = y.extract_info(url, download=True)
    path = next(os.path.join(tmp, f) for f in os.listdir(tmp) if f.startswith('src.'))
    return path, start - margin, info.get('title'), info.get('channel') or info.get('uploader'), info.get('upload_date')


def cut(src, start, dur, out, has_audio):
    cmd = ['ffmpeg', '-y', '-v', 'error', '-ss', f'{start:.3f}', '-t', f'{dur:.3f}', '-i', src, '-map', '0:v:0']
    if has_audio:
        cmd += ['-map', '0:a:0', '-c:a', 'aac', '-b:a', '160k']
    cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '18', '-pix_fmt', 'yuv420p', out]
    subprocess.run(cmd, check=True)


def clock_srt(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def cuda_dlls():
    # cuBLAS / cuDNN come from the nvidia-*-cu12 wheels; Windows only finds them once their bin folders are added
    import glob, site
    for sp in site.getsitepackages() + [site.getusersitepackages()]:
        for d in glob.glob(os.path.join(sp, 'nvidia', '*', 'bin')):
            os.add_dll_directory(d)
            os.environ['PATH'] = d + os.pathsep + os.environ['PATH']


def gpu_free_mb():
    try:
        import pynvml
        pynvml.nvmlInit()
        free = pynvml.nvmlDeviceGetMemoryInfo(pynvml.nvmlDeviceGetHandleByIndex(0)).free
        pynvml.nvmlShutdown()
        return free // 2**20
    except Exception:
        return None


def wait_for_gpu(need_mb, wait_s):
    """The 8 GB GPU is shared (Voice Input, lifelog keep Whisper loaded): wait for room instead of failing."""
    import time
    deadline = time.time() + wait_s
    while True:
        free = gpu_free_mb()
        if free is None or free >= need_mb:
            return free
        if time.time() >= deadline:
            raise RuntimeError(f'GPU has {free} MB free, {need_mb} MB needed (other work is using it)')
        print(f'GPU busy: {free} MB free, waiting', file=sys.stderr)
        time.sleep(5)


def transcribe(clip, srt, model, device='auto', gpu_wait=180, need_mb=2000):
    cuda_dlls()
    from faster_whisper import WhisperModel
    segs = None
    devices = {'auto': ('cuda', 'cpu'), 'cuda': ('cuda',), 'cpu': ('cpu',)}[device]
    for dev in devices:
        try:  # CUDA errors (missing DLL, out of memory) can show up only while decoding, so run it inside the try
            if dev == 'cuda':
                print(f'GPU free before load: {wait_for_gpu(need_mb, gpu_wait)} MB', file=sys.stderr)
            m = WhisperModel(model, device=dev, compute_type='int8_float16' if dev == 'cuda' else 'int8')
            segs = list(m.transcribe(clip, language='ja', vad_filter=True)[0])
            print(f'transcribed on {dev}', file=sys.stderr)
            del m
            break
        except Exception as e:
            if dev == devices[-1]:
                raise
            print(f'cuda failed ({e}); using cpu', file=sys.stderr)
    lines = []
    for s in segs:
        text = s.text.strip()
        if text:
            lines.append(f'{len(lines) + 1}\n{clock_srt(s.start)} --> {clock_srt(s.end)}\n{text}\n')
    with open(srt, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return len(lines)


def ass_escape(s):
    return s.replace('\\', '\\\\').replace('{', '\\{').replace('}', '\\}')


def burn(clip, out, w, h, srt, credit, has_audio):
    tmp = tempfile.mkdtemp()
    filters = []
    short = min(w, h)
    if srt:
        shutil.copy(srt, os.path.join(tmp, 'subs.srt'))
        size = max(16, int(short / 10 * 288 / h))  # libass scales from PlayResY=288
        style = (f"FontName={FONT_NAME},FontSize={size},PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                 f"BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV={int(288 * 0.06)}")
        filters.append(f"subtitles=subs.srt:force_style='{style}'")
    if credit:
        with open(os.path.join(tmp, 'credit.txt'), 'w', encoding='utf-8') as f:
            f.write(credit)
        fs = max(14, short // 34)
        filters.append(f"drawtext=fontfile='{FONT_FILE.replace(':', chr(92) + ':')}':textfile=credit.txt:"
                       f"fontsize={fs}:fontcolor=white@0.92:borderw=2:bordercolor=black@0.7:x={fs}:y={fs}")
    clip = os.path.abspath(clip)
    out = os.path.abspath(out)
    cmd = ['ffmpeg', '-y', '-v', 'error', '-i', clip, '-vf', ','.join(filters) or 'null', '-map', '0:v:0']
    if has_audio:
        cmd += ['-map', '0:a:0', '-c:a', 'copy']
    cmd += ['-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', out]
    subprocess.run(cmd, check=True, cwd=tmp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', required=True, help='video file, or a URL the rights holder allows to reuse')
    ap.add_argument('--start', required=True)
    ap.add_argument('--end', required=True)
    ap.add_argument('--out')
    ap.add_argument('--subs', help='an .srt to burn (write one with --srt-only and check it first)')
    ap.add_argument('--srt-only', help='transcribe the cut part to this .srt and stop')
    ap.add_argument('--model', default='large-v3-turbo')
    ap.add_argument('--device', default='auto', choices=['auto', 'cuda', 'cpu'], help='auto: GPU, CPU only if the GPU stays busy or fails')
    ap.add_argument('--gpu-wait', type=int, default=180, help='seconds to wait for free GPU memory before falling back')
    ap.add_argument('--credit', help='one line in the top-left corner, e.g. 出典：〇〇公式 2026.03.22')
    ap.add_argument('--width', type=int, default=1280, help='longest side is reduced to this')
    ap.add_argument('--long', action='store_true', help='allow more than 140 seconds')
    a = ap.parse_args()
    if not a.out and not a.srt_only:
        sys.exit('--out or --srt-only is required')
    start, end = seconds(a.start), seconds(a.end)
    if end <= start:
        sys.exit('end must be after start')
    if end - start > 140 and not a.long:
        sys.exit('longer than 140 seconds (X plays up to 2:20 on most accounts). Use --long only for a 15-60 minute style post.')
    tmp = tempfile.mkdtemp()
    meta = {}
    src, offset = a.src, 0.0
    if a.src.startswith(('http://', 'https://')):
        src, offset, title, channel, date = fetch(a.src, start, end, tmp)
        meta = {'title': title, 'channel': channel, 'upload_date': date}
    total, sw, sh, has_audio = probe(src)
    s0 = start - offset
    if not (0 <= s0 < total):
        sys.exit(f'start is outside the video (0..{total:.1f}s)')
    dur = min(end - start, total - s0)
    r = min(1.0, a.width / max(sw, sh))
    w, h = int(sw * r) // 2 * 2, int(sh * r) // 2 * 2
    raw = os.path.join(tmp, 'cut.mp4')
    cut(src, s0, dur, raw, has_audio)
    if (w, h) != (sw, sh):
        small = os.path.join(tmp, 'cut_s.mp4')
        cmd = ['ffmpeg', '-y', '-v', 'error', '-i', raw, '-vf', f'scale={w}:{h}', '-c:v', 'libx264', '-crf', '18',
               '-pix_fmt', 'yuv420p'] + (['-c:a', 'copy'] if has_audio else []) + [small]
        subprocess.run(cmd, check=True)
        raw = small
    sys.stdout.reconfigure(encoding='utf-8')
    if a.srt_only:
        n = transcribe(raw, a.srt_only, a.model, a.device, a.gpu_wait)
        print(json.dumps({'srt': a.srt_only, 'lines': n, 'seconds': round(dur, 2), **meta}, ensure_ascii=False))
        return
    burn(raw, a.out, w, h, a.subs, a.credit, has_audio)
    print(json.dumps({'out': a.out, 'seconds': round(dur, 2), 'size': f'{w}x{h}', 'subs': bool(a.subs),
                      'credit': a.credit, **meta}, ensure_ascii=False))


if __name__ == '__main__':
    main()
