"""Dan's Chrome should be signed in to the user's Google account unless the user does not want it: asked once, then done."""
import json

import pytest

from app.services import chrome_signin as C


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(C, 'ROOT', tmp_path/'state')
    async def accounts(user_id): return ['a@gmail.com', 'b@gmail.com']
    monkeypatch.setattr(C, 'known_accounts', accounts)
    profile = tmp_path/'profile'; profile.mkdir()
    return profile


def sign(profile, user=''):
    (profile/'Local State').write_text(json.dumps({'profile': {'info_cache': {'Default': {'user_name': user}}}}), encoding='utf-8')


@pytest.mark.asyncio
async def test_asked_once_with_the_known_accounts_then_quiet(setup):
    sign(setup)
    first = await C.note('u', setup)
    assert 'a@gmail.com / b@gmail.com' in first and '報告の最後に一言だけ聞く' in first
    assert await C.note('u', setup) == ''          # not asked again while the user has not answered


@pytest.mark.asyncio
async def test_approved_means_dan_signs_in_without_asking_and_declined_means_never_again(setup, monkeypatch):
    sign(setup)
    monkeypatch.setenv('DAN_USER_ID', 'u')
    await C.tool({'action': 'approve', 'account': 'A@gmail.com'})
    assert '承認済み' in await C.note('u', setup) and 'a@gmail.com' in await C.note('u', setup)
    sign(setup, 'a@gmail.com')
    assert await C.note('u', setup) == ''          # signed in: nothing to do
    sign(setup)
    await C.tool({'action': 'decline'})
    assert await C.note('u', setup) == ''
