"""
ポルノブロッカー端末の「守りが立っているか」を受け取る型。

端末（Android アプリ）が定期的に、そして状態が変わった瞬間に送ってくる。
送られてくるのは守りの状態だけで、見たサイトや検索語は含まない。
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class GuardFlags(BaseModel):
    """守りを構成する部品ひとつひとつの状態。端末側の Health.State と同じ並び。"""

    # 遮断が成立しているか（見張り・重ね表示・遮断がすべて立っている）
    protected: bool = False
    # 画面の見張り（ユーザー補助）
    guard: bool = False
    # 他アプリの上に表示する許可
    overlay: bool = False
    # サイトの遮断（VPN）
    vpn: bool = False
    # 端末の管理アプリとしての登録（消されないため）
    admin: bool = False
    notifications: bool = False
    # 保護ロック（本人には解除できない状態）
    locked: bool = False
    safe_mode: bool = Field(default=False, alias="safeMode")

    model_config = {"populate_by_name": True}


class BeaconEvent(GuardFlags):
    """端末が送ってくる 1 件。圏外だった分をまとめて送ってくることがある。"""

    device_id: str = Field(alias="deviceId", min_length=1, max_length=128)
    # 端末側の時計（ミリ秒）。ずれることがあるので、受信時刻とは別に持つ。
    at: Optional[int] = None
    app_version: Optional[str] = Field(default=None, alias="appVersion")
    model: Optional[str] = None
    android: Optional[str] = None

    model_config = {"populate_by_name": True}


class BeaconPayload(BaseModel):
    """受け口が受け取る本体。溜まっていた分をまとめて送れるよう配列で受ける。"""

    events: List[BeaconEvent] = Field(default_factory=list, max_length=100)


class BeaconAck(BaseModel):
    accepted: int
    ok: bool = True


class DeviceRow(GuardFlags):
    """運営の一覧に出す 1 台分。"""

    device_id: str
    label: Optional[str] = None
    contact: Optional[str] = None
    first_seen_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    reported_at: Optional[datetime] = None
    app_version: Optional[str] = None
    model: Optional[str] = None
    android: Optional[str] = None

    # 以下は保存しない。一覧を返すときに算出する。
    # 連絡が途絶えているか。端末が消された・電源が切られた・アプリを消された、を拾う。
    silent: bool = False
    minutes_since_seen: Optional[int] = None
    # 運営が手を打つべき状態か（守りが欠けている、または連絡が途絶えている）
    needs_attention: bool = False


class DeviceLabelUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=120)
    contact: Optional[str] = Field(default=None, max_length=200)


class DeviceEventRow(GuardFlags):
    """1 台の履歴。いつ外れて、いつ戻ったか。"""

    id: int
    device_id: str
    received_at: Optional[datetime] = None
    reported_at: Optional[datetime] = None
    app_version: Optional[str] = None


# ================================================================== 課金と連絡


class SubscriptionStatus(BaseModel):
    """端末が「自分の鍵は生きているか」を確かめるための返事。"""

    active: bool = False
    status: str = "none"
    current_period_end: Optional[str] = None


class CheckoutRequest(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    app_version: Optional[str] = None


class CheckoutResponse(BaseModel):
    url: str


class MessageRow(BaseModel):
    """1 通。誰から来たかだけを持つ。名前も連絡先もここには入れない。"""

    sender: str = "user"
    text: str = ""
    created_at: Optional[str] = None


class MessagesResponse(BaseModel):
    messages: List[MessageRow] = []


class MessageIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4000)
    # 鍵がかかっている端末だけが送ってくる申請番号。
    #
    # 【本人に書かせない】
    # 以前は画面に出した番号を本人に書き写してもらっていた。1 文字違えば
    # 解除コードが合わず、本人には理由が分からないまま開かない。
    # 端末が黙って添えれば、書き間違いという失敗の道が消える。
    request_id: Optional[str] = Field(default=None, max_length=32)


class AdminReply(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ThreadRow(BaseModel):
    """運営の一覧に出す 1 行。返事待ちが先頭に来る。"""

    device_id: str
    last_text: str = ""
    last_at: Optional[str] = None
    count: int = 0
    awaiting_reply: bool = False
