"""
端末向け入口の回数制限を、本物の HTTP で確かめる。

ルーター自体を FastAPI に載せて叩く。台帳（Supabase）だけ模造品に
差し替える。差し替えるのは「保存先」だけで、ヘッダの読み取り・
経路の振り分け・状態コード・Retry-After は本物が動く。
"""
from __future__ import annotations

import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import pornblocker_guard_beacon_routes as mod
from app.api.chat_routes import TokenData, get_current_user

TOKEN = "verify-beacon-token"
DEVICE = "verify-device-0001"


class _FakeBeaconService:
    async def ingest(self, events):
        return len(events)


class _FakeBilling:
    async def get_status(self, device_id):
        return {"active": False, "status": "none", "current_period_end": None}

    async def list_messages(self, device_id, limit=100):
        return []

    async def add_message(self, device_id, sender, text):
        return {
            "id": 1,
            "device_id": device_id,
            "sender": sender,
            "text": text,
            "created_at": "2026-08-08T00:00:00+00:00",
        }


async def _noop_incoming(*_args, **_kwargs):
    """解約の受け付けは別の検査で見る。ここでは台帳に触らせない。"""
    return None


def build_client() -> TestClient:
    mod.settings.PORNBLOCKER_BEACON_TOKEN = TOKEN
    mod._handle_incoming = _noop_incoming

    app = FastAPI()
    app.include_router(mod.router, prefix="/api/v1")
    app.dependency_overrides[mod.get_service] = lambda: _FakeBeaconService()
    app.dependency_overrides[mod.get_billing] = lambda: _FakeBilling()
    app.dependency_overrides[get_current_user] = lambda: TokenData(user_id="x")
    return TestClient(app)


def reset() -> None:
    for limiter in (
        mod._AUTH_FAILURES,
        mod._PER_IP,
        mod._PER_DEVICE,
        mod._PER_DEVICE_WRITE,
        mod._WEBHOOK_FAILURES,
    ):
        limiter._history.clear()
        limiter._blocked_until.clear()


def hdr(token=TOKEN, ip="203.0.113.9"):
    return {"X-Beacon-Token": token, "x-forwarded-for": ip}


results: list[tuple[str, str, bool]] = []


def show(name: str, got: str, ok: bool) -> None:
    results.append((name, got, ok))
    print(f"{'  OK  ' if ok else ' FAIL '} | {name:<44} | {got}")


def main() -> int:
    c = build_client()

    # --- 1. 正規の端末は通る
    reset()
    r = c.get(f"/api/v1/pornblocker/subscription?device_id={DEVICE}", headers=hdr())
    show("正しい合言葉で契約を確かめる", f"{r.status_code} {r.json()}", r.status_code == 200)

    # --- 2. 合言葉が違えば 401
    reset()
    r = c.get(
        f"/api/v1/pornblocker/subscription?device_id={DEVICE}", headers=hdr(token="wrong")
    )
    show("合言葉が違う", str(r.status_code), r.status_code == 401)

    # --- 3. 総当たり: 10 回外したら締め出し
    reset()
    codes = []
    for _ in range(12):
        r = c.get(
            f"/api/v1/pornblocker/subscription?device_id={DEVICE}",
            headers=hdr(token="wrong", ip="192.0.2.11"),
        )
        codes.append(r.status_code)
    show(
        "合言葉の総当たり 12 回",
        f"401 x{codes.count(401)} → 429 x{codes.count(429)}",
        codes[:10] == [401] * 10 and codes[10:] == [429, 429],
    )

    # --- 4. 締め出し中は正しい合言葉でも通らない
    r = c.get(
        f"/api/v1/pornblocker/subscription?device_id={DEVICE}",
        headers=hdr(ip="192.0.2.11"),
    )
    show(
        "締め出し中は正解でも弾く",
        f"{r.status_code} Retry-After={r.headers.get('Retry-After')}",
        r.status_code == 429 and int(r.headers.get("Retry-After", 0)) > 600,
    )

    # --- 5. 別の回線は巻き込まれない
    r = c.get(
        f"/api/v1/pornblocker/subscription?device_id={DEVICE}",
        headers=hdr(ip="192.0.2.12"),
    )
    show("別の回線は巻き込まれない", str(r.status_code), r.status_code == 200)

    # --- 6. 書き込みは 1 分に 10 回
    reset()
    codes = []
    for _ in range(12):
        r = c.post(
            "/api/v1/pornblocker/messages",
            headers=hdr(),
            json={"device_id": DEVICE, "text": "やめたいです"},
        )
        codes.append(r.status_code)
    show(
        "連絡の送信 12 回",
        f"通った {sum(1 for x in codes if x < 400)} / 弾いた {codes.count(429)}",
        codes.count(429) == 2,
    )

    # --- 7. 書き込みを使い切っても読み取りは残る
    r = c.get(f"/api/v1/pornblocker/messages?device_id={DEVICE}", headers=hdr())
    show("使い切っても読み取りは残る", str(r.status_code), r.status_code == 200)

    # --- 8. 端末ごとに数えている（同じ回線の別端末は無事）
    reset()
    for _ in range(11):
        c.post(
            "/api/v1/pornblocker/messages",
            headers=hdr(ip="198.51.100.5"),
            json={"device_id": "device-A", "text": "x"},
        )
    r = c.post(
        "/api/v1/pornblocker/messages",
        headers=hdr(ip="198.51.100.5"),
        json={"device_id": "device-B", "text": "x"},
    )
    show("同じ回線の別端末は無事", str(r.status_code), r.status_code < 400)

    # --- 9. 呼び名の総当たりは回線で止まる
    reset()
    codes = []
    for i in range(305):
        r = c.get(
            f"/api/v1/pornblocker/subscription?device_id=guess-{i}",
            headers=hdr(ip="192.0.2.200"),
        )
        codes.append(r.status_code)
    show(
        "呼び名を変えて 305 回",
        f"通った {codes.count(200)} → 弾いた {codes.count(429)}",
        codes.count(200) == 300 and codes.count(429) == 5,
    )

    # --- 10. 見張りの受け口（beacon）も守られる
    reset()
    r = c.post(
        "/api/v1/pornblocker/beacon",
        headers=hdr(),
        json={"events": [{"device_id": DEVICE, "protected": True, "at": 1}]},
    )
    show("守りの知らせは通る", f"{r.status_code} {r.json()}", r.status_code == 200)

    r = c.post(
        "/api/v1/pornblocker/beacon",
        headers=hdr(token="wrong"),
        json={"events": [{"device_id": DEVICE, "protected": True, "at": 1}]},
    )
    show("合言葉なしの偽の知らせは弾く", str(r.status_code), r.status_code == 401)

    print()
    failed = [n for n, _, ok in results if not ok]
    if failed:
        print(f"FAILED ({len(failed)}): " + ", ".join(failed))
        return 1
    print(f"全 {len(results)} 件 通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
