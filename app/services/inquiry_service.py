"""
inquiry のビジネスロジック
クライアントHPの問い合わせフォームを保存する。
保存後、届いたことをダンの受け口（inbox）で判断し、知らせる部屋に返信案の送信案カードを出す
（カードの送信ボタンでメール送信）。機械的ないたずら投稿は保存だけして、知らせも返信もしない。
"""
import asyncio
import logging
import re
from typing import List, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# scope → 差出人として名乗る会社/サービス名（返信草案の主体）
SCOPE_SENDER = {
    "paina-contact": "株式会社パイナ",
    "paina-waitlist": "株式会社パイナ",
    "oku-yukadanbou-waitlist": "コンセントで使える床暖房",
    "oku-yukadanbou-survey": "コンセントで使える床暖房",
}
SCOPE_LABEL = {
    "paina-contact": "お問い合わせ",
    "paina-waitlist": "ウェイティングリスト登録",
    "oku-yukadanbou-waitlist": "先行登録",
    "oku-yukadanbou-survey": "アンケート回答",
}
# scope → 登録直後に自動で送る返信（人の承認を待たない）。ドライテストの先行登録など、
# 「受け付けました＋次の導線」を即返したいフォーム用。件名/本文/差出人名/送信アカウント。
SCOPE_AUTO_REPLY = {
    "oku-yukadanbou-waitlist": {
        "from_name": "コンセントで使える床暖房",
        "from_account": "gmail",
        "subject": "先行登録ありがとうございます｜コンセントで使える床暖房",
        "body": (
            "ご登録ありがとうございます。\n\n"
            "「コンセントで使える床暖房」は現在開発中です。発売時期と価格が決まりしだい、"
            "このメールアドレスへいちばん先にお知らせします。\n\n"
            "続報はLINEでもお届けします。まだの方は、こちらから友だち追加をしてお待ちください。\n"
            "https://lin.ee/QY0SmIp\n\n"
            "ご質問は、このメールにそのまま返信してください。\n\n"
            "コンセントで使える床暖房\n"
            "株式会社パイナ"
        ),
    },
}
# scope → 問い合わせ内容をそのまま転送するクライアント側の宛先
SCOPE_FORWARD_TO = {
    "himawari-seitai": ["0aw325171@gmail.com"],  # ひまわり整体院 向井院長
}
SCOPE_CLIENT_NAME = {
    "himawari-seitai": "ひまわり整体院",
}


_RANDOM_WORD = re.compile(r"[A-Za-z]{12,}")


def _random_letters(text: Optional[str]) -> bool:
    """「IXpRheOqzjZWmTRhI」のような、空白のない英字の大小ごちゃ混ぜ（人の名前や文には出ない）。"""
    t = (text or "").strip()
    if not _RANDOM_WORD.fullmatch(t):
        return False
    swaps = sum(1 for a, b in zip(t, t[1:]) if a.isupper() != b.isupper())
    return swaps >= 5


def _dotted_gmail(email: Optional[str]) -> bool:
    """「w.atso.ndan.ie.l.le843@gmail.com」: Gmail は点を無視するので、1つの受信箱を使い回す投稿で多い形。"""
    local, _, domain = (email or "").strip().lower().partition("@")
    return domain in ("gmail.com", "googlemail.com") and local.count(".") >= 3


def looks_like_bot(inquiry: dict) -> bool:
    """機械的ないたずら投稿か。印が2つ以上そろった時だけ（本物の人を落とさないため）。"""
    signs = [
        _random_letters(inquiry.get("name")),
        _random_letters(inquiry.get("message")),
        _random_letters((inquiry.get("company") or "").removesuffix(" LLC")),
        _dotted_gmail(inquiry.get("email")),
    ]
    return sum(signs) >= 2


class InquiryService:
    def __init__(self):
        self.supabase = get_supabase_client().client
        self.table = "inquiries"

    async def create(
        self,
        scope: str,
        name: str,
        message: str,
        email: Optional[str] = None,
        phone: Optional[str] = None,
        company: Optional[str] = None,
        source_url: Optional[str] = None,
        user_agent: Optional[str] = None,
        client_ip: Optional[str] = None,
    ) -> dict:
        row = {
            "scope": scope,
            "name": name,
            "message": message,
            "email": email,
            "phone": phone,
            "company": company,
            "source_url": source_url,
            "user_agent": user_agent,
            "client_ip": client_ip,
        }

        def _insert():
            return self.supabase.table(self.table).insert(row).execute()

        result = await asyncio.to_thread(_insert)
        created = result.data[0] if result.data else row
        logger.info("inquiry created scope=%s name=%s", scope, name)

        if looks_like_bot(created):
            # いたずら投稿: 記録だけ残す。自動返信・返信案・知らせ・転送はしない（相手に届けても得るものがない）
            logger.info("inquiry looks like a bot scope=%s name=%s email=%s", scope, name, email)
            if created.get("id"):
                try:
                    await self.update_status(created["id"], "spam")
                except Exception:
                    logger.warning("inquiry spam mark failed id=%s", created.get("id"), exc_info=True)
            return created

        # 返信草案の生成と知らせはバックグラウンドで（フォーム応答をブロックしない）
        try:
            asyncio.create_task(self._auto_reply(created))
            asyncio.create_task(self._draft_and_propose(created))
            asyncio.create_task(self._forward_to_client(created))
        except RuntimeError:
            # 実行中ループが無い稀なケースは同期フォールバック
            await self._auto_reply(created)
            await self._draft_and_propose(created)
            await self._forward_to_client(created)

        return created

    async def _auto_reply(self, inquiry: dict) -> None:
        """SCOPE_AUTO_REPLY に載っている scope は、登録者へ即時に定型メールを返す（ベストエフォート）。"""
        scope = inquiry.get("scope") or ""
        cfg = SCOPE_AUTO_REPLY.get(scope)
        to = (inquiry.get("email") or "").strip()
        if not cfg or not to:
            return
        if to.endswith("@example.com"):
            logger.info("inquiry auto-reply skipped (test address) scope=%s to=%s", scope, to)
            return
        try:
            from app.services.email_send import send_plain_email

            await asyncio.to_thread(
                send_plain_email,
                to,
                cfg["subject"],
                cfg["body"],
                from_name=cfg.get("from_name", "Done"),
                from_account=cfg.get("from_account", "gmail"),
            )
            logger.info("inquiry auto-reply sent scope=%s to=%s", scope, to)
        except Exception:
            logger.exception("inquiry auto-reply failed scope=%s to=%s", scope, to)

    async def _forward_to_client(self, inquiry: dict) -> None:
        """問い合わせ内容をクライアント本人のメールへ転送する（ベストエフォート）。

        通知タブへの提案とは独立。クライアントが自分の受信箱でも見落とさないための控え。
        """
        scope = inquiry.get("scope") or ""
        recipients = SCOPE_FORWARD_TO.get(scope) or []
        if not recipients:
            return
        try:
            from app.services.email_send import send_plain_email

            client = SCOPE_CLIENT_NAME.get(scope, scope)
            name = inquiry.get("name") or "お名前未記入"
            sender_email = inquiry.get("email")
            reply_note = (
                f"そのまま返信するとお客様（{sender_email}）に直接届きます。"
                if sender_email
                else "お客様のメールアドレスが未記入のため、返信しても届きません。"
            )
            subject = f"【{client}】ホームページからお問い合わせが届きました（{name} 様）"
            body = (
                f"{client}のホームページの問い合わせフォームに、新しいお問い合わせが届きました。\n\n"
                f"お名前: {name}\n"
                f"メール: {sender_email or '-'}\n"
                f"電話: {inquiry.get('phone') or '-'}\n"
                f"受付日時: {inquiry.get('created_at') or '-'}\n\n"
                f"--- お問い合わせ内容 ---\n"
                f"{inquiry.get('message') or '(本文なし)'}\n\n"
                f"※このメールは自動転送です。{reply_note}\n"
            )
            for to in recipients:
                await asyncio.to_thread(
                    send_plain_email,
                    to,
                    subject,
                    body,
                    from_name=f"{client} お問い合わせ通知",
                    reply_to=sender_email or None,
                )
            logger.info("inquiry forwarded scope=%s to=%s", scope, recipients)
        except Exception:
            logger.exception("inquiry forward failed scope=%s", scope)

    async def _draft_and_propose(self, inquiry: dict) -> None:
        """届いたことをダンの受け口で判断し、知らせる部屋に返信案の送信案カードを出す（ベストエフォート）。

        カードは知らせと同じ部屋に、その部屋の送信案（outbound）として作る。そうすれば部屋に表示され、
        部屋から送信・破棄できる（以前は廃止済みの通知欄用に部屋なしで作り、どこにも出なかった。2026-10-16）。
        受け口が無視と判断した時は、カードも作らない。"""
        try:
            from app.services.owner import resolve_owner_user_id

            owner_id = resolve_owner_user_id()
            if not owner_id:
                logger.warning("inquiry draft skipped: owner user_id 未解決")
                return

            scope = inquiry.get("scope") or ""
            name = inquiry.get("name") or "お客様"
            sender_email = (inquiry.get("email") or "").strip()
            company = SCOPE_SENDER.get(scope, "弊社")
            label = SCOPE_LABEL.get(scope, "お問い合わせ")
            subject = f"Re: {label}ありがとうございます（{company}）"

            async def prepare(room_id: str) -> Optional[str]:
                if not sender_email:
                    return "（返信先のメールが未記入なので、メールでは返信できない）"
                summary, draft = await self._generate_draft(inquiry, company, label)
                if not draft:
                    return "（返信案の自動作成に失敗した。返事が要るなら compose_message で作る）"
                from app.services.outbound_message_service import get_outbound_message_service

                card = await asyncio.to_thread(
                    get_outbound_message_service().create_draft,
                    user_id=owner_id, room_id=room_id, channel="email", to=sender_email,
                    to_name=f"{name} 様", subject=subject, body=draft, from_name=company,
                    intent=f"サイトの{label}への返信" + (f"（{summary}）" if summary else ""),
                )
                logger.info("inquiry reply card created scope=%s room=%s card=%s", scope, room_id, card.get("id"))
                return (f"（この部屋に返信案の送信案カード {card.get('id')} を出し済み。重ねて作らない。"
                        "直すなら compose_message で、要らなければ discard）")

            from app.services import inbox   # judged like mail (stage 2)
            asked = (f"{label}\n会社名: {inquiry.get('company') or '-'}\nメール: {sender_email or '-'}\n電話: {inquiry.get('phone') or '-'}\n\n"
                     f"{inquiry.get('message') or '(本文なし)'}")
            await inbox.receive(owner_id, "inquiry", name, asked, subject=f"サイトの問い合わせ（{label}）",
                                source_id=f"inquiry:{inquiry.get('id')}" if inquiry.get("id") else "",
                                metadata={"inquiry_id": inquiry.get("id")}, prepare=prepare)
            logger.info("inquiry received scope=%s", scope)
        except Exception:
            logger.exception("inquiry draft/propose failed")

    async def _generate_draft(self, inquiry: dict, company: str, label: str):
        """run_oneshot_cli で (自然な概要, 返信本文) を生成する。失敗時 (None, None)。"""
        try:
            from app.agent.cli_runner import run_oneshot_cli
            from app.services.external_message_routing import _split_summary_reply, _with_signature
        except Exception:
            logger.warning("run_oneshot_cli をimportできず草案生成をスキップ")
            return None, None

        name = inquiry.get("name") or "お客様"
        msg = inquiry.get("message") or ""
        comp = inquiry.get("company")
        prompt = (
            f"あなたは「{company}」の担当者です。自社サイトの{label}フォームに以下の問い合わせが届きました。\n"
            f"(1)状況の自然な要約 と (2)返信メール本文 を作ってください。\n"
            f"出力は次の形式を厳守し、他の文字を足さないこと:\n"
            f"【概要】<1〜2文の自然な日本語。誰から何の件で何を求めているか。"
            f"例: {name}さんから{label}で、料金についての問い合わせです。>\n"
            f"【返信案】\n"
            f"<丁寧で簡潔な返信本文のみ。宛名は「{name} 様」で始める。件名・マークダウン不要。"
            f"本文末尾に署名・会社名・連絡先を書かないこと（署名はシステムが自動で付ける）。>\n\n"
            f"--- 問い合わせ ---\n"
            f"お名前: {name}\n"
            + (f"会社名: {comp}\n" if comp else "")
            + f"内容: {msg}\n"
        )
        raw = await asyncio.to_thread(run_oneshot_cli, prompt, "sonnet", 90)
        summary, reply = _split_summary_reply(raw)
        return summary, _with_signature(reply)

    async def list(self, scope: Optional[str] = None, limit: int = 100) -> List[dict]:
        def _query():
            q = self.supabase.table(self.table).select("*")
            if scope:
                q = q.eq("scope", scope)
            return q.order("created_at", desc=True).limit(limit).execute()

        result = await asyncio.to_thread(_query)
        return result.data or []

    async def update_status(self, inquiry_id: str, status: str) -> Optional[dict]:
        def _update():
            return (
                self.supabase.table(self.table)
                .update({"status": status})
                .eq("id", inquiry_id)
                .execute()
            )

        result = await asyncio.to_thread(_update)
        return result.data[0] if result.data else None
