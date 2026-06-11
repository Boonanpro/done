"""ブラウザ代理ログイン型レジストラドライバのレジストリ。

registrar_detect の ``registrar_key`` からドライバを引く。新しいレジストラに対応する時は
ここに1行足す＋ドライバ実装を追加するだけ（接続フロー本体は触らない）。
"""
from __future__ import annotations

from typing import Optional

from app.tools.publish_site.browser_registrars.base import (
    BrowserRegistrarDriver,
    DnsRecord,
    LoginResult,
    launch_registrar_context,
    run_in_proactor_loop,
)


def get_browser_driver(registrar_key: str) -> Optional[BrowserRegistrarDriver]:
    """registrar_key に対応するブラウザドライバを返す（未対応は None）。"""
    if registrar_key == "gmo_onamae":
        from app.tools.publish_site.browser_registrars.onamae import OnamaeDriver

        return OnamaeDriver()
    # TODO: gandi / porkbun / godaddy / muumuu を順次追加
    return None


__all__ = [
    "BrowserRegistrarDriver",
    "DnsRecord",
    "LoginResult",
    "get_browser_driver",
    "launch_registrar_context",
    "run_in_proactor_loop",
]
