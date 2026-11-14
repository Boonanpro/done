"""Full-text captions aligned to the spoken audio of a timeline.

Input: the exact script per time range ({t0, t1, text}) — the text the viewer must
read, not what Whisper heard. Whisper only supplies WORD TIMES for the timeline's
speech audio; the script is aligned to those words character by character
(difflib), split into captions at meaning boundaries (文節; a caption never ends inside
'アプリや|ホームページ' or 'この|AI', see _bunsetsu) of at most max_chars per line, and placed
with two rules that came out of the kittoku video (2026-09-04):
  * monotonic search — a repeated phrase ("こんなところ") must not snap back to its
    first occurrence;
  * never delay — when a caption would overlap the previous one, the PREVIOUS is cut
    short. Captions that appear late read as "wrong"; captions that vanish a
    little early do not.
Whisper runs in a subprocess (scripts/dan_audio_check.py) — never import
faster-whisper/numpy in the MCP process (DLL init hang, 2026-07-16).
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.services import timeline_commands as tc

ROOT = Path(__file__).resolve().parents[2]
_NORM_RE = re.compile(r"[\s、。,.!?！？「」・…]")
MAX_CHARS = 16  # one line; 2026-11-13 owner: captions were too long and cut mid-phrase


def _f(v: Any, d: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _norm(t: str) -> str:
    return _NORM_RE.sub("", t)


def _ffmpeg() -> str:
    for c in (os.environ.get("DAN_FFMPEG"), r"C:\Users\Owner\ffmpeg\bin\ffmpeg.exe", r"C:\ffmpeg\bin\ffmpeg.exe"):
        if c and Path(c).exists():
            return c
    import shutil

    return shutil.which("ffmpeg") or "ffmpeg"


def speech_clips(sequence: dict[str, Any]) -> list[dict[str, Any]]:
    """Audio-lane clips that carry speech (everything except music/sfx roles)."""
    out: list[dict[str, Any]] = []
    for track in sequence.get("tracks") or []:
        if str(track.get("type") or "") != "audio":
            continue
        for c in track.get("clips") or []:
            if not isinstance(c, dict) or not c.get("asset_id"):
                continue
            if str(c.get("role") or "").lower() in {"music", "bgm", "sfx"}:
                continue
            if _f(c.get("volume"), 1.0) <= 0.0:
                continue
            out.append(c)
    return sorted(out, key=lambda c: _f(c.get("timeline_start")))


def render_speech_wav(sequence: dict[str, Any], assets: dict[str, dict[str, Any]], work_dir: Path,
                      t0: float | None = None, t1: float | None = None) -> Path | None:
    """Mix the speech clips into ONE mono 16k wav on the timeline clock (adelay+amix),
    so Whisper's timestamps are timeline seconds directly. Speed is honored."""
    clips = speech_clips(sequence)
    if t0 is not None or t1 is not None:
        lo, hi = (t0 if t0 is not None else -1e9), (t1 if t1 is not None else 1e9)
        clips = [c for c in clips if _f(c.get("timeline_end")) > lo and _f(c.get("timeline_start")) < hi]
    if not clips:
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    inputs: list[str] = []
    filters: list[str] = []
    n = 0
    end = 0.0
    for c in clips:
        a = assets.get(str(c.get("asset_id"))) or {}
        src = a.get("local_path") or a.get("proxy_path") or ""
        if not src or not Path(src).exists():
            continue
        ts, te = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
        ss = _f(c.get("source_start"))
        spd = _f(c.get("speed"), 1.0) or 1.0
        dur = max(0.05, te - ts)
        inputs += ["-ss", f"{ss:.3f}", "-t", f"{dur * spd:.3f}", "-i", src]
        chain = f"[{n}:a]aresample=16000,aformat=channel_layouts=mono"
        if abs(spd - 1.0) > 1e-3:
            chain += f",atempo={min(2.0, max(0.5, spd)):.4f}"
        chain += f",adelay={int(ts * 1000)}|{int(ts * 1000)},volume={max(0.05, _f(c.get('volume'), 1.0)):.3f}[a{n}]"
        filters.append(chain)
        end = max(end, te)
        n += 1
    if n == 0:
        return None
    mix = "".join(f"[a{i}]" for i in range(n)) + f"amix=inputs={n}:normalize=0:dropout_transition=0[out]"
    out = work_dir / f"speech_{uuid.uuid4().hex[:8]}.wav"
    cmd = [_ffmpeg(), "-nostdin", "-y", "-v", "error", *inputs, "-filter_complex", ";".join(filters + [mix]),
           "-map", "[out]", "-t", f"{end + 0.5:.3f}", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out)]
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise RuntimeError(f"speech mix failed: {(r.stderr or '')[-400:]}")
    return out


def transcribe_words(wav: Path, model: str | None = None, initial_prompt: str | None = None) -> list[tuple[float, float, str]]:
    """Word timings via cloud API/cache; an explicit local model remains opt-in."""
    if model in (None, 'whisper-1'):
        return transcribe_cloud_words(wav, initial_prompt)
    script = ROOT / "scripts" / "dan_audio_check.py"
    model = model or os.environ.get("DAN_CAPTION_WHISPER_MODEL") or os.environ.get("DAN_WHISPER_MODEL") or "small"
    env = dict(os.environ)
    if initial_prompt:
        env["DAN_WHISPER_INITIAL_PROMPT"] = initial_prompt
    r = subprocess.run([sys.executable, str(script), str(wav), "--words", "--json-only", "--model", model],
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, stdin=subprocess.DEVNULL,
                       timeout=1800, env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out_json = wav.with_name(wav.stem + "_audiocheck.json")
    if not out_json.exists():
        raise RuntimeError(f"whisper failed rc={r.returncode}: {(r.stderr or '')[-400:]}")
    data = json.loads(out_json.read_text(encoding="utf-8"))
    words: list[tuple[float, float, str]] = []
    for seg in data.get("segments") or []:
        for w in seg.get("words") or []:
            text = str(w.get("word") or w.get("text") or "")
            if text.strip():
                words.append((_f(w.get("start")), max(_f(w.get("end")), _f(w.get("start")) + 0.05), text))
    return words


def transcribe_cloud_words(wav: Path, prompt: str | None = None):
    """Word timings without loading a GPU model; bounded uploads and durable cache."""
    import hashlib, io, wave
    from openai import OpenAI
    from app.config import settings
    digest = hashlib.sha256(wav.read_bytes() + (prompt or '').encode()).hexdigest()
    cache = wav.parent / (digest + '.whisper-1.words.json')
    if cache.exists():
        return [tuple(w) for w in json.loads(cache.read_text(encoding='utf-8'))]
    words = []
    with OpenAI(api_key=settings.OPENAI_API_KEY, timeout=120, max_retries=1) as client, wave.open(str(wav), 'rb') as src:
        rate = src.getframerate()
        offset = 0.0
        while True:
            frames = src.readframes(rate * 300)
            if not frames: break
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as dst:
                dst.setparams(src.getparams()); dst.writeframes(frames)
            result = client.audio.transcriptions.create(model='whisper-1',
                file=('speech.wav', buf.getvalue(), 'audio/wav'), language='ja',
                response_format='verbose_json', timestamp_granularities=['word'],
                **({'prompt': prompt} if prompt else {}))
            words.extend((offset + w.start, offset + w.end, w.word) for w in (result.words or []))
            offset += len(frames) / (rate * src.getnchannels() * src.getsampwidth())
    tmp = cache.with_suffix('.tmp'); tmp.write_text(json.dumps(words, ensure_ascii=False), encoding='utf-8'); tmp.replace(cache)
    return words


@lru_cache(maxsize=1)
def _phrase_parser():
    import budoux
    return budoux.load_default_japanese_parser()


@lru_cache(maxsize=1)
def _tokenizer():
    try:
        from janome.tokenizer import Tokenizer
    except Exception:  # janome missing: fall back to budoux phrases
        return None
    return Tokenizer()


# Emphasis markup inside a script: <key>決め言葉</key>, <neg>否定の言葉</neg>; "|" forces a break.
_MARK_RE = re.compile(r"<(key|neg)>(.*?)</\1>", re.S)
_SENT_END = ("。", "！", "？", "!", "?")
_ATTACH_POS = {"助詞", "助動詞"}
_ATTACH_SUB = {("名詞", "非自立"), ("名詞", "接尾"), ("動詞", "非自立"), ("動詞", "接尾"),
               ("形容詞", "非自立"), ("形容詞", "接尾"), ("記号", "句点"), ("記号", "読点"), ("記号", "括弧閉")}


def _width(t: str) -> float:
    """Display width: half-width letters/digits count about half a full-width character."""
    return sum(0.6 if ord(ch) < 0x2E80 and not ch.isspace() else (0 if ch.isspace() else 1) for ch in t)


def parse_markup(text: str) -> list[tuple[str, str]]:
    """'<key>…</key>' / '<neg>…</neg>' / '|' → [(piece, kind)], kind normal|key|neg.
    Every piece boundary is a forced caption break."""
    out: list[tuple[str, str]] = []
    pos = 0
    for m in _MARK_RE.finditer(text):
        for part in text[pos:m.start()].split("|"):
            out.append((part, "normal"))
        for part in m.group(2).split("|"):
            out.append((part, m.group(1)))
        pos = m.end()
    for part in text[pos:].split("|"):
        out.append((part, "normal"))
    return [(p, k) for p, k in out if p]


def plain_text(text: str) -> str:
    return "".join(p for p, _ in parse_markup(text))


def _bunsetsu(text: str) -> list[list[Any]]:
    """Split into phrases (文節) → [[surface, break_cost_after, hard_after]].
    The cost says how badly a caption may end right after that phrase: sentence ends and
    、 are free, a clause ending in て/が/から is cheap, splitting 'アプリや|ホームページ',
    'この|AI', '自由な|人生' or '私の|太陽光' is expensive."""
    tok = _tokenizer()
    if tok is None:
        parts = _phrase_parser().parse(text)
        return [[p, 0.0 if p.endswith(_SENT_END) else 1.0 if p.endswith("、") else 4.0, p.endswith(_SENT_END)]
                for p in parts]
    toks = list(tok.tokenize(text))
    groups: list[list[Any]] = []  # [surface, tokens]
    for t in toks:
        pos = t.part_of_speech.split(",")
        key = (pos[0], pos[1])
        prev = groups[-1][1][-1] if groups else None
        ppos = prev.part_of_speech.split(",") if prev else None
        attach = bool(groups) and (
            pos[0] in _ATTACH_POS or key in _ATTACH_SUB
            or (pos[0] == "名詞" and ppos and ppos[0] in {"名詞", "接頭詞"} and ppos[1] not in {"非自立"}
                and not (prev.surface.endswith(_SENT_END) or prev.surface == "、"))
            or (ppos and (ppos[0] == "接頭詞" or ppos[1] == "括弧開"))
            or (pos[0] == "名詞" and ppos and ppos[0] == "名詞" and ppos[1] == "非自立" and pos[1] == "接尾")
            or (t.surface in {"なんか", "なんて"} and ppos and ppos[0] == "名詞")  # 仕事なんか
            or (pos[0] == "動詞" and t.base_form in {"する", "できる"} and ppos and ppos[1] == "サ変接続")  # 受注できる
            or (ppos and prev.surface == "つ" and pos[0] == "名詞" and len(groups[-1][1]) >= 2
                and groups[-1][1][-2].part_of_speech.startswith("名詞,数"))  # 3つ目
        )
        # A content word after a closed sentence always opens a new phrase.
        if groups and groups[-1][0].endswith(_SENT_END) and pos[0] not in {"記号"}:
            attach = False
        if attach:
            groups[-1][0] += t.surface
            groups[-1][1].append(t)
        else:
            groups.append([t.surface, [t]])
    def predicate(k: int) -> float:
        """How much phrase k is the predicate of the phrase before it: 1 for a verb/adjective/
        ない/サ変名詞+する, 0.5 when it only modifies the next noun (経験も|ない自分), else 0."""
        if k >= len(groups):
            return 0.0
        lastk = groups[k][1][-1]
        nk0 = groups[k + 1][1][0] if k + 1 < len(groups) else None
        if (nk0 is not None and getattr(lastk, "infl_form", "") in {"基本形", "体言接続"}
                and nk0.part_of_speech.startswith("名詞") and not nk0.part_of_speech.startswith("名詞,非自立")):
            rel = 0.8  # やりたい|仕事: the verb modifies the next noun, not only this argument
        else:
            rel = 1.0
        t0 = groups[k][1][0]
        p0 = t0.part_of_speech.split(",")
        if p0[0] in {"動詞", "形容詞"} or (p0[0] == "助動詞" and t0.base_form == "ない"):
            return rel
        if p0[0] == "名詞" and p0[1] == "サ変接続":
            nk = groups[k + 1][1][0] if k + 1 < len(groups) else None
            if any(x.base_form in {"する", "できる"} for x in groups[k][1][1:]):
                return rel
            return rel if (nk and nk.base_form in {"する", "できる"}) else 0.0
        return 0.0

    out: list[list[Any]] = []
    for i, (surf, ts) in enumerate(groups):
        last = ts[-1]
        lp = last.part_of_speech.split(",")
        form = getattr(last, "infl_form", "*")
        nxt = groups[i + 1][1][0] if i + 1 < len(groups) else None
        np = nxt.part_of_speech.split(",") if nxt else ["*", "*"]
        hard = surf.endswith(_SENT_END)
        nbase = getattr(nxt, "base_form", "") if nxt else ""
        if not hard and nbase in {"なる", "する", "できる"} and (
                (lp[0] == "形容詞" and form.startswith("連用")) or last.surface in {"ように", "ようには", "と", "に", "く"}
                or lp[1] in {"副詞化", "形容動詞語幹", "サ変接続"}):
            out.append([surf, 12.0, False])  # 詳しく|なる, ように|なる, と|したら
            continue
        if hard:
            c = 0.0
        elif surf.endswith(("、", ",")):
            c = 1.0
        elif lp[0] == "助詞" or (lp[0] == "フィラー" and last.surface in {"なんか", "なんて"}):
            if lp[0] == "フィラー":
                lp = ["助詞", "副助詞"]  # 仕事なんか|ない
            c = {"終助詞": 0.5, "接続助詞": 2.0, "係助詞": 3.5, "格助詞": 4.0, "副助詞": 4.0,
                 "並立助詞": 9.0, "連体化": 9.0, "副詞化": 5.0, "副助詞／並立助詞／終助詞": 4.0}.get(lp[1], 4.0)
            if last.surface in {"の"} and lp[1] == "格助詞":
                c = 10.0  # 私の|太陽光, この中の|1つ目
            if last.surface in {"と", "とか"} and np[0] == "名詞" and lp[1] == "並立助詞":
                c = 9.0
            if last.surface == "より":
                c = 10.0  # 勉強より|先に
            if last.surface in {"たり", "だり"}:
                c = 2.5  # 持ったり|アートを買ったり: clauses, not nouns
            if lp[1] in {"格助詞", "係助詞", "副助詞"} and last.surface not in {"の", "は"}:
                pr = predicate(i + 1)
                c += 3.0 * pr
                if pr and nxt.base_form in {"ある", "ない", "いる"}:
                    c += 3.0  # 必要が|ある, 経験も|ない: the pair is one expression
            if (last.surface == "に" and len(ts) >= 2 and ts[-2].part_of_speech.split(",")[1] in {"数", "接尾"}
                    and np[0] == "名詞" and np[1] == "数"):
                c = max(c, 9.0)  # 1ヶ月に|5本  # 大波に|乗って, 必要が|ある, 経験も|ない: keep an argument with its predicate
        elif lp[0] in {"動詞", "形容詞", "助動詞"}:
            if lp[0] == "形容詞" and form.startswith("連用テ") and last.surface.endswith("く"):
                c = 7.0  # 大きく|資産を増やして: an adverb stays with its verb
            elif form.startswith("連用") or form in {"連用形", "連用タ接続"}:
                c = 2.0  # 稼ぎ / 改良し / であり: a clause ends here
            elif form == "体言接続" or (form == "基本形" and np[0] == "名詞" and np[1] != "非自立"):
                c = 9.0  # 自由な|人生, 生み出した|収入
            elif form == "基本形":
                c = 1.0  # sentence end without punctuation (speech transcripts)
            elif form == "仮定形":
                c = 2.0
            else:
                c = 5.0
        elif lp[0] == "連体詞" or lp[0] == "接頭詞":
            c = 12.0
        elif lp[0] == "接続詞":
            c = 5.0
        elif lp[0] == "副詞":
            c = 9.0 if lp[1] == "助詞類接続" else 7.0  # たった|20分, ほとんど|なくても
        elif lp[0] == "名詞":
            c = 6.0
        else:
            c = 5.0
        out.append([surf, c, hard])
    return out


def _segment(phr: list[list[Any]], maxw: float, times=None, base: int = 0) -> list[tuple[int, int]]:
    """Best split of one forced piece into caption chunks (dynamic programming over phrase
    boundaries). Returns [(i, j)] phrase index ranges. `times(a, b)` → seconds that the
    normalized characters [a, b) take to say, used to avoid captions that flash by."""
    n = len(phr)
    if n == 0:
        return []
    w = [_width(p[0].rstrip("、。,")) + (0.5 if p[0].endswith(("、", ",")) else 0.0) for p in phr]
    nlen = [len(_norm(p[0])) for p in phr]
    offs = [0]
    for k in nlen:
        offs.append(offs[-1] + k)
    lo, hi = max(4.0, maxw * 0.45), maxw * 0.8
    INF = float("inf")
    best = [INF] * (n + 1)
    back = [0] * (n + 1)
    best[0] = 0.0
    for j in range(1, n + 1):
        width = 0.0
        for i in range(j - 1, -1, -1):
            width += w[i]
            if width > maxw and i < j - 1:
                break
            if i < j - 1 and any(phr[k][2] for k in range(i, j - 1)):
                break  # never run across a sentence end
            cost = 1.0
            for k in range(i, j - 1):  # running across a clause boundary reads as two thoughts
                if phr[k][1] < 2.5:
                    cost += (2.5 - phr[k][1]) * 0.8
            if width < lo:
                cost += (lo - width) * 0.8
            if width < 4.0 and (i > 0 or j < n):
                cost += (4.0 - width) * 2.0  # 'では、' alone flashes by and says nothing
            elif width > hi:
                cost += (width - hi) * 0.9
            if width > maxw:
                cost += 30.0  # a single phrase longer than a caption
            if j < n:
                cost += phr[j - 1][1]
            if times is not None:
                d = times(base + offs[i], base + offs[j])
                if d is not None and d < 0.75:
                    cost += (0.75 - d) * 6.0
            if best[i] + cost < best[j]:
                best[j] = best[i] + cost
                back[j] = i
    out = []
    j = n
    while j > 0:
        out.append((back[j], j))
        j = back[j]
    return out[::-1]


def _two_lines(phrases: list[list[Any]], line_w: float) -> str:
    """Join phrases into at most two lines, breaking at the cheapest balanced boundary."""
    text = "".join(p[0] for p in phrases)
    if _width(text) <= line_w or len(phrases) < 2:
        return text
    best, cut = float("inf"), None
    for k in range(1, len(phrases)):
        a = "".join(p[0] for p in phrases[:k])
        b = "".join(p[0] for p in phrases[k:])
        if _width(a) > line_w or _width(b) > line_w:
            continue
        score = phrases[k - 1][1] * 2 + abs(_width(a) - _width(b)) * 0.3
        if score < best:
            best, cut = score, k
    if cut is None:
        return text
    return "".join(p[0] for p in phrases[:cut]) + "\n" + "".join(p[0] for p in phrases[cut:])


def chunk_script(text: str, maxlen: float = MAX_CHARS, max_lines: int = 1, times=None) -> list[dict[str, Any]]:
    """Script (with optional <key>/<neg>/| markup) → caption chunks
    [{text, kind, a, b}] where a/b index the normalized characters of plain_text(text)."""
    out: list[dict[str, Any]] = []
    base = 0
    line_w = float(maxlen)
    maxw = line_w * max(1, int(max_lines))
    for piece, kind in parse_markup(text):
        phr = _bunsetsu(piece)
        offs = [0]
        for p in phr:
            offs.append(offs[-1] + len(_norm(p[0])))
        for i, j in _segment(phr, maxw, times, base):
            sub = phr[i:j]
            t = _two_lines(sub, line_w) if max_lines > 1 else "".join(p[0] for p in sub)
            out.append({"text": t, "kind": kind, "a": base + offs[i], "b": base + offs[j]})
        base += offs[-1]
    # drop punctuation-only leftovers ("。") and the 、。 a caption ends with: on screen the
    # line end already is the pause (the text check ignores punctuation)
    merged: list[dict[str, Any]] = []
    for c in out:
        if not _norm(c["text"]):
            continue
        c["text"] = c["text"].strip("、。, \n")
        merged.append(c)
    return merged


def chunk_text(text: str, maxlen: int = MAX_CHARS) -> list[str]:
    """Plain-text chunks at meaning boundaries (kept for callers that only need strings)."""
    return [c["text"] for c in chunk_script(text, maxlen)]


def _char_times(words: list[tuple[float, float, str]], ref: str) -> list[tuple[float, float]] | None:
    """Time (start, end) for every normalized character of `ref`, from word timings.
    Unmatched characters are interpolated between their matched neighbours."""
    spoken = ""
    times: list[tuple[float, float]] = []
    for st, en, wd in words:
        wn = _norm(wd)
        for j in range(len(wn)):
            spoken += wn[j]
            times.append((st + (en - st) * j / max(1, len(wn)), st + (en - st) * (j + 1) / max(1, len(wn))))
    if not ref or not spoken:
        return None
    sm = difflib.SequenceMatcher(None, ref, spoken, autojunk=False)
    got: list[tuple[float, float] | None] = [None] * len(ref)
    for blk in sm.get_matching_blocks():
        for k in range(blk.size):
            got[blk.a + k] = times[blk.b + k]
    known = [i for i, v in enumerate(got) if v is not None]
    if not known:
        return None
    for i in range(len(ref)):
        if got[i] is not None:
            continue
        left = max((k for k in known if k < i), default=None)
        right = min((k for k in known if k > i), default=None)
        if left is None:
            got[i] = (got[right][0], got[right][0])
        elif right is None:
            got[i] = (got[left][1], got[left][1])
        else:
            f = (i - left) / (right - left)
            t = got[left][1] + (got[right][0] - got[left][1]) * f
            got[i] = (t, t)
    return got  # type: ignore[return-value]


HOLD_GAP = 0.6   # pauses shorter than this keep the previous caption on screen
HOLD_TAIL = 0.25  # after a longer pause the caption lingers this long


def align_segments(words: list[tuple[float, float, str]], segments: list[dict[str, Any]],
                   maxlen: float = MAX_CHARS, max_lines: int = 1) -> list[dict[str, Any]]:
    """segments: [{t0, t1, text}] (timeline seconds, exact script, optional <key>/<neg>/|
    markup). Returns caption specs [{start, end, text, kind}] on the timeline clock.
    Each caption starts when its first word starts being spoken."""
    subs: list[dict[str, Any]] = []
    for seg in segments:
        a, b, raw = _f(seg.get("t0")), _f(seg.get("t1")), str(seg.get("text") or "").strip()
        text = plain_text(raw)
        if not text or b <= a:
            continue
        ws = [w for w in words if a - 0.15 <= w[0] < b - 0.1]
        ct = _char_times(ws, _norm(text)) if ws else None
        if ct is None:
            cs = chunk_script(raw, maxlen, max_lines)
            total = sum(max(1, c["b"] - c["a"]) for c in cs) or 1
            cur = a
            for c in cs:
                d = (b - a) * max(1, c["b"] - c["a"]) / total
                subs.append({"start": round(cur, 2), "end": round(cur + d - 0.03, 2), "text": c["text"], "kind": c["kind"]})
                cur += d
            continue

        def span(i: int, j: int, ct=ct) -> float | None:
            if j <= i or j > len(ct):
                return None
            return ct[j - 1][1] - ct[i][0]

        for c in chunk_script(raw, maxlen, max_lines, span):
            if c["b"] <= c["a"]:
                continue
            st = max(a, ct[c["a"]][0])
            en = min(b, max(ct[c["b"] - 1][1], st + 0.3))
            subs.append({"start": st, "end": en, "text": c["text"], "kind": c["kind"]})
    subs.sort(key=lambda s: s["start"])
    for i, s in enumerate(subs):
        nxt = subs[i + 1]["start"] if i + 1 < len(subs) else None
        if nxt is not None and nxt - s["end"] < HOLD_GAP:
            s["end"] = nxt  # never delay the next one; no flicker between them
        else:
            s["end"] = s["end"] + HOLD_TAIL if nxt is None else min(s["end"] + HOLD_TAIL, nxt - 0.03)
        if s["end"] - s["start"] < 0.2:
            s["end"] = s["start"] + 0.2
            if nxt is not None and nxt < s["end"]:
                subs[i + 1]["start"] = s["end"]
        s["start"], s["end"] = round(s["start"], 2), round(s["end"], 2)
    return subs


DEFAULT_STYLE = {"font": "noto-sans", "fontSize": 0.85, "color": "#ffffff", "outlineColor": "#000000",
                 "outlineWidth": 2, "textAlign": "center", "maxWidth": 0.86, "y": 0.06}
# Emphasis kinds marked in the script. Size is relative to the normal caption.
KIND_STYLES = {
    "key": {"font": "dela-gothic", "color": "#FFD84D", "outlineColor": "#000000", "scale": 1.17},
    "neg": {"font": "dela-gothic", "color": "#FF4A4A", "outlineColor": "#000000", "scale": 1.17},
}


def kind_style(base: dict[str, Any], kind: str, override: dict[str, Any] | None = None) -> dict[str, Any]:
    if kind not in KIND_STYLES:
        return dict(base)
    d = dict(KIND_STYLES[kind])
    scale = d.pop("scale")
    st = {**base, **d}
    st["fontSize"] = round(_f(base.get("fontSize"), 1.0) * scale, 3)
    st["outlineWidth"] = round(_f(base.get("outlineWidth"), 1.0) * 1.15, 3)
    if isinstance(override, dict):
        st.update(override)
    return st


def auto_captions(sequence: dict[str, Any], assets: dict[str, dict[str, Any]], work_dir: Path,
                  segments: list[dict[str, Any]], style: dict[str, Any] | None = None,
                  replace: bool = True, whisper_model: str | None = None,
                  words: list | None = None, styles: dict[str, Any] | None = None,
                  max_chars: float | None = None, max_lines: int = 1) -> dict[str, Any]:
    """Align `segments` to the timeline's speech and write caption clips into `sequence`.
    replace=True removes existing captions inside the covered ranges first."""
    if not segments:
        return {"ok": False, "error": "segments required: [{t0,t1,text}]"}
    for stl in [style, *((styles or {}).values() if isinstance(styles, dict) else [])]:
        font_err = tc.caption_font_error(stl)
        if font_err:
            return {"ok": False, "error": font_err}
    maxlen = max(6.0, min(40.0, _f(max_chars, MAX_CHARS))) if max_chars is not None else MAX_CHARS
    max_lines = 2 if int(max_lines or 1) >= 2 else 1
    lo = min(_f(s.get("t0")) for s in segments)
    hi = max(_f(s.get("t1")) for s in segments)
    supplied = words is not None
    if supplied:
        try:
            words = [(float(w[0]), float(w[1]), str(w[2])) for w in words]
            import math
            if any(not math.isfinite(st) or not math.isfinite(en) or en <= st for st,en,_ in words):
                raise ValueError('Invalid word interval')
        except (TypeError, ValueError, IndexError):
            return {'ok':False,'error':'words must contain [timeline_start, timeline_end, text] intervals'}
    else:
        wav = render_speech_wav(sequence, assets, work_dir, lo - 1.0, hi + 1.0)
        words = transcribe_words(wav, model=whisper_model) if wav else []
    specs = align_segments(words, segments, maxlen, max_lines)
    expected = ''.join(_norm(plain_text(str(s.get('text') or ''))) for s in segments)
    actual = ''.join(_norm(s['text']) for s in specs)
    if expected != actual:
        return {'ok':False,'error':'字幕の文字が欠ける時刻配分です。範囲か単語時刻を確認してください。既存字幕は変更していません。'}
    if replace:
        for track in sequence.get("tracks") or []:
            if str(track.get("type") or "") != "caption":
                continue
            keep = []
            for c in track.get("clips") or []:
                cs, ce = _f(c.get("timeline_start")), _f(c.get("timeline_end"))
                covered = any(_f(s.get("t0")) - 0.2 <= cs and ce <= _f(s.get("t1")) + 0.2 for s in segments)
                if not covered:
                    keep.append(c)
            track["clips"] = keep
    st = dict(DEFAULT_STYLE)
    if isinstance(style, dict):
        st.update(style)
    ids = []
    used: dict[str, dict[str, Any]] = {}
    for sp in specs:
        kind = sp.get("kind") or "normal"
        if kind not in used:
            used[kind] = kind_style(st, kind, (styles or {}).get(kind) if isinstance(styles, dict) else None)
        sp["style"] = used[kind]
        r = tc.add_caption(sequence, text=sp["text"], timeline_start=sp["start"], timeline_end=sp["end"], style=used[kind])
        if r.get("ok"):
            ids.append(r["clip_id"])
    return {"ok": True, "captions": len(ids), "clip_ids": ids, "words": len(words), "style": st, "styles": used,
            "specs": specs, "timing_source": "supplied" if supplied else "transcribed"}
