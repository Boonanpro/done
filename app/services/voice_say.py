"""The one place that gives the call's speech model anything while the call runs (2026-11-07, the owner).

Why: the speech model talks about whatever it is given, silent context (thinking) and commentary alike. In the owner's
12:22 call the state of the work, given silently every few seconds as 「作業「…」の今（12:25:07）: …」, came out in three
unrelated replies (「今の時刻は12時25分7秒です」, the last one to 「電話切れ」); on 11/6 21:33 it was 「今、午後九時三十四分に
依頼内容を確認しています」. From 10/31 each fix had added one more place that pushed something into the call. The owner:
渡されたものは全部読んじゃうのは弱点ではなくそういう仕様。逆手に取って設計すればいい.

So only what is fine to be said as it is gets given, of the kinds below, and only from here. Everything else (what the
work is doing step by step, the clock, a report's full text, page addresses) is not given: the speech model reads it
through its backend when it wants it (voice_router: 'status' reads the work and its full results, 'clock' the time).
How the speech model words and times what it is given is its own (voice_plain); nothing here tells it what to say.
"""
import re
import time

KINDS = {
    'answer': 'the answer to what the speech model handed to the backend',
    'started': 'work began for what the speech model handed over (said only before Dan has acknowledged it himself)',
    'result': 'a piece of the call\'s work finished',
    'note': 'something the work wanted the owner to know on the way (voice_router.CALL_JOB_NOTE)',
    'problem': 'the work or the backend failed',
    'question': 'the work needs the owner to decide or answer',
    'summon': 'why Dan called the owner',
    'chat': 'what the owner sent to the room\'s chat during the call',
    'touch': 'what the owner pressed on the call\'s screen (a pin, a photo card, a frame; 2026-11-12)',
    'heard': 'the owner\'s own words the speech model did not hear itself (a whisper the server heard, voice_whisper)',
    'unheard': 'the owner said something neither the speech model nor the server could make out (voice_whisper)',
}
SHORT = 300    # one append is limited to 500 tokens; Japanese runs at about a token a character
LONG = 1200    # an answer to the owner's own question may say more, in several appends
LONG_KINDS = ('answer', 'chat')
CODE_KINDS = ('summon', 'question', 'answer')
# A number read digit by digit: a code, not an amount. 「802227」 went in whole and was said 「8、0、2、2、7」 (11/7 12:23).
CODE = re.compile(r'(?<![\d,.¥$＄/:-])(\d{4,8})(?![\d,.:/-]|\s*(?:円|年|月|日|時|分|秒|件|人|枚|個|回|歳|万|千|億|%|％|km|ｍ|m|g|kg|mm|cm|kcal|ml|h))')
SECONDS_CLOCK = re.compile(r'[（(]?\d{1,2}:\d{2}:\d{2}[）)]?')


def spaced_digits(match):
    digits = match.group(1)
    return '・'.join(digits) + f'（{len(digits)}桁）'


def site_of(url):
    from urllib.parse import urlparse
    host = urlparse(url if '://' in url else 'https://' + url).hostname or ''
    return host.removeprefix('www.') or 'ページ'


def speakable(kind, text):
    """The text as it may be said: no page addresses, no clock to the second, no thousands separators, codes digit by
    digit, and not longer than the kind allows (the first sentences of a long one)."""
    from app.services.voice_lookup import unspoken_urls
    from app.services.voice_lookup import URL_TEXT
    text = ' '.join(str(text or '').split())
    if kind == 'chat':   # what the owner sent: Dan knows a link came and from where, and does not read it out
        text = URL_TEXT.sub(lambda m: f'（{site_of(m.group(0))}のリンク）', text)
    text = unspoken_urls(text)
    text = SECONDS_CLOCK.sub('', text)
    text = re.sub(r'(?<=\d),(?=\d{3})', '', text)   # 14,320円 was read as 「十四、三百二十円」 (2026-09-22)
    if kind in CODE_KINDS:
        text = CODE.sub(spaced_digits, text)
    limit = LONG if kind in LONG_KINDS else SHORT
    if len(text) > limit:
        sentences = re.split(r'(?<=[。！？!?])', text)
        kept = ''
        for s in sentences:
            if len(kept) + len(s) > limit: break
            kept += s
        text = kept or text[:limit]
    return text.strip()


def pieces(text, size=SHORT):
    while text:
        cut = len(text) if len(text) <= size else max(text.rfind('。', 0, size) + 1, text.rfind('、', 0, size) + 1) or size
        yield text[:cut]
        text = text[cut:].lstrip()


async def say(send, kind, text, record=None, delegation_id=None, quiet=False):
    """Give the speech model one thing of a known kind. `quiet`: the answer to a delegation after Dan has already
    acknowledged it (the API asks him to by itself after voice_router.ACK_DELAY_MS) goes in as thinking, so he does not
    say 「調べるね」 and then 「調べ始めた」; it is still a sentence that may be said. Returns what was given."""
    if kind not in KINDS:
        raise ValueError(f'not a kind the call is given: {kind}')
    try:
        from app.services.voice_furigana import annotate
        text = annotate(text)
    except Exception:
        pass
    said = speakable(kind, text)
    channel = 'session.thinking.append' if quiet else 'session.commentary.append'
    parts = list(pieces(said)) or ([''] if delegation_id else [])   # a delegation is answered even with nothing to say
    for part in parts:
        await send({'type': channel, 'event_id': f'dan-{time.time_ns()}', 'delegation_id': delegation_id, 'content': part})
    if record is not None and parts:
        record('call_given', kind=kind, chars=len(said), quiet=bool(quiet), **({'delegation': True} if delegation_id else {}))
    return said
