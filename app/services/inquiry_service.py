"""
inquiry のビジネスロジック
クライアントHPの問い合わせフォームを保存する。
保存後、バックグラウンドでダンが返信草案を生成し、通知タブ(dan_proposals)に
「要対応の返信案」として提案する（承認するとメール送信）。
"""
import asyncio
import logging
from typing import List, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

# scope → 差出人として名乗る会社/サービス名（返信草案の主体）
SCOPE_SENDER = {
    "paina-contact": "株式会社パイナ",
    "paina-waitlist": "株式会社パイナ",
}
SCOPE_LABEL = {
    "paina-contact": "お問い合わせ",
    "paina-waitlist": "ウェイティングリスト登録",
}
# scope → 問い合わせ内容をそのまま転送するクライアント側の宛先
SCOPE_FORWARD_TO = {
    "himawari-seitai": ["0aw325171@gmail.com"],  # ひまわり整体院 向井院長
}
SCOPE_CLIENT_NAME = {
    "himawari-seitai": "ひまわり整体院",
}


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

        # ダンの返信草案生成＋提案作成はバックグラウンドで（フォーム応答をブロックしない）
        try:
            asyncio.create_task(self._draft_and_propose(created))
            asyncio.create_task(self._forward_to_client(created))
        except RuntimeError:
            # 実行中ループが無い稀なケースは同期フォールバック
            await self._draft_and_propose(created)
            await self._forward_to_client(created)

        return created

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
        """問い合わせ内容からダンが返信草案を作り、通知タブに reply 提案を出す（ベストエフォート）。"""
        try:
            from app.services.owner import resolve_owner_user_id

            owner_id = resolve_owner_user_id()
            if not owner_id:
                logger.warning("inquiry draft skipped: owner user_id 未解決")
                return

            scope = inquiry.get("scope") or ""
            name = inquiry.get("name") or "お客様"
            sender_email = inquiry.get("email")
            company = SCOPE_SENDER.get(scope, "弊社")
            label = SCOPE_LABEL.get(scope, "お問い合わせ")
            subject = f"Re: {label}ありがとうございます（{company}）"

            summary, draft = await self._generate_draft(inquiry, company, label)

            has_email = bool(sender_email)
            if has_email and draft:
                ptype = "reply"
                title = "返信しますか？"
                content = draft
                action_data = {
                    "action": "send_inquiry_reply",
                    "channel": "email",
                    "inquiry_id": inquiry.get("id"),
                    "to": sender_email,
                    "subject": subject,
                    "scope": scope,
                    "reply_from_name": company,
                    "summary": summary,
                    "from_sender": f"{name}（{inquiry.get('company') or '個人'}）",
                    "original_body": (inquiry.get("message") or "")[:2000],
                }
            else:
                # 返信先メール無し or 草案生成失敗 → 通知のみ(action)。承認=確認済み扱い。
                ptype = "action"
                title = "対応してください"
                body = inquiry.get("message") or "(本文なし)"
                reason = "返信先メールが未記入のため自動送信不可" if not has_email else "返信草案の生成に失敗"
                content = (
                    f"{label}が届きました（{reason}）。\n\n"
                    f"お名前: {name}\n"
                    f"会社名: {inquiry.get('company') or '-'}\n"
                    f"メール: {sender_email or '-'}\n"
                    f"電話: {inquiry.get('phone') or '-'}\n\n"
                    f"--- 内容 ---\n{body}"
                )
                action_data = {
                    "action": "inquiry_no_reply_channel",
                    "inquiry_id": inquiry.get("id"),
                    "scope": scope,
                }

            def _insert_proposal():
                return self.supabase.table("dan_proposals").insert({
                    "user_id": owner_id,
                    "type": ptype,
                    "title": title,
                    "content": content,
                    "status": "pending",
                    "action_data": action_data,
                }).execute()

            await asyncio.to_thread(_insert_proposal)
            logger.info("inquiry proposal created scope=%s type=%s", scope, ptype)
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
