"""
解約の申し出を人手なしで捌く仕組みの検査。

ここが壊れると、直接の被害は 2 つ。
1. やめたい人が永久に閉じ込められる（＝抜けられないアプリになる）
2. 解除コードが端末と食い違い、鍵を預かっているのに開けられない

どちらも「静かに壊れて、報告されるのは口コミが荒れてから」なので、
挙動を固定値で押さえておく。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.services import pornblocker_cancellation_service as mod
from app.services.pornblocker_cancellation_service import (
    JST,
    PornblockerCancellationService,
    compute_unlock_code,
)


# ==================================================================== 偽の台帳


class _Query:
    """supabase のクエリビルダの、この機能が使う分だけの模造品。"""

    def __init__(self, store: list, table: str):
        self.store = store
        self.table_name = table
        self.filters = []
        self._insert = None
        self._update = None

    # --- 絞り込み
    def select(self, *_):
        return self

    def eq(self, col, val):
        self.filters.append(lambda r: r.get(col) == val)
        return self

    def lte(self, col, val):
        self.filters.append(lambda r: r.get(col) is not None and r.get(col) <= val)
        return self

    def is_(self, col, _null):
        self.filters.append(lambda r: r.get(col) is None)
        return self

    @property
    def not_(self):
        parent = self

        class _Not:
            def is_(self, col, _null):
                parent.filters.append(lambda r: r.get(col) is not None)
                return parent

        return _Not()

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    # --- 書き込み
    def insert(self, row):
        self._insert = row
        return self

    def update(self, patch):
        self._update = patch
        return self

    #: 実テーブルの DEFAULT。入れておかないと、列を触らない書き込みの後で
    #: 状態が読めず、本番では起きない失敗をここだけで踏む。
    DEFAULTS = {"pornblocker_cancellations": {"state": "none", "attempts": 0}}

    def execute(self):
        if self._insert is not None:
            rows = self._insert if isinstance(self._insert, list) else [self._insert]
            base = self.DEFAULTS.get(self.table_name, {})
            stored = [{**base, **dict(r)} for r in rows]
            self.store.extend(stored)
            return _Result(stored)

        matched = [r for r in self.store if all(f(r) for f in self.filters)]
        if self._update is not None:
            for r in matched:
                r.update(self._update)
        return _Result(matched)


class _Result:
    def __init__(self, data):
        self.data = data


class _FakeSupabase:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return _Query(self.tables.setdefault(name, []), name)


@pytest.fixture
def svc(monkeypatch):
    """台帳と AI を偽物に差し替えたサービス。"""
    fake = _FakeSupabase()

    class _Client:
        client = fake

    monkeypatch.setattr(mod, "get_supabase_client", lambda: _Client())
    # 返事を書き込む先（やりとりの台帳）も同じ偽物に向ける。
    # ここを外すと、検査が本物のデータベースへ書きに行く。
    from app.services import pornblocker_guard_beacon_service as beacon_mod

    monkeypatch.setattr(beacon_mod, "get_supabase_client", lambda: _Client())
    # AI は呼ばない。呼ぶと結果が毎回変わり、検査にならない。
    monkeypatch.setattr(mod, "_ask_model", lambda *a, **k: None)
    # 鍵は固定。アプリ側 UnlockCodeTest と同じ値。
    monkeypatch.setattr(
        mod.settings,
        "PORNBLOCKER_UNLOCK_MASTER_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef",
        raising=False,
    )
    monkeypatch.setattr(mod.settings, "PORNBLOCKER_STRIPE_SECRET_KEY", "", raising=False)

    s = PornblockerCancellationService()
    s._fake = fake
    return s


def _messages(svc):
    return svc._fake.tables.get("pornblocker_messages", [])


def _run(coro):
    # 自前のループを立てて閉じる。使い回すと、先に走った別の検査が
    # ループを閉じていた場合にここだけ落ちる（単体では通るのに全体で落ちる）。
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ==================================================================== 解除コード


def test_解除コードは端末と同じ値になる(monkeypatch):
    """
    アプリ側 UnlockCodeTest.kt の固定値。**片方だけ直すと鍵が開かない。**
    ここが落ちたら、先に端末側を確かめること。
    """
    monkeypatch.setattr(
        mod.settings,
        "PORNBLOCKER_UNLOCK_MASTER_KEY",
        "0123456789abcdef0123456789abcdef0123456789abcdef",
        raising=False,
    )
    assert compute_unlock_code("AB23CD") == "30142488"
    assert compute_unlock_code("ZZZZZZ") == "93955312"
    # 管理者が小文字で打ち返しても同じ値になる。
    assert compute_unlock_code("ab23cd") == "30142488"


def test_鍵が無ければコードを作らない(monkeypatch):
    """作れないのに嘘の数字を返すと、本人が何度入れても開かない状態になる。"""
    monkeypatch.setattr(mod.settings, "PORNBLOCKER_UNLOCK_MASTER_KEY", "", raising=False)
    assert compute_unlock_code("AB23CD") is None


# ==================================================================== 返事の時刻


def test_深夜の申し出は翌朝まで返さない(svc):
    """一番申し出が多い時間帯。ここで即答すると、衝動が冷める時間を奪う。"""
    for hour in (23, 1, 3, 6):
        now = datetime(2026, 8, 6, hour, 0, tzinfo=JST).astimezone(timezone.utc)
        due = svc._decide_reply_time(now).astimezone(JST)
        assert 7 <= due.hour <= 9, f"{hour}時の申し出が{due.hour}時に返っている"
        assert due > now.astimezone(JST)


def test_日中は数十分から数時間で返す(svc):
    """即答は機械だと分かる。かといって日中に丸一日待たせると不信になる。"""
    now = datetime(2026, 8, 6, 13, 0, tzinfo=JST).astimezone(timezone.utc)
    for _ in range(50):
        due = svc._decide_reply_time(now)
        delta = (due - now).total_seconds() / 60
        assert 25 <= delta <= 180


def test_返す頃に深夜なら翌朝へ回す(svc):
    """22時50分に来たものを3時間後に返すと、深夜2時に返事が届く。"""
    now = datetime(2026, 8, 6, 22, 50, tzinfo=JST).astimezone(timezone.utc)
    for _ in range(50):
        due = svc._decide_reply_time(now).astimezone(JST)
        assert not (due.hour >= 23 or due.hour < 7)


# ==================================================================== 引き止め


def test_一回目は引き止めてコードを出さない(svc):
    r = _run(svc.on_user_message("dev1", "解約したいです"))
    assert r["intent"] == "cancel"
    assert r["attempts"] == 1

    row = svc._fake.tables["pornblocker_cancellations"][0]
    assert row["state"] == "requested"
    assert "30142488" not in (row["pending_reply"] or "")
    # 数字らしきコードが混ざっていないこと。
    assert "解除コード" not in row["pending_reply"]


def test_二回目は必ず通してコードを出す(svc):
    _run(svc.on_user_message("dev1", "解約したいです", request_id="AB23CD"))
    r = _run(svc.on_user_message("dev1", "やっぱり解約でお願いします", request_id="AB23CD"))

    assert r["attempts"] == 2
    row = svc._fake.tables["pornblocker_cancellations"][0]
    assert row["state"] == "released"
    assert "30142488" in row["pending_reply"]
    assert row["released_code"] == "30142488"


def test_二回目はAIが引き止めようとしても通す(svc, monkeypatch):
    """
    引き止めるかどうかを AI の裁量にしない。

    何度でも引き止める作りは、解約を著しく困難にする行為として問題になる。
    ここは文章ではなく仕組みで縛る。
    """
    monkeypatch.setattr(
        mod,
        "_ask_model",
        lambda *a, **k: {"intent": "cancel", "reply": "もう少しだけ続けてみませんか。"},
    )
    _run(svc.on_user_message("dev1", "解約", request_id="AB23CD"))
    _run(svc.on_user_message("dev1", "解約", request_id="AB23CD"))

    row = svc._fake.tables["pornblocker_cancellations"][0]
    assert row["state"] == "released"
    assert "30142488" in row["pending_reply"]


def test_撤回したら回数は振り出しに戻る(svc):
    """
    半年後にまたやめたくなった人が、いきなり2回目扱いで素通しになるのを防ぐ。
    撤回はやり直しであって、進行ではない。
    """
    _run(svc.on_user_message("dev1", "解約したい"))
    _run(svc.on_user_message("dev1", "やっぱり続けます"))

    row = svc._fake.tables["pornblocker_cancellations"][0]
    assert row["state"] == "none"
    assert row["attempts"] == 0

    r = _run(svc.on_user_message("dev1", "解約したい"))
    assert r["attempts"] == 1


def test_解約以外の相談も同じだけ待たせる(svc):
    """
    ここだけ即答すると、解約のときだけ返事が遅いことがすぐ分かる。
    """
    r = _run(svc.on_user_message("dev1", "仕事で使うサイトが止まりました"))
    assert r["intent"] == "other"
    row = svc._fake.tables["pornblocker_cancellations"][0]
    assert row["reply_due_at"] is not None
    assert row["state"] == "none"


# ==================================================================== 流し込み


def test_時間が来るまで返事は出ない(svc):
    _run(svc.on_user_message("dev1", "解約したい"))
    sent = _run(svc.flush_due_replies("dev1"))
    assert sent == 0
    assert _messages(svc) == []


def test_時間が来たら返事が出る(svc):
    _run(svc.on_user_message("dev1", "解約したい"))
    row = svc._fake.tables["pornblocker_cancellations"][0]
    row["reply_due_at"] = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()

    assert _run(svc.flush_due_replies("dev1")) == 1
    msgs = _messages(svc)
    assert len(msgs) == 1
    assert msgs[0]["sender"] == "admin"

    # 二度流さない。同じ返事が並ぶと、相手をしているのが機械だと分かる。
    assert _run(svc.flush_due_replies("dev1")) == 0
    assert len(_messages(svc)) == 1


def test_返事が滞っても一定時間で鍵が開く(svc):
    """
    引き止めの返事が作れない・流す機会が来ないといった不具合で
    本人が閉じ込められる事態だけは避ける。商品が緩むより事故のほうが高くつく。
    """
    _run(svc.on_user_message("dev1", "解約したい", request_id="AB23CD"))
    row = svc._fake.tables["pornblocker_cancellations"][0]
    old = datetime.now(timezone.utc) - timedelta(hours=mod.FAILSAFE_HOURS + 1)
    row["first_requested_at"] = old.isoformat()
    row["released_request_id"] = "AB23CD"
    # 返事は出せていない状態にする（期限はまだ先）。
    row["reply_due_at"] = (datetime.now(timezone.utc) + timedelta(hours=5)).isoformat()

    assert _run(svc.flush_due_replies("dev1")) == 1
    assert row["state"] == "released"
    assert "30142488" in _messages(svc)[0]["text"]


# ==================================================================== 読み取り


def test_言葉尻でも解約を取りこぼさない(svc):
    """AI が使えないときの受け皿。取りこぼして無視するのが一番まずい。"""
    for text in ("解約したい", "もうやめたい", "鍵を外してください", "コードください"):
        assert mod._guess_intent(text, 0) == "cancel", text


def test_撤回は申し出た後だけ拾う(svc):
    # 申し出ていない人の「このまま続けます」を撤回と取ると、状態が壊れる。
    assert mod._guess_intent("このまま続けます", 0) == "other"
    assert mod._guess_intent("このまま続けます", 1) == "resume"


def test_AIの返事が壊れていたら使わない():
    assert mod._parse("") is None
    assert mod._parse("すみません、わかりません") is None
    assert mod._parse('{"intent": "unknown", "reply": "x"}') is None
    assert mod._parse('{"intent": "cancel", "reply": ""}') is None
    # 前後に説明が付いてきても拾う。
    assert mod._parse('はい\n{"intent": "cancel", "reply": "わかりました"}\n以上') == {
        "intent": "cancel",
        "reply": "わかりました",
    }
