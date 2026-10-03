"""Places near a point, anywhere (owner, 2026-10-03): 「近くの〇〇」 and lists such as 「〇〇市の工務店」 without a browser.
Japan: OpenPOI API (3.37M facilities: Overture Maps + food business permits; free, no key). Elsewhere, and as a second
source in Japan when OpenPOI finds little: Photon (komoot's OpenStreetMap search; free, no key). Place names are turned
into coordinates with Photon too. Neither has opening hours or reviews: check the few that matter with web_search.

Attribution the sources ask for is returned with the results (OpenPOI: a link to OpenPOI API; OSM: © OpenStreetMap)."""
import math
import os

import httpx

OPENPOI = 'https://api.openpoiapi.com/v1/search'
PHOTON = 'https://photon.komoot.io/api/'
UA = {'User-Agent': 'Dan/1.0 (personal assistant; places lookup)'}

TOOL = {
    'name': 'places',
    'description': ('近くの店・施設や、ある地域の店・会社の一覧を、ブラウザなしで一瞬で出す（世界中。日本は OpenPOI、海外は OpenStreetMap）。'
                    '「近くの〇〇」「〇〇駅の周りの〇〇」「〇〇市の工務店を全部」など。距離順に、名前・種類・距離・住所（あれば）・座標を返す。'
                    '中心は lat/lng、なければ near（地名）、どちらもなければ本人の現在地。営業時間・評判・電話は載っていないことが多いので、'
                    '絞った数件だけ web_search で確かめる。海外は query を英語で（cafe, ramen など）。名前に出ない種類（金物店・薬局など）は osm_tag も付ける。結果を本人に見せる時は出典を添える。'),
    'input_schema': {'type': 'object', 'properties': {
        'query': {'type': 'string', 'description': '探す物（例: ラーメン、工務店、薬局、cafe）'},
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


async def geocode(client, text):
    r = await client.get(PHOTON, params={'q': text, 'limit': 1}, headers=UA)
    feats = r.json().get('features') or []
    if not feats:
        return None
    lng, lat = feats[0]['geometry']['coordinates']
    p = feats[0]['properties']
    return lat, lng, ', '.join(x for x in (p.get('name'), p.get('city'), p.get('country')) if x)


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
    params = {'q': (osm_tag.split(':')[-1] if osm_tag else query), 'lat': lat, 'lon': lng, 'bbox': bbox, 'limit': min(50, limit*2)}
    if osm_tag:
        params['osm_tag'] = osm_tag
    r = await client.get(PHOTON, params=params, headers=UA)
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
        rows = []
        if in_japan(lat, lng):
            try:
                rows = await openpoi(client, query, lat, lng, radius_m, limit)
            except Exception:
                rows = []
        if len(rows) < 3:
            try:
                rows += await photon(client, query, lat, lng, radius_m, limit, osm_tag)
            except Exception:
                pass
    seen, out = set(), []
    for x in rows:
        if x['lat'] is None or not x['name']:
            continue
        x['distance_m'] = distance_m(lat, lng, x['lat'], x['lng'])
        key = (x['name'], round(x['lat'], 4), round(x['lng'], 4))
        if x['distance_m'] > radius_m * 1.2 or key in seen:
            continue
        seen.add(key)
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
