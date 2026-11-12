"""Places near a point, anywhere (owner, 2026-10-03): 「近くの〇〇」 and lists such as 「〇〇市の工務店」 without a browser.
Japan: OpenPOI API (3.37M facilities: Overture Maps + food business permits; free, no key). Elsewhere, and as a second
source in Japan when OpenPOI finds little: Photon (komoot's OpenStreetMap search; free, no key). Place names are turned
into coordinates with Nominatim (OpenStreetMap's own search). Neither has opening hours or reviews: check the few that
matter with web_search.

Photon's public server stopped answering its API on 2026-11-13 (the home page loads, /api/ times out) and every places
call waited the client's 20 s for it, three in a row in one call lookup: 20.9 s, 41.8 s, 62.7 s. Place names now go to
Nominatim (0.5 s; its policy: at most one request a second, an identifying User-Agent), and each Photon request has a
short limit of its own, so a dead Photon costs PHOTON_S and the results come from the sources that answered.

Attribution the sources ask for is returned with the results (OpenPOI: a link to OpenPOI API; OSM: © OpenStreetMap)."""
import math
import os

import httpx

OPENPOI = 'https://api.openpoiapi.com/v1/search'
PHOTON = 'https://photon.komoot.io/api/'
NOMINATIM = 'https://nominatim.openstreetmap.org/search'
GSI = 'https://msearch.gsi.go.jp/address-search/AddressSearch'   # 国土地理院: Japanese place names and addresses
PHOTON_S = 3          # Photon answers in under a second when it is up
PHOTON_REST_S = 600   # after Photon has not answered, it is left alone this long (a dead Photon would cost PHOTON_S each call)
_photon_down = [0.0]


def photon_up():
    import time
    return time.monotonic() >= _photon_down[0]


def photon_failed():
    import time
    _photon_down[0] = time.monotonic() + PHOTON_REST_S
UA = {'User-Agent': 'Dan/1.0 (personal assistant; places lookup)'}

TOOL = {
    'name': 'places',
    'description': ('近くの店・施設や、ある地域の店・会社の一覧を、ブラウザなしで一瞬で出す（世界中。日本は OpenPOI、海外は OpenStreetMap）。'
                    '「近くの〇〇」「〇〇駅の周りの〇〇」「〇〇市の工務店を全部」など。距離順に、名前・種類・距離・住所（あれば）・座標を返す。'
                    '中心は lat/lng、なければ near（地名）、どちらもなければ本人の現在地。営業時間・評判・電話は載っていないことが多いので、'
                    '絞った数件だけ web_search で確かめる。海外は query を英語で（cafe, ramen など）。名前に出ない種類（百均・金物店・薬局など）は osm_tag も付ける（日本でも効く。百均なら shop:variety_store）。結果を本人に見せる時は出典を添える。'),
    'input_schema': {'type': 'object', 'properties': {
        'query': {'type': 'string', 'description': '探す物。空白で区切った語のどれかに当たれば出る。一般名だけでは名前に出ないことが多いので店名・チェーン名も並べる（例: 「百均」なら「ダイソー セリア キャンドゥ ワッツ」、ラーメン、工務店、cafe）'},
        'near': {'type': 'string', 'description': '中心にする地名（例: 小倉駅、北九州市、Shibuya、Paris 11e）'},
        'lat': {'type': 'number'}, 'lng': {'type': 'number'},
        'osm_tag': {'type': 'string', 'description': '海外で種類で探す時の OpenStreetMap のタグ（例: shop:hardware, amenity:cafe, amenity:pharmacy, tourism:hotel）。名前に含まれない種類はこれで見つかる'},
        'radius_m': {'type': 'integer', 'minimum': 50, 'maximum': 50000, 'description': '探す半径（既定1000m。市全体なら10000〜30000）'},
        'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100, 'description': '返す件数（既定20）'},
    }, 'required': ['query'], 'additionalProperties': False},
}


def in_japan(lat, lng):
    return 20 <= lat <= 46 and 122 <= lng <= 154


def distance_m(lat1, lng1, lat2, lng2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2-p1)/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(math.radians(lng2-lng1)/2)**2
    return round(2*r*math.asin(math.sqrt(a)))


_nominatim_gate = [0.0]


async def nominatim(client, params):
    """One Nominatim request, at most one a second from this process (its usage policy)."""
    import asyncio, time
    wait = _nominatim_gate[0] + 1.05 - time.monotonic()
    _nominatim_gate[0] = time.monotonic() + max(0.0, wait)
    if wait > 0:
        await asyncio.sleep(wait)
    r = await client.get(NOMINATIM, params={'format': 'jsonv2', 'accept-language': 'ja', **params}, headers=UA, timeout=8)
    return r.json() if r.status_code == 200 else []


async def gsi(client, text):
    r = await client.get(GSI, params={'q': text}, headers=UA, timeout=4)
    return r.json() if r.status_code == 200 else []


_geocoded = {}   # place name -> (lat, lng, label): a lookup asks the same place again (2026-11-13: four places at once)


async def geocode(client, text):
    key = ' '.join(text.split())
    if key not in _geocoded:
        found = await _geocode(client, key)
        if found is None:
            return None
        if len(_geocoded) > 500: _geocoded.clear()
        _geocoded[key] = found
    return _geocoded[key]


async def _geocode(client, text):
    # Nominatim takes 0.3-5 s; the 国土地理院 search, asked at the same time, answers Japanese names when it is slow.
    import asyncio
    backup = asyncio.ensure_future(gsi(client, text))
    try:
        found = await asyncio.wait_for(nominatim(client, {'q': text, 'limit': 1}), 4)
    except Exception:
        found = []
    if not found:
        try:
            rows = await backup
        except Exception:
            rows = []
        if rows:
            lng, lat = rows[0]['geometry']['coordinates']
            return lat, lng, rows[0]['properties'].get('title') or text
    else:
        backup.cancel()
    if found:
        x = found[0]
        name = x.get('name') or ''
        return float(x['lat']), float(x['lon']), ', '.join(v for v in (name, x.get('display_name', '').split(', ')[-1]) if v)
    if not photon_up():
        return None
    try:   # Photon, when it is up, knows a few names Nominatim does not
        r = await client.get(PHOTON, params={'q': text, 'limit': 1}, headers=UA, timeout=PHOTON_S)
        feats = r.json().get('features') or []
    except Exception:
        photon_failed()
        return None
    if not feats:
        return None
    lng, lat = feats[0]['geometry']['coordinates']
    p = feats[0]['properties']
    return lat, lng, ', '.join(x for x in (p.get('name'), p.get('city'), p.get('country')) if x)


async def nominatim_near(client, query, lat, lng, radius, limit):
    """OpenStreetMap places by name inside the circle's box (one request, the whole query)."""
    d_lat = radius/111000
    d_lng = radius/(111000*max(.1, math.cos(math.radians(lat))))
    rows = []
    for x in await nominatim(client, {'q': query, 'viewbox': f'{lng-d_lng},{lat+d_lat},{lng+d_lng},{lat-d_lat}', 'bounded': 1,
                                      'limit': min(40, limit*2)}):
        rows.append({'name': x.get('name') or '', 'kind': f"{x.get('category', '')}:{x.get('type', '')}",
                     'address': x.get('display_name') or '', 'lat': float(x['lat']), 'lng': float(x['lon']), 'source': 'OpenStreetMap'})
    return rows


async def openpoi(client, query, lat, lng, radius, limit):
    r = await client.get(OPENPOI, params={'q': query, 'center': f'{lng},{lat}', 'radius': radius, 'limit': min(200, limit*2)}, headers=UA)
    rows = []
    for x in (r.json().get('results') or []):
        rows.append({'name': x.get('name') or '', 'kind': x.get('business_type') or x.get('category') or '',
                     'address': ' '.join(v for v in (x.get('prefecture'), x.get('city'), x.get('address')) if v),
                     'lat': x.get('lat'), 'lng': x.get('lng'), 'source': 'OpenPOI'})
    return rows


async def photon(client, query, lat, lng, radius, limit, osm_tag=''):
    d_lat = radius/111000
    d_lng = radius/(111000*max(.1, math.cos(math.radians(lat))))
    bbox = f'{lng-d_lng},{lat-d_lat},{lng+d_lng},{lat+d_lat}'
    params = {'q': query, 'lat': lat, 'lon': lng, 'bbox': bbox, 'limit': min(50, limit*2)}
    if osm_tag:
        params['osm_tag'] = osm_tag
    if not photon_up():
        return []
    try:
        r = await client.get(PHOTON, params=params, headers=UA, timeout=PHOTON_S)
    except httpx.TimeoutException:
        photon_failed()
        raise
    rows = []
    for f in (r.json().get('features') or []):
        p = f['properties']
        if p.get('type') in ('city', 'district', 'county', 'state', 'country', 'street', 'locality') and p.get('osm_key') == 'place':
            continue
        x_lng, x_lat = f['geometry']['coordinates']
        rows.append({'name': p.get('name') or '', 'kind': f"{p.get('osm_key', '')}:{p.get('osm_value', '')}",
                     'address': ' '.join(str(v) for v in (p.get('street'), p.get('housenumber'), p.get('city'), p.get('country')) if v),
                     'lat': x_lat, 'lng': x_lng, 'source': 'OpenStreetMap'})
    return rows


async def find(query, lat=None, lng=None, near='', radius_m=1000, limit=20, user_id='', osm_tag=''):
    async with httpx.AsyncClient(timeout=20) as client:
        where = ''
        if lat is None or lng is None:
            if near:
                found = await geocode(client, near)
                if not found:
                    return {'success': False, 'error': f'「{near}」の場所が分からなかった'}
                lat, lng, where = found
            else:
                from app.services import user_location
                here = user_location.current(user_id) if user_id else None
                if not here or here.get('lat') is None:
                    return {'success': False, 'error': '中心が分からない（lat/lng か near を渡す。本人の現在地もまだ届いていない）'}
                lat, lng, where = here['lat'], here['lng'], f"本人の現在地（{here.get('area') or ''}、{here.get('minutes_ago')}分前）"
        # Japan: both sources at once (2026-10-03 call: OpenPOI had no DAISO in Amings Shioe 356 m away; OSM had it).
        import asyncio
        async def safe(coro):
            try:
                return await coro
            except Exception:
                return []
        # Photon matches a query as one phrase: each word on its own (up to 4), and the kind (osm_tag) with the first word
        words = query.split()[:4] or [query]
        jobs = [safe(photon(client, w, lat, lng, radius_m, limit)) for w in words]
        if osm_tag:
            jobs.append(safe(photon(client, words[0], lat, lng, radius_m, limit, osm_tag)))
        if in_japan(lat, lng):   # OpenPOI covers Japan; Nominatim's one request a second is kept for the place names
            jobs.insert(0, safe(openpoi(client, query, lat, lng, radius_m, limit)))
        else:
            jobs.append(safe(nominatim_near(client, query, lat, lng, radius_m, limit)))
        rows = [x for part in await asyncio.gather(*jobs) for x in part]
    out = []
    squash = lambda t: ''.join(t.lower().split())
    for x in rows:
        if x['lat'] is None or not x['name']:
            continue
        x['distance_m'] = distance_m(lat, lng, x['lat'], x['lng'])
        if x['distance_m'] > radius_m * 1.2:
            continue
        # the same place from both sources: names that contain one another, within 80 m
        twin = next((y for y in out if distance_m(x['lat'], x['lng'], y['lat'], y['lng']) <= 80
                     and (squash(x['name']) in squash(y['name']) or squash(y['name']) in squash(x['name']))), None)
        if twin:
            if len(x['name']) > len(twin['name']):
                twin['name'] = x['name']
            twin['address'] = twin['address'] or x['address']
            continue
        out.append(x)
    out.sort(key=lambda x: x['distance_m'])
    out = out[:limit]
    sources = sorted({x['source'] for x in out})
    credit = {'OpenPOI': '施設データ: OpenPOI API（https://docs.openpoiapi.com）', 'OpenStreetMap': '© OpenStreetMap contributors'}
    lines = [f'中心: {where or f"{lat:.5f},{lng:.5f}"} / 半径{radius_m}m / {len(out)}件（近い順）']
    lines += [f"- {x['name']}（{x['kind']}）{x['distance_m']}m {x['address']} [{x['lat']:.5f},{x['lng']:.5f}]" for x in out]
    lines += ['出典: ' + ' / '.join(credit[s] for s in sources)] if sources else ['見つからなかった（言い換える・半径を広げる・海外なら英語で）']
    return {'success': True, 'output': '\n'.join(lines)}


async def tool(params):
    q = str(params.get('query') or '').strip()
    if not q:
        return {'success': False, 'error': 'query が空'}
    return await find(q, params.get('lat'), params.get('lng'), str(params.get('near') or ''), int(params.get('radius_m') or 1000),
                      int(params.get('limit') or 20), os.environ.get('DAN_USER_ID', ''), str(params.get('osm_tag') or ''))
