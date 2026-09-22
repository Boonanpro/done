import json
import pytest
from app.services import user_location as L


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(L, 'STORE', tmp_path)
    async def area(lat, lng): return '東京都千代田区丸の内一丁目'
    monkeypatch.setattr(L, 'area_of', area)
    return tmp_path


@pytest.mark.asyncio
async def test_latest_fix_is_kept_with_its_town_and_age(store):
    await L.report('u1', 35.681236, 139.767125, 12.4)
    here = L.current('u1')
    assert here['area'] == '東京都千代田区丸の内一丁目' and here['fresh'] and here['minutes_ago'] == 0 and here['accuracy_m'] == 12
    assert L.place_for_speech('u1')['current_place'] == '東京都千代田区丸の内一丁目'
    assert 'lat' not in L.place_for_speech('u1')   # speech gets the town, never the coordinates
    assert len(list(store.glob('*.json'))) == 1


@pytest.mark.asyncio
async def test_old_fix_is_where_you_were_not_where_you_are(store):
    await L.report('u1', 35.681236, 139.767125)
    path = next(store.glob('*.json')); record = json.loads(path.read_text(encoding='utf-8'))
    record['received'] -= 3 * 3600; path.write_text(json.dumps(record), encoding='utf-8')
    assert not L.current('u1')['fresh'] and '30分以上前' in L.place_for_speech('u1')['note']
    assert '今もそこにいるとは限らない' in (await L.tool('u1'))['output']


@pytest.mark.asyncio
async def test_never_reported_and_bad_coordinates(store):
    assert L.current('nobody') is None and '未取得' in (await L.tool('nobody'))['output']
    with pytest.raises(ValueError): await L.report('u1', 123.0, 500.0)
