"""Readings for place names in what is handed to the speech model (owner, 2026-10-03: Live 1 read 杭瀬 and 尼崎 wrongly;
the speech model guesses readings from the written form). Only names whose real reading differs from the ordinary reading of
their characters get one, written after the name: 杭瀬本町（くいせほんまち）. 尼崎市 reads as written, so it is left alone.

Readings come from Japan Post's postcode table (~/.dan/data/utf_ken_all.zip, cities, wards and towns); the ordinary reading
from pykakasi. Both are local: a text is annotated in well under a millisecond after a one-time load (~0.7 s, started in the
background when this module is imported). The speech model's own words (from its knowledge) cannot be reached this way."""
import csv
import io
import re
import threading
import zipfile
from pathlib import Path

POSTCODES = Path.home()/'.dan'/'data'/'utf_ken_all.zip'
MAX_NOTES = 8
_names = None
_kakasi = None
_lock = threading.Lock()


def _hira(text):
    return ''.join(chr(ord(c)-0x60) if 'ァ' <= c <= 'ヶ' else c for c in text)


def _load():
    global _names, _kakasi
    with _lock:
        if _names is not None:
            return _names
        names = {}
        try:
            import pykakasi
            kakasi = pykakasi.kakasi()
            seen, city_kanas = {}, {}
            with zipfile.ZipFile(POSTCODES) as z:
                for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8')):
                    pairs = [(r[7], _hira(r[4]))]
                    ward = re.match(r'(.+?[市郡])(.+?[区町村])$', r[7])
                    if ward:   # 北九州市門司区: the ward's reading is what follows the city's (when the city reads as written)
                        if ward.group(1) not in city_kanas:
                            city_kanas[ward.group(1)] = ''.join(x['hira'] for x in kakasi.convert(ward.group(1)))
                        city_kana = city_kanas[ward.group(1)]
                        full = _hira(r[4])
                        if full.startswith(city_kana) and len(full) > len(city_kana):
                            pairs.append((ward.group(2), full[len(city_kana):]))
                    if r[8] and '（' not in r[8] and '以下' not in r[8] and not re.search(r'[0-9０-９]', r[8]):
                        pairs.append((r[8], _hira(r[5])))
                    for name, kana in pairs:
                        if len(name) >= 2 and re.fullmatch(r'[一-鿿々ヶ]+[市区町村郡]?|[一-鿿々ヶ]+', name):
                            seen.setdefault(name, set()).add(kana)
            # a name read two ways in different places is left alone (no guess)
            names = {n: next(iter(k)) for n, k in seen.items() if len(k) == 1}
            _kakasi = kakasi
        except Exception:
            names = {}
        _names = names
        return _names


def _ordinary(name):
    try:
        return ''.join(x['hira'] for x in _kakasi.convert(name))
    except Exception:
        return ''


def annotate(text):
    """The text with readings added after place names that are not read as written (first occurrence of each)."""
    if not text or not isinstance(text, str):
        return text
    names = _load()
    if not names or not _kakasi:
        return text
    out, i, notes, done = [], 0, 0, set()
    while i < len(text):
        hit = None
        if '一' <= text[i] <= '鿿' and notes < MAX_NOTES:
            for end in range(min(len(text), i + 10), i + 1, -1):
                name = text[i:end]
                if name in names:
                    hit = name
                    break
        if hit:
            out.append(hit)
            kana = names[hit]
            if hit not in done and kana != _ordinary(hit) and not text[i+len(hit):].startswith('（'):
                out.append(f'（{kana}）')
                done.add(hit); notes += 1
            i += len(hit)
            continue
        out.append(text[i]); i += 1
    return ''.join(out)


def annotate_all(value):
    """annotate() through a JSON-like value (strings in dicts and lists)."""
    if isinstance(value, str):
        return annotate(value)
    if isinstance(value, dict):
        return {k: annotate_all(v) for k, v in value.items()}
    if isinstance(value, list):
        return [annotate_all(v) for v in value]
    return value


threading.Thread(target=_load, daemon=True).start()
