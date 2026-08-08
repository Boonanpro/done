"""
ポルノブロッカー端末の「守りが立っているか」の受け口と、運営用の一覧。

【入口は 2 つ】
1. 端末 → `POST /beacon`
   認証は合言葉ひとつ（`PORNBLOCKER_BEACON_TOKEN`）。
   端末にログインを持たせると、ログインが切れた端末から知らせが来なくなる。
   知らせが来なくなることこそ避けたい事態なので、ここは軽くする。

2. 運営 → `GET /devices` ほか
   こちらは普通のログインを要求する。端末の一覧は契約者の情報そのもの。

【合言葉ひとつで守れない分をどう埋めるか】
合言葉は 1 つしかないので、総当たりで当てられる余地が残る。当てられた後も、
端末の呼び名（device_id）を総当たりすれば他人の契約状態や連絡を覗ける。
そこで「短時間に何度も」を回数で塞ぐ（下の 3 つの制限）。
1 回ごとの正しさは合言葉で、繰り返しの悪用は回数で、と分けて受け持つ。
"""
from __future__ import annotations

import secrets
from typing import List

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from app.config import settings
from app.models.pornblocker_guard_beacon_schemas import (
    AdminReply,
    BeaconAck,
    BeaconPayload,
    CheckoutRequest,
    CheckoutResponse,
    DeviceEventRow,
    DeviceLabelUpdate,
    DeviceRow,
    MessageIn,
    MessageRow,
    MessagesResponse,
    SubscriptionStatus,
    ThreadRow,
)
from app.api.chat_routes import TokenData, get_current_user
from app.services.pornblocker_cancellation_service import (
    PornblockerCancellationService,
)
from app.services.pornblocker_guard_beacon_service import (
    PornblockerBillingService,
    PornblockerGuardBeaconService,
)
from app.utils.rate_limit import SlidingWindowLimiter, client_ip

# main.py 側で prefix="/api/v1" を付けて登録する。
router = APIRouter(prefix="/pornblocker", tags=["pornblocker"])


def get_service() -> PornblockerGuardBeaconService:
    return PornblockerGuardBeaconService()


#: 合言葉を間違えた回数（回線ごと）。
#:
#: ここだけ回線で数える。正規の端末は合言葉を間違えないので、
#: 携帯回線のように多数の契約者が同じ IP を共有していても巻き込まない。
#: 5 分に 10 回外したら 15 分締める。総当たりはこれで成立しなくなる。
_AUTH_FAILURES = SlidingWindowLimiter(
    max_requests=10,
    window_seconds=300,
    block_seconds=900,
    detail="認証に繰り返し失敗しました。しばらく待ってからお試しください。",
)

#: 同じ回線からの総量。
#:
#: 合言葉を当てた相手が、端末の呼び名を総当たりしてくる場合に効かせる。
#: 呼び名は端末ごとに違うので、相手ごとの制限では止まらない。
#: ただし携帯回線は IP を共有するため、緩く取る。端末は 30 分に 1 回しか
#: 来ないので、同じ回線に数千台ぶら下がっても正規利用は届かない。
_PER_IP = SlidingWindowLimiter(
    max_requests=300,
    window_seconds=60,
    detail="この回線からの求めが多すぎます。しばらく待ってからお試しください。",
)

#: 端末ごとの通常利用。
#:
#: 端末は 30 分に 1 回来る作りなので、1 分に 60 回は圏外明けのまとめ送信や
#: 再送を含めても届かない。締め出しは付けない。正規の端末が一時的に
#: 混み合っただけで長時間黙らされると、守りの状態が運営に届かなくなる。
_PER_DEVICE = SlidingWindowLimiter(
    max_requests=60,
    window_seconds=60,
    detail="送信が多すぎます。しばらく待ってからお試しください。",
)

#: 書き込みは別枠でさらに絞る。
#:
#: 支払いページの作成と連絡の送信は、人が画面を押して初めて起きる。
#: 1 分に 10 回で足りるし、Stripe のページを大量に作らせる遊びも塞げる。
_PER_DEVICE_WRITE = SlidingWindowLimiter(
    max_requests=10,
    window_seconds=60,
    detail="送信が多すぎます。しばらく待ってからお試しください。",
)


#: Stripe の署名を外した回数（回線ごと）。詳しくは stripe_webhook の説明。
_WEBHOOK_FAILURES = SlidingWindowLimiter(
    max_requests=20,
    window_seconds=300,
    detail="署名の誤りが続いています。しばらく待ってからお試しください。",
)


def _check_token(token: str | None, ip: str) -> None:
    """
    端末からの知らせを受けてよいか。

    合言葉を設定していない状態で開けておくと、誰でも
    「この端末は守られています」と嘘を送れる。それでは見張りにならないので、
    未設定のときは受け口ごと閉じる。うっかり開いたままにしないため。

    突き合わせに compare_digest を使うのは、先頭何文字が合っていたかを
    返答の速さから読まれないようにするため。ふつうの `==` は
    違いが見つかった時点で止まるので、1 文字ずつ当てられる。
    """
    expected = settings.PORNBLOCKER_BEACON_TOKEN
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="受け口が設定されていません（PORNBLOCKER_BEACON_TOKEN 未設定）",
        )
    if not token or not secrets.compare_digest(token, expected):
        _AUTH_FAILURES.hit(ip)
        raise HTTPException(status_code=401, detail="合言葉が違います")


def _guard(
    request: Request,
    token: str | None,
    device_id: str | None = None,
    write: bool = False,
) -> None:
    """
    端末からの求めを通してよいか。合言葉と回数の 2 つで見る。

    順番に意味がある。締め出し中かを**合言葉を見る前に**確かめる。
    後にすると、締め出した相手にも突き合わせを走らせ続けることになる。
    """
    ip = client_ip(request)
    _AUTH_FAILURES.peek(ip)
    _check_token(token, ip)
    _PER_IP.check(ip)
    if device_id:
        _PER_DEVICE.check(device_id)
        if write:
            _PER_DEVICE_WRITE.check(device_id)


@router.post("/beacon", response_model=BeaconAck)
async def receive_beacon(
    payload: BeaconPayload,
    request: Request,
    x_beacon_token: str | None = Header(default=None, alias="X-Beacon-Token"),
    service: PornblockerGuardBeaconService = Depends(get_service),
):
    """
    端末から守りの状態を受け取る。

    圏外だった分をまとめて送ってくることがあるので配列で受ける。
    1 件でも通れば受理にする。ここで弾くと、端末は送り直しを続け、
    壊れた 1 件のせいでその後の知らせが永久に届かなくなる。
    """
    events = [e.model_dump(by_alias=False) for e in payload.events]
    _guard(request, x_beacon_token, events[0]["device_id"] if events else None)
    accepted = await service.ingest(events)

    # 端末は 30 分ごとにここへ来る。ついでに、時間が来た返事を流しておく。
    # チャットを開く前に返事が並んでいる状態にしたい。
    if events:
        try:
            await PornblockerCancellationService().flush_due_replies(events[0]["device_id"])
        except Exception:
            pass
    return BeaconAck(accepted=accepted)


@router.get("/devices", response_model=List[DeviceRow])
async def list_devices(
    current_user: TokenData = Depends(get_current_user),
    service: PornblockerGuardBeaconService = Depends(get_service),
):
    """端末の一覧。手を打つべきものが先頭に来る。"""
    return await service.list_devices()


@router.get("/devices/{device_id}/events", response_model=List[DeviceEventRow])
async def list_device_events(
    device_id: str,
    limit: int = 100,
    current_user: TokenData = Depends(get_current_user),
    service: PornblockerGuardBeaconService = Depends(get_service),
):
    """1 台の履歴。いつ外れて、いつ戻ったかを追う。"""
    return await service.list_events(device_id, limit=min(limit, 500))


@router.patch("/devices/{device_id}", response_model=DeviceRow)
async def update_device_label(
    device_id: str,
    data: DeviceLabelUpdate,
    current_user: TokenData = Depends(get_current_user),
    service: PornblockerGuardBeaconService = Depends(get_service),
):
    """運営が呼び名と連絡先を付ける。誰の端末か分からないと連絡が打てない。"""
    result = await service.update_label(device_id, data.label, data.contact)
    if not result:
        raise HTTPException(status_code=404, detail="その端末は登録されていません")
    return result


# ================================================================== 課金と連絡


def get_billing() -> PornblockerBillingService:
    return PornblockerBillingService()


@router.get("/subscription", response_model=SubscriptionStatus)
async def get_subscription(
    device_id: str,
    request: Request,
    x_beacon_token: str | None = Header(default=None, alias="X-Beacon-Token"),
    billing: PornblockerBillingService = Depends(get_billing),
):
    """
    端末が自分の契約を確かめる。

    ここが落ちているときにアプリが「未契約」と解釈すると、
    こちらの障害で契約者の鍵が外れる。だからアプリ側は
    返事が取れないときに前回の答えを使う作りにしてある（Api.kt）。
    """
    _guard(request, x_beacon_token, device_id)
    return await billing.get_status(device_id)


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    data: CheckoutRequest,
    request: Request,
    x_beacon_token: str | None = Header(default=None, alias="X-Beacon-Token"),
    billing: PornblockerBillingService = Depends(get_billing),
):
    """支払いのページを作る。住所をアプリに埋め込まないので、金額を変えても配り直さずに済む。"""
    _guard(request, x_beacon_token, data.device_id, write=True)
    url = await billing.create_checkout(data.device_id)
    if not url:
        raise HTTPException(status_code=503, detail="支払いの設定がまだありません")
    return CheckoutResponse(url=url)


@router.post("/stripe-webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"),
    billing: PornblockerBillingService = Depends(get_billing),
):
    """
    Stripe からの知らせ。

    署名を必ず確かめる。確かめないと、誰でも「この端末は契約済み」と送れてしまう。
    合言葉の受け口と違い、ここは Stripe しか叩かない場所なので厳しくしてよい。

    署名を外した相手は回数で数える。正規の Stripe は署名を外さないので、
    ここに積み上がるのは攻めている相手だけ。ただし締め出しは付けない。
    こちらの設定ミスで secret がずれたときに、直しても届かない時間が
    続くのを避けるため。
    """
    import stripe

    secret = settings.PORNBLOCKER_STRIPE_WEBHOOK_SECRET
    if not secret:
        raise HTTPException(status_code=503, detail="webhook の合言葉が未設定です")

    ip = client_ip(request)
    _WEBHOOK_FAILURES.peek(ip)

    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, secret)
    except Exception:
        _WEBHOOK_FAILURES.hit(ip)
        raise HTTPException(status_code=400, detail="署名が確かめられません")

    applied = await billing.apply_stripe_event(dict(event))
    return {"applied": applied}


def get_cancellation() -> PornblockerCancellationService:
    return PornblockerCancellationService()


@router.get("/messages", response_model=MessagesResponse)
async def list_messages(
    device_id: str,
    request: Request,
    x_beacon_token: str | None = Header(default=None, alias="X-Beacon-Token"),
    billing: PornblockerBillingService = Depends(get_billing),
    cancellation: PornblockerCancellationService = Depends(get_cancellation),
):
    """
    端末から見るやりとり。

    読みに来たこの瞬間に、時間が来ている返事を流す。
    返事を出すためだけの常駐処理を別に置かない。**置けば必ず止まり、
    止まったことに誰も気付かないまま利用者が待たされる。**
    利用者が見に来た通り道で流すなら、その事故が起きない。
    """
    _guard(request, x_beacon_token, device_id)
    try:
        await cancellation.flush_due_replies(device_id)
    except Exception:
        # 流せなくても、これまでのやりとりは読ませる。
        pass
    rows = await billing.list_messages(device_id)
    return MessagesResponse(messages=[MessageRow(**r) for r in rows])


@router.post("/messages", response_model=MessageRow)
async def post_message(
    data: MessageIn,
    background: BackgroundTasks,
    request: Request,
    x_beacon_token: str | None = Header(default=None, alias="X-Beacon-Token"),
    billing: PornblockerBillingService = Depends(get_billing),
):
    """
    端末から送る。解約の申し出も、誤って止まったサイトの報告も、ここ 1 か所。

    読み取りと課金の停止は**返事を待たせてから**やる。
    ここで待つと、端末側の待ち時間（8 秒）を超えて送信そのものが失敗する。
    やめたいと打った人に「送れませんでした」と出すのが最悪の失敗。
    """
    _guard(request, x_beacon_token, data.device_id, write=True)
    row = await billing.add_message(data.device_id, "user", data.text)

    history = await billing.list_messages(data.device_id)
    background.add_task(
        _handle_incoming, data.device_id, data.text, data.request_id, history
    )
    return MessageRow(**row)


async def _handle_incoming(
    device_id: str, text: str, request_id: str | None, history: list
) -> None:
    try:
        await PornblockerCancellationService().on_user_message(
            device_id, text, request_id=request_id, history=history
        )
    except Exception:
        # ここで落ちても利用者の送信は成立している。
        # 取りこぼしは、申し出から一定時間で自動的に鍵を開ける仕掛けが拾う。
        import logging

        logging.getLogger(__name__).exception("解約の受け付けに失敗: %s", device_id)


@router.get("/cancellation")
async def get_cancellation_state(
    device_id: str,
    current_user: TokenData = Depends(get_current_user),
    cancellation: PornblockerCancellationService = Depends(get_cancellation),
):
    """運営が「いま何合目か」を見る。手を出すためではなく、任せた結果を確かめるため。"""
    return await cancellation.get_state(device_id)


@router.get("/threads", response_model=List[ThreadRow])
async def list_threads(
    current_user: TokenData = Depends(get_current_user),
    billing: PornblockerBillingService = Depends(get_billing),
):
    """運営の一覧。返事をしていないものが先頭に来る。"""
    rows = await billing.list_threads()
    return [ThreadRow(**r) for r in rows]


@router.post("/threads/{device_id}/reply", response_model=MessageRow)
async def reply_to_thread(
    device_id: str,
    data: AdminReply,
    current_user: TokenData = Depends(get_current_user),
    billing: PornblockerBillingService = Depends(get_billing),
):
    """運営から返す。"""
    row = await billing.add_message(device_id, "admin", data.text)
    return MessageRow(**row)
