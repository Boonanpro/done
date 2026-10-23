"""パスワード表示用の端末（パスキー）の登録受付を、PC から開く。

最初の1台を登録する時だけ使う。2台目以降は、登録済みの端末で /vault の
「端末を追加」を押して開ける（その時は本人確認が要る）。

    python scripts/secret_vault_enroll.py            # 端末が0台の時だけ10分開ける
    python scripts/secret_vault_enroll.py --status   # 登録済みの端末と受付の状態
    python scripts/secret_vault_enroll.py --reset    # 端末を全部失くした時だけ。全部外して受付を開ける

受付を開けた・全部外したことは本人のスマホに通知される。
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import secret_vault as vault  # noqa: E402
from app.services.owner import resolve_owner_user_id  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    passkeys = vault.load_passkeys()
    until = vault.enroll_open_until()
    if args.status:
        print(f"登録済みの端末: {len(passkeys)}台")
        for p in passkeys:
            print(f"  - {p.get('label')} ({p.get('rp_id')}) 登録 {p.get('created_at')} 最終使用 {p.get('last_used_at')}")
        print(f"登録受付: {until.isoformat() + ' まで' if until else '閉じています'}")
        return 0

    owner = resolve_owner_user_id()
    if args.reset:
        vault._save_passkeys([])
        vault.log_event("reset", removed=len(passkeys))
        message = f"パスワード表示用の端末{len(passkeys)}台を全部外し、登録受付を開けました"
    elif passkeys:
        print("登録済みの端末があるので開けません。登録済みの端末で /vault の「端末を追加」を押してください。")
        return 1
    else:
        message = "パスワード表示用の端末の登録受付を10分間開けました"

    until = vault.open_enroll_window(opened_by="local-script")
    if owner:
        asyncio.run(vault.notify_owner(owner, message))
    print(f"{message}（{until.astimezone().strftime('%H:%M')} まで）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
