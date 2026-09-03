# -*- coding: utf-8 -*-
"""【廃止済み 2026-08-24】watch システム（app/services/followups.py の mail watch）に移行した。

この監視は pending_followups の mail watch 行（経費仕訳ルーム, from=taxdr-kim.com）として
dan-core の followup_poller が10分間隔で実行している。タスクスケジューラの
\\DanZeirishiMailWatch は無効化済み。再有効化しないこと（二重検知になる）。
以下は移行前の実装を参考として残す。

税理士(金永哲税理士事務所)からの受信メールだけを監視し、経費仕訳ルームでダンを起こす。

なぜ専用スクリプトなのか:
  dan-core の email_poller は iCloud を既定で巡回しない(自分の複数アドレスを
  同時巡回すると自己ループするため)。かといって iCloud 全体を巡回対象にすると
  楽天/マネーフォワード等のメルマガが大量に流れ込み通知が実質死ぬ。
  → 「この差出人だけ」を見る薄い監視をコア外に置き、新着を pending_followups に
    積んで既存の followup_poller にダンを起こさせる(コア再起動不要)。

ダンは起こされたあと報告と提案までを行い、返信送信はユーザー承認後に限る。
Windows タスクスケジューラから 10 分間隔で叩く想定。
"""
from __future__ import annotations

import email
import imaplib
import json
import re
import sys
from datetime import datetime, timezone
from email.header import decode_header
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import dotenv_values  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "data" / "zeirishi_mail_watch.json"
WATCH_DOMAIN = "taxdr-kim.com"
ROOM_ID = "2c1c50e1-61c4-44eb-99e5-8f78905ab200"   # 経費仕訳ルーム
USER_ID = "2582a188-ff24-4a4f-b989-6063034d90b2"
MAX_PER_RUN = 3           # 一度に起こす上限(取りこぼしは次回に回す)
BODY_LIMIT = 2500


def _decode(value):
    if not value:
        return ""
    out = []
    for s, enc in decode_header(value):
        out.append(s.decode(enc or "utf-8", errors="replace") if isinstance(s, bytes) else s)
    return "".join(out).strip().replace("\r", "")


def _body(msg) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    pass
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                    return re.sub(r"<[^>]+>", "", html)
                except Exception:
                    pass
    else:
        try:
            return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
        except Exception:
            return msg.get_payload() or ""
    return ""


def _trim_quote(text: str) -> str:
    """引用された過去メール(From: 〜)を落として今回の本文だけ残す。"""
    cut = re.split(r"\n\s*From:\s", text, maxsplit=1)[0]
    return cut.strip()


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_note(sender: str, subject: str, date: str, body: str, attachments: list) -> str:
    att = "、".join(attachments) if attachments else "なし"
    return (
        "[税理士メール自動監視] 顧問税理士から新着メールが届いたので検知した。"
        "以下の内容をユーザー(みきさん)に報告し、次に何をすべきかを提案すること。"
        "経緯はこのルームのこれまでのやり取りを踏まえること。"
        "期限が書かれていれば必ず日付を明示する。"
        "ユーザーの承認なしに返信・送信・外部への働きかけをしてはいけない。今回は報告と提案まで。\n"
        f"--- 受信メール ---\n差出人: {sender}\n件名: {subject}\n受信日時: {date}\n添付: {att}\n本文:\n{body}\n--- ここまで ---"
    )


def main(dry_run: bool = False) -> int:
    cfg = dotenv_values(str(ROOT / ".env"))
    addr, pw = cfg.get("ICLOUD_ADDRESS"), cfg.get("ICLOUD_APP_PASSWORD")
    if not addr or not pw:
        print("[watch] ICLOUD credentials missing")
        return 1

    state = _load_state()
    last_uid = int(state.get("last_uid") or 0)

    M = imaplib.IMAP4_SSL("imap.mail.me.com", 993)
    M.login(addr, pw)
    M.select("INBOX", readonly=True)
    typ, data = M.uid("SEARCH", None, "FROM", WATCH_DOMAIN)
    uids = [int(u) for u in (data[0].split() if data and data[0] else [])]
    new_uids = sorted(u for u in uids if u > last_uid)

    # 初回起動時は既読分を掘り起こさない(最新UIDまでを既知として記録するだけ)
    if last_uid == 0:
        state["last_uid"] = max(uids) if uids else 0
        state["initialized_at"] = datetime.now(timezone.utc).isoformat()
        state["address"] = addr
        if not dry_run:
            _save_state(state)
        M.logout()
        print(f"[watch] initialized. baseline uid={state['last_uid']} (no wake)")
        return 0

    fired = 0
    for uid in new_uids[:MAX_PER_RUN]:
        typ, d = M.uid("FETCH", str(uid), "(BODY.PEEK[])")
        if not d or not isinstance(d[0], tuple):
            continue
        msg = email.message_from_bytes(d[0][1])
        sender = _decode(msg.get("From"))
        subject = _decode(msg.get("Subject"))
        date = _decode(msg.get("Date"))
        atts = [_decode(p.get_filename()) for p in (msg.walk() if msg.is_multipart() else []) if p.get_filename()]
        body = _trim_quote(_body(msg))[:BODY_LIMIT]
        note = _build_note(sender, subject, date, body, atts)
        print(f"[watch] new mail uid={uid} subject={subject}")
        if dry_run:
            print(note[:800])
            fired += 1
            continue
        from app.services.followups import schedule_followup
        res = schedule_followup(ROOM_ID, note, 20, user_id=USER_ID)
        print(f"[watch] scheduled={res.get('scheduled')} {res.get('message','')}")
        if not res.get("scheduled"):
            break
        state["last_uid"] = uid
        _save_state(state)
        fired += 1

    if not dry_run and new_uids and fired == 0:
        pass  # 予約に失敗したら state を進めない(次回再挑戦)
    M.logout()
    print(f"[watch] done. new={len(new_uids)} fired={fired} last_uid={state.get('last_uid')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(dry_run="--dry-run" in sys.argv))
