"""
端末向けの入口を「短時間に何度も」から守る仕組みの検査。

【ここが壊れたときの被害】
1. 緩すぎる → 合言葉と端末の呼び名を総当たりされ、他人の契約や連絡が覗ける
2. 厳しすぎる → 正規の端末が黙らされ、守りが外れても運営に届かない

2 が起きても誰も気付かない（届かないことは、届かないので分からない）。
だから「正規の使い方は絶対に弾かれない」側を、固定値で押さえておく。
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.api import pornblocker_guard_beacon_routes as mod

TOKEN = "test-beacon-token"


class _FakeClient:
    def __init__(self, host: str):
        self.host = host


class _FakeRequest:
    """client_ip が見るところだけの模造品。"""

    def __init__(self, ip: str = "203.0.113.10", forwarded: str | None = None):
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}
        self.client = _FakeClient(ip)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    """合言葉を差し替え、数えた分を毎回まっさらにする。"""
    monkeypatch.setattr(mod.settings, "PORNBLOCKER_BEACON_TOKEN", TOKEN)
    for limiter in (
        mod._AUTH_FAILURES,
        mod._PER_IP,
        mod._PER_DEVICE,
        mod._PER_DEVICE_WRITE,
        mod._WEBHOOK_FAILURES,
    ):
        limiter._history.clear()
        limiter._blocked_until.clear()
    yield


# ==================================================================== 正規の使い方


def test_正しい合言葉は通る():
    mod._guard(_FakeRequest(), TOKEN, "device-a")


def test_端末は一分に六十回まで通る():
    """端末は 30 分に 1 回しか来ない。60 回は圏外明けのまとめ送信でも届かない。"""
    for _ in range(60):
        mod._guard(_FakeRequest(), TOKEN, "device-a")

    with pytest.raises(HTTPException) as e:
        mod._guard(_FakeRequest(), TOKEN, "device-a")
    assert e.value.status_code == 429


def test_ある端末の使いすぎが別の端末を巻き込まない():
    """
    数える単位が端末であることの確認。

    携帯回線は多数の契約者が同じ IP を共有する。ここを IP で数えていると、
    同じ回線の無関係な契約者が道連れになる。
    """
    for _ in range(60):
        mod._guard(_FakeRequest(ip="198.51.100.1"), TOKEN, "device-a")

    # 同じ回線・別の端末。通らなければならない。
    mod._guard(_FakeRequest(ip="198.51.100.1"), TOKEN, "device-b")


# ==================================================================== 合言葉の総当たり


def test_合言葉が違えば四〇一():
    with pytest.raises(HTTPException) as e:
        mod._guard(_FakeRequest(), "wrong-token", "device-a")
    assert e.value.status_code == 401


def test_合言葉を十回外すと締め出される():
    req = _FakeRequest(ip="192.0.2.55")
    for _ in range(10):
        with pytest.raises(HTTPException) as e:
            mod._guard(req, "wrong-token", "device-a")
        assert e.value.status_code == 401

    # 11 回目からは、突き合わせる前に止まる。
    with pytest.raises(HTTPException) as e:
        mod._guard(req, "wrong-token", "device-a")
    assert e.value.status_code == 429


def test_締め出し中は正しい合言葉でも通らない():
    """
    当てられた瞬間に通ってしまっては、総当たりを止めたことにならない。
    """
    req = _FakeRequest(ip="192.0.2.66")
    for _ in range(11):
        with pytest.raises(HTTPException):
            mod._guard(req, "wrong-token", "device-a")

    with pytest.raises(HTTPException) as e:
        mod._guard(req, TOKEN, "device-a")
    assert e.value.status_code == 429


def test_締め出しは回線ごとで他の回線に及ばない():
    bad = _FakeRequest(ip="192.0.2.77")
    for _ in range(11):
        with pytest.raises(HTTPException):
            mod._guard(bad, "wrong-token", "device-a")

    mod._guard(_FakeRequest(ip="192.0.2.78"), TOKEN, "device-a")


def test_合言葉が無い場合も外したとみなす():
    with pytest.raises(HTTPException) as e:
        mod._guard(_FakeRequest(), None, "device-a")
    assert e.value.status_code == 401


def test_受け口の合言葉が未設定なら閉じる(monkeypatch):
    """未設定で開けたままだと、誰でも「守られています」と嘘を送れる。"""
    monkeypatch.setattr(mod.settings, "PORNBLOCKER_BEACON_TOKEN", "")
    with pytest.raises(HTTPException) as e:
        mod._guard(_FakeRequest(), TOKEN, "device-a")
    assert e.value.status_code == 503


# ==================================================================== 呼び名の総当たり


def test_同じ回線から呼び名を変えて叩き続けると止まる():
    """
    端末の呼び名を総当たりする動きは、端末ごとの制限では止まらない。
    呼び名が毎回違うため。ここは回線で受け止める。
    """
    req = _FakeRequest(ip="192.0.2.90")
    for i in range(300):
        mod._guard(req, TOKEN, f"guess-{i}")

    with pytest.raises(HTTPException) as e:
        mod._guard(req, TOKEN, "guess-300")
    assert e.value.status_code == 429


# ==================================================================== 書き込み


def test_書き込みは一分に十回まで():
    for _ in range(10):
        mod._guard(_FakeRequest(), TOKEN, "device-a", write=True)

    with pytest.raises(HTTPException) as e:
        mod._guard(_FakeRequest(), TOKEN, "device-a", write=True)
    assert e.value.status_code == 429


def test_書き込みを使い切っても読み取りは残る():
    """
    解約の申し出を送りすぎた人が、そのやりとりを読めなくなってはいけない。
    """
    for _ in range(11):
        try:
            mod._guard(_FakeRequest(), TOKEN, "device-a", write=True)
        except HTTPException:
            pass

    mod._guard(_FakeRequest(), TOKEN, "device-a")


# ==================================================================== 待ち時間の伝達


def test_四二九には待ち時間が付く():
    """
    いつ再開してよいかを返さないと、端末は総当たりと同じ速さで再送を続ける。
    """
    for _ in range(10):
        mod._guard(_FakeRequest(), TOKEN, "device-a", write=True)

    with pytest.raises(HTTPException) as e:
        mod._guard(_FakeRequest(), TOKEN, "device-a", write=True)
    assert int(e.value.headers["Retry-After"]) >= 1


def test_プロキシ越しでも本当の回線で数える():
    """
    手前にプロキシが立つので、素の接続元だけを見ると全員が同じに見える。
    そうなると 1 人の総当たりで全員が締め出される。
    """
    a = _FakeRequest(ip="10.0.0.1", forwarded="192.0.2.100, 10.0.0.1")
    b = _FakeRequest(ip="10.0.0.1", forwarded="192.0.2.101, 10.0.0.1")

    for _ in range(11):
        with pytest.raises(HTTPException):
            mod._guard(a, "wrong-token", "device-a")

    # 別の利用者。同じプロキシを通っているが、巻き込まれない。
    mod._guard(b, TOKEN, "device-b")
