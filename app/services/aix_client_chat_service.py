"""
AIX クライアント別チャット。
- 各クライアントごとに独立した会話履歴を保持
- システムプロンプトにクライアント文脈（業種・課題仮説・提供中アセット等）を自動注入
- Claude Sonnet 4.6 を使用、システム部分は prompt caching で再利用

会話履歴は aix_client_chats テーブルに保存。
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

import anthropic

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

MODEL_ID = "claude-sonnet-4-6"
MAX_TOKENS = 2048
HISTORY_LIMIT = 40  # 直近何往復をプロンプトに含めるか


class AixClientChatService:
    def __init__(self):
        self.sb = get_supabase_client().client
        self.table = "aix_client_chats"

    # ── メッセージ取得・保存 ──
    async def list_messages(
        self, user_id: str, client_id: str, limit: int = 200
    ) -> List[Dict[str, Any]]:
        def _q():
            return (
                self.sb.table(self.table)
                .select("*")
                .eq("created_by", user_id)
                .eq("client_id", client_id)
                .order("created_at", desc=False)
                .limit(limit)
                .execute()
            )

        r = await asyncio.to_thread(_q)
        return r.data or []

    async def _save_message(
        self,
        user_id: str,
        client_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        row = {
            "client_id": client_id,
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "created_by": user_id,
        }

        def _i():
            return self.sb.table(self.table).insert(row).execute()

        r = await asyncio.to_thread(_i)
        return r.data[0] if r.data else row

    # ── クライアント文脈組み立て ──
    async def _build_client_context(
        self, user_id: str, client_id: str
    ) -> Dict[str, Any]:
        def _client():
            return (
                self.sb.table("aix_clients")
                .select("*")
                .eq("created_by", user_id)
                .eq("id", client_id)
                .single()
                .execute()
            )

        def _children(table: str):
            return (
                self.sb.table(table)
                .select("*")
                .eq("created_by", user_id)
                .eq("client_id", client_id)
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )

        client_res = await asyncio.to_thread(_client)
        client = client_res.data
        if not client:
            return {}

        hyp, props, eng, tasks, contracts = await asyncio.gather(
            asyncio.to_thread(_children, "aix_hypotheses"),
            asyncio.to_thread(_children, "aix_proposals"),
            asyncio.to_thread(_children, "aix_engagements"),
            asyncio.to_thread(_children, "aix_tasks"),
            asyncio.to_thread(_children, "aix_contracts"),
        )

        return {
            "client": client,
            "hypotheses": hyp.data or [],
            "proposals": props.data or [],
            "engagements": eng.data or [],
            "tasks": tasks.data or [],
            "contracts": contracts.data or [],
        }

    def _format_system_prompt(self, ctx: Dict[str, Any]) -> str:
        c = ctx.get("client", {})
        if not c:
            return "あなたはダンというAIアシスタントです。"

        lines: List[str] = [
            "あなたは「ダン」というAIアシスタントで、AIX事業（AIを活用したDX支援）のクライアント担当として、本田 樹（みき）さんと一緒に仕事を進めています。",
            "",
            f"## 担当クライアント: {c.get('name', '?')}",
            f"- 業種: {c.get('industry') or '未設定'}",
            f"- 地域: {c.get('region') or '未設定'}",
            f"- 規模: {c.get('size') or '未設定'}",
            f"- ステージ: {c.get('stage') or '未設定'}",
            f"- 担当者: {c.get('contact_name') or '未設定'} ({c.get('contact_role') or '?'})",
            f"- 連絡先: TEL {c.get('contact_phone') or '?'} / Mail {c.get('contact_email') or '?'}",
            f"- メモ: {c.get('notes') or '(なし)'}",
        ]

        if ctx.get("hypotheses"):
            lines.append("\n## 課題仮説")
            for h in ctx["hypotheses"][:10]:
                lines.append(f"- [{h.get('status')}] {h.get('title')}: {h.get('pain_point') or ''}")

        if ctx.get("proposals"):
            lines.append("\n## 提案")
            for p in ctx["proposals"][:10]:
                lines.append(f"- [{p.get('status')}] {p.get('title')}: {p.get('summary') or ''}")

        if ctx.get("engagements"):
            lines.append("\n## 運用中の成果物")
            for e in ctx["engagements"][:10]:
                lines.append(f"- {e.get('deliverable_name')} ({e.get('deliverable_url') or '?'})")

        if ctx.get("contracts"):
            lines.append("\n## 契約")
            for k in ctx["contracts"][:5]:
                lines.append(f"- {k.get('title')} 月額 ¥{k.get('monthly_value') or 0}")

        if ctx.get("tasks"):
            open_tasks = [t for t in ctx["tasks"] if t.get("status") not in ("done", "cancelled")][:10]
            if open_tasks:
                lines.append("\n## 進行中タスク")
                for t in open_tasks:
                    lines.append(f"- [{t.get('zone')}/{t.get('status')}] {t.get('title')}")

        lines.extend([
            "",
            "---",
            "## 振る舞い",
            "- 日本語で回答する。返事は簡潔に、必要な情報だけ。",
            "- このクライアント固有の文脈に基づいて回答する。一般論は避ける。",
            "- HPやツールの新規制作の依頼があった場合、構成案・必要素材・想定URLを具体的に提示する。",
            "- 修正依頼の場合、変更箇所と理由を明確にする。",
            "- 承認が必要な実行系タスク（メール送信・公開・契約等）は事前確認を取る。",
        ])

        return "\n".join(lines)

    # ── メッセージ送信（メイン処理） ──
    async def send(
        self, user_id: str, client_id: str, user_message: str
    ) -> Dict[str, Any]:
        # 1. クライアント文脈を取得
        ctx = await self._build_client_context(user_id, client_id)
        if not ctx:
            raise ValueError("client not found")

        system_prompt = self._format_system_prompt(ctx)

        # 2. 過去履歴を取得
        history = await self.list_messages(user_id, client_id, limit=HISTORY_LIMIT)
        msgs: List[Dict[str, Any]] = [
            {"role": h["role"], "content": h["content"]}
            for h in history
            if h["role"] in ("user", "assistant")
        ]
        msgs.append({"role": "user", "content": user_message})

        # 3. ユーザーメッセージを先に保存
        saved_user = await self._save_message(user_id, client_id, "user", user_message)

        # 4. Claude API呼び出し（system は cache対象）
        def _call():
            # SDKに任せる（ANTHROPIC_API_KEY を自動で読む）
            client = anthropic.Anthropic()
            return client.messages.create(
                model=MODEL_ID,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=msgs,
            )

        try:
            res = await asyncio.to_thread(_call)
            assistant_text = "".join(
                block.text for block in res.content if hasattr(block, "text")
            )
        except Exception as e:
            logger.exception("AIX chat AI call failed")
            assistant_text = f"（AIエラー: {e}）"

        # 5. 応答も保存
        saved_assistant = await self._save_message(
            user_id, client_id, "assistant", assistant_text,
            metadata={"model": MODEL_ID},
        )

        return {
            "user_message": saved_user,
            "assistant_message": saved_assistant,
        }
