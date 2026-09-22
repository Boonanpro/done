"""How a saved value should be SPOKEN. The speech model guesses readings from written text: it dropped the zero of
「-0807」, read an expiry as 「十月二十九年」, and read 尼崎駅前 as 「あまさきまえ」. Give it the reading instead of the spelling.

Deterministic, no model call:
  identifiers (postcode, phone, card, codes)  -> digit by digit, grouped the way people say them
  MM/YY expiry                                -> 「二〇二九年の十月」 order
  address                                     -> prefecture/city/town in kana from Japan Post's public postcode table
                                                 (built and tested, switched off by KANA=False: the owner preferred the normal spelling)
Learned once, then remembered:
  names the table does not cover (building, company, person)  -> asked once from the flat-rate model in the background,
    kept in ~/.dan/voice-readings.json under a hash of the written form, so the file never holds the written value
Anything else is left to the speech model."""
import hashlib
import json
import csv
import io
import re
import threading
import unicodedata
import zipfile
from pathlib import Path

DIGIT = dict(zip('0123456789', ('ゼロ', 'いち', 'に', 'さん', 'よん', 'ご', 'ろく', 'なな', 'はち', 'きゅう')))
POSTCODES = Path.home()/'.dan'/'data'/'utf_ken_all.zip'   # https://www.post.japanpost.jp/service/search/zipcode/download/utf-zip.html
_towns = None
KANA = False   # owner's decision 2026-09-21: only numbers get a spoken form; place and building names go back to their normal spelling
_lock = threading.Lock()


def digits(run):
    """A run of digits as people read an identifier aloud: one by one, long runs in fours."""
    parts = [run[i:i+4] for i in range(0, len(run), 4)] if len(run) > 6 else [run]
    return '、'.join(''.join(DIGIT[c] for c in p) for p in parts)


def hiragana(text):
    return ''.join(chr(ord(c)-0x60) if 'ァ' <= c <= 'ヶ' else c for c in text)


def towns():
    """{(prefecture+city+town kanji): kana, (city+town kanji): kana}; empty when the table is not installed."""
    global _towns
    with _lock:
        if _towns is None:
            _towns = {}
            try:
                with zipfile.ZipFile(POSTCODES) as z:
                    for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8')):
                        if '以下に掲載' in r[8] or '（' in r[8]: town, town_kana = '', ''
                        else: town, town_kana = r[8], r[5]
                        kana = [hiragana(r[3]), hiragana(r[4])]+([hiragana(town_kana)] if town else [])
                        _towns.setdefault(r[6]+r[7]+town, '、'.join(kana))
                        _towns.setdefault(r[7]+town, '、'.join(kana[1:]))
            except (OSError, KeyError, IndexError, zipfile.BadZipFile):
                pass
        return _towns


def address(text):
    """Replace the longest prefecture/city/town prefix found in the text with its kana; None when nothing matches."""
    table = towns()
    if not table: return None
    for start in range(min(len(text), 16)):
        if not '一' <= text[start] <= '鿿': continue
        for end in range(min(len(text), start+30), start+2, -1):
            kana = table.get(text[start:end])
            if kana: return (text[:start]+kana+'、'+text[end:].lstrip()).rstrip('、')
    return None


def say(value):
    """The spoken form of a saved value, or None when the written form is fine as it is."""
    v = unicodedata.normalize('NFKC', str(value)).strip()
    expiry = re.fullmatch(r'(\d{1,2})\s*/\s*(\d{2}|\d{4})', v)
    if expiry and 1 <= int(expiry.group(1)) <= 12:
        year = expiry.group(2) if len(expiry.group(2)) == 4 else '20'+expiry.group(2)
        return f'{year}年の{int(expiry.group(1))}月'
    date = re.fullmatch(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', v)
    if date: return f'{date.group(1)}年{int(date.group(2))}月{int(date.group(3))}日'
    if re.fullmatch(r'[〒+\d\s\-()]+', v) and sum(c.isdigit() for c in v) >= 3:
        return ('プラス、' if v.lstrip('〒 ').startswith('+') else '')+'の、'.join(digits(run) for run in re.findall(r'\d+', v))
    spoken = v
    if KANA and re.search(r'[都道府県市区町村郡]', v):
        spoken = address(re.sub(r'〒?\s*\d{3}-?\d{4}\s*', '', v, count=1) if re.match(r'\s*〒?\s*\d{3}-?\d{4}', v) else v) or v
        postcode = re.match(r'\s*〒?\s*(\d{3})-?(\d{4})', v)
        if postcode and spoken != v: spoken = f'郵便番号、{digits(postcode.group(1))}の、{digits(postcode.group(2))}。'+spoken
    if not KANA:   # a postcode inside a sentence or an address
        spoken = re.sub(r'〒?\s*(\d{3})-(\d{4})(?!\d)\s*', lambda m: f'郵便番号、{digits(m.group(1))}の、{digits(m.group(2))}。', spoken)
    # a run that starts with zero, or a long one, is an identifier inside a sentence: its zero must not be dropped
    spoken = re.sub(r'(?<![\d.])(0\d+|\d{7,})(?![\d.])', lambda m: digits(m.group(1)), spoken)
    return spoken if spoken != v else None


LEARNED = Path.home()/'.dan'/'voice-readings.json'
NAME = re.compile(r'[一-鿿々][一-鿿々ぁ-んァ-ヶーA-Za-z]*')   # a written name that starts with kanji
_learned = None
_asking = set()


def _key(name): return hashlib.sha256(name.encode('utf-8')).hexdigest()[:24]


def learned():
    global _learned
    if _learned is None:
        try: _learned = json.loads(LEARNED.read_text(encoding='utf-8'))
        except (OSError, ValueError): _learned = {}
    return _learned


def ask(names):
    """Blocking (about ten seconds): the readings of written names from the flat-rate model. Returns {name: hiragana}."""
    from app.agent.cli_runner import run_oneshot_cli
    prompt = ('次の表記それぞれの読みを、ひらがなだけで答えてください。地名・建物名・会社名・人名です。'
              '出力はJSONオブジェクト1つだけ（キー=表記そのまま、値=ひらがな。カタカナや英字もひらがなにする）。説明は不要。\n'
              + json.dumps(names, ensure_ascii=False))
    text = run_oneshot_cli(prompt, model='haiku', timeout=60) or ''
    found = re.search(r'\{.*\}', text, re.S)
    try: data = json.loads(found.group(0)) if found else {}
    except ValueError: data = {}
    return {n: r for n, r in data.items() if n in names and isinstance(r, str) and re.fullmatch(r'[ぁ-んー]+', r)}


def learn(names):
    """Background: ask once, remember for good. The next answer uses it."""
    names = [n for n in names if _key(n) not in learned() and n not in _asking][:12]
    if not names: return
    _asking.update(names)
    def run():
        try:
            got = ask(names)
            if got:
                with _lock:
                    learned().update({_key(n): r for n, r in got.items()})
                    LEARNED.parent.mkdir(parents=True, exist_ok=True)
                    LEARNED.write_text(json.dumps(learned(), ensure_ascii=False), encoding='utf-8')
        finally:
            _asking.difference_update(names)
    threading.Thread(target=run, daemon=True).start()


def names_in(spoken):
    """Written names still left in a spoken form, read from their spelling by the speech model unless learned."""
    return [n for n in NAME.findall(spoken) if len(n) >= 2 and n not in ('郵便番号',)]


def annotate(facts):
    """Add 'say' to each {label,value} that should not be read from its spelling."""
    for fact in facts:
        try:
            value = str(fact.get('value', ''))
            spoken = say(value)
            # only values that are a place or a name, never free text: the written names go to the model once
            if KANA and spoken and spoken != value and re.search(r'[都道府県市区町村郡]', value):
                pending = []
                for name in names_in(spoken):
                    reading = learned().get(_key(name))
                    if reading: spoken = spoken.replace(name, reading)
                    else: pending.append(name)
                learn(pending)
        except Exception: spoken = None
        if spoken: fact['say'] = spoken
    return facts


SAY_NOTE = 'say がある項目は、value の字面から読みを推測せず、say に書かれた通りに発音する（数字は1桁ずつ、区切りの「、」で短く間を置く。ひらがなの地名はそのまま読む）。'
