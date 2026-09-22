"""Where the owner is right now, shared by chat and voice.

The phone app reports its GPS fix while it is open (app opened, voice call started, moved). The server (the owner's
own PC) keeps only the latest fix per user, with the time it was taken, and turns it into a town name with the
Geospatial Information Authority's free reverse geocoder. Questions like 「この近く」「今いる所の天気」 get the town,
never the raw coordinates, unless a tool caller asks for them.
"""
import asyncio
import csv
import io
import json
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

STORE = Path.home()/'.dan'/'location'
POSTCODES = Path.home()/'.dan'/'data'/'utf_ken_all.zip'   # column 0 = municipality code, 6/7 = prefecture/city
GEOCODER = 'https://mreversegeocoder.gsi.go.jp/reverse-geocoder/LonLatToAddress'
FRESH_MINUTES = 30      # a fix older than this is "where you were", not "where you are"
_municipalities = None
_lock = threading.Lock()

TOOL = {
    'name': 'get_location',
    'description': ('本人のスマホが最後に知らせた現在地を返す（町名まで、取得した時刻、何分前か、緯度経度、精度）。'
                    '「この近く」「今いる所」「ここから」「今日の天気」など、場所が答えを左右する質問で、場所を本人に聞き返す前に使う。'
                    '30分より古い時は「最後に分かっている場所」として扱い、必要ならそのことを伝える。位置が一度も届いていなければ未取得と返る。'),
    'input_schema': {'type': 'object', 'properties': {}, 'additionalProperties': False},
}


def municipalities():
    """{5-digit municipality code: (prefecture, city)} from the postcode table already installed for voice readings."""
    global _municipalities
    with _lock:
        if _municipalities is None:
            _municipalities = {}
            try:
                with zipfile.ZipFile(POSTCODES) as z:
                    for r in csv.reader(io.TextIOWrapper(z.open(z.namelist()[0]), encoding='utf-8')):
                        _municipalities.setdefault(r[0], (r[6], r[7]))
            except (OSError, KeyError, IndexError, zipfile.BadZipFile):
                pass
        return _municipalities


async def area_of(lat, lng):
    """Town-level name for a coordinate, or '' when the geocoder is unreachable or the point is outside Japan."""
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            data = (await client.get(GEOCODER, params={'lat': lat, 'lon': lng})).json().get('results') or {}
    except (httpx.HTTPError, ValueError):
        return ''
    code = str(data.get('muniCd') or '').zfill(5)
    prefecture, city = (await asyncio.to_thread(municipalities)).get(code, ('', ''))
    return prefecture+city+str(data.get('lv01Nm') or '').replace('－', '')


def _path(user_id):
    return STORE/f'{"".join(c for c in str(user_id) if c.isalnum() or c == "-")}.json'


async def report(user_id, lat, lng, accuracy=None, taken_at=None):
    """Keep the latest fix. Returns the stored record."""
    if not (-90 <= lat <= 90 and -180 <= lng <= 180): raise ValueError('coordinates out of range')
    previous = read(user_id)
    moved = not previous or abs(previous['lat']-lat) > .002 or abs(previous['lng']-lng) > .002   # about 200 m
    area = await area_of(lat, lng) if moved or not previous.get('area') else previous['area']
    record = {'lat': round(lat, 6), 'lng': round(lng, 6), 'accuracy_m': round(accuracy) if accuracy is not None else None,
              'area': area, 'at': taken_at or datetime.now(timezone.utc).isoformat(), 'received': time.time()}
    STORE.mkdir(parents=True, exist_ok=True)
    temp = _path(user_id).with_suffix('.tmp'); temp.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8'); temp.replace(_path(user_id))
    return record


def read(user_id):
    try: return json.loads(_path(user_id).read_text(encoding='utf-8'))
    except (OSError, ValueError): return None


def current(user_id):
    """{'area','minutes_ago','fresh',...} or None when the phone has never reported."""
    record = read(user_id)
    if not record: return None
    minutes = max(0, round((time.time()-record.get('received', 0))/60))
    return {**{k: record.get(k) for k in ('area', 'lat', 'lng', 'accuracy_m', 'at')}, 'minutes_ago': minutes, 'fresh': minutes <= FRESH_MINUTES}


def place_for_speech(user_id):
    """What voice answers may assume about "here": the town only, and how old it is. None when unknown or without a name."""
    here = current(user_id)
    if not here or not here.get('area'): return None
    return {'current_place': here['area'], 'minutes_ago': here['minutes_ago'],
            'note': '本人のスマホが知らせた現在地。' + ('' if here['fresh'] else '30分以上前の位置なので、今もそこにいるとは限らない。')}


async def tool(user_id):
    here = current(user_id)
    if not here:
        return {'success': True, 'output': '現在地は未取得です（スマホのアプリから位置がまだ一度も届いていません。アプリを開くと届きます）。'}
    age = 'たった今' if here['minutes_ago'] < 2 else f"{here['minutes_ago']}分前"
    lines = [f"現在地: {here['area'] or '（町名は取得できず）'}", f"取得: {age}（{here['at']}）" + ('' if here['fresh'] else ' ※30分以上前の位置。今もそこにいるとは限らない'),
             f"緯度経度: {here['lat']}, {here['lng']}" + (f"（精度 約{here['accuracy_m']}m）" if here.get('accuracy_m') else '')]
    return {'success': True, 'output': '\n'.join(lines)}


async def home_area(user_id):
    """The owner's home town (prefecture + city) from the saved address: what "here" means until the phone reports a fix."""
    import re
    from app.services.personal_info_service import PersonalInfoService
    service = PersonalInfoService()
    try: rows = await asyncio.to_thread(service.list_masked_sync, user_id)
    except Exception: return None
    for row in rows:
        if row.get('category') != 'address': continue
        found = await service.get(user_id, row['field_key'])
        match = re.search(r'((?:東京都|北海道|(?:京都|大阪)府|[^\s\d〒]{2,3}県))?\s*([^\s\d〒]{1,10}?[市区町村])', str((found or {}).get('value') or ''))
        if match: return {'current_place': (match.group(1) or '')+match.group(2), 'note': '現在地は未取得。本人の自宅の市区町村を仮の場所として使っている。'}
    return None
