"""note投稿システムのサービス層

下書き管理、AI清書プロンプト生成、投稿記録を担当。
"""

import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)


class NotePostingService:
    """note投稿の全ライフサイクルを管理"""

    def __init__(self):
        self.supabase = get_supabase_client().client

    # ==================== Drafts ====================

    async def create_draft(
        self,
        user_id: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
    ) -> dict:
        """下書きを作成"""
        draft_id = str(uuid.uuid4())
        result = self.supabase.table("note_drafts").insert({
            "id": draft_id,
            "user_id": user_id,
            "title": title,
            "content": content,
            "tags": json.dumps(tags or []),
            "status": "draft",
        }).execute()

        if not result.data:
            raise ValueError("Failed to create draft")

        row = result.data[0]
        row["tags"] = self._parse_tags(row.get("tags"))
        return row

    async def list_drafts(self, user_id: str) -> list[dict]:
        """ユーザーの下書き一覧を取得"""
        result = (
            self.supabase.table("note_drafts")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            row["tags"] = self._parse_tags(row.get("tags"))
        return rows

    async def get_draft(self, draft_id: str, user_id: str) -> Optional[dict]:
        """下書きを取得"""
        result = (
            self.supabase.table("note_drafts")
            .select("*")
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        row["tags"] = self._parse_tags(row.get("tags"))
        return row

    async def update_draft(
        self,
        draft_id: str,
        user_id: str,
        **updates,
    ) -> Optional[dict]:
        """下書きを更新"""
        if "tags" in updates and updates["tags"] is not None:
            updates["tags"] = json.dumps(updates["tags"])
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Remove None values
        updates = {k: v for k, v in updates.items() if v is not None}

        if not updates or (len(updates) == 1 and "updated_at" in updates):
            return None

        result = (
            self.supabase.table("note_drafts")
            .update(updates)
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        row["tags"] = self._parse_tags(row.get("tags"))
        return row

    async def delete_draft(self, draft_id: str, user_id: str) -> bool:
        """下書きを削除"""
        result = (
            self.supabase.table("note_drafts")
            .delete()
            .eq("id", draft_id)
            .eq("user_id", user_id)
            .execute()
        )
        return bool(result.data)

    # ==================== Polish ====================

    def get_polish_prompt(
        self,
        title: str,
        content: str,
        article_type: str = "free",
        price: int | None = None,
    ) -> str:
        """AI清書用のプロンプトを生成

        Args:
            title: 下書きのタイトル
            content: 下書きの本文
            article_type: "free"（無料記事）or "paid"（有料記事）
            price: 有料記事の場合の価格（円）
        """
        if article_type == "paid":
            return self._get_paid_article_prompt(title, content, price or 1500)
        return self._get_free_article_prompt(title, content)

    def _get_free_article_prompt(self, title: str, content: str) -> str:
        """無料記事用の清書プロンプト（フォロワー獲得・ブランディング向け）"""
        return f"""あなたはnoteで月30万円稼ぐプロのライターです。
以下の下書きを、noteのSEOとスキ数を最大化する記事に清書してください。

## 構成ルール（この順番で書く）

1. **フック（冒頭3行）**: 読者が「自分に関係ある」と感じる問いかけ or 衝撃の事実。数字を1つ入れる
2. **共感パート（2-3段落）**: 「こんな経験ありませんか？」で読者の悩みを代弁
3. **本論（3-5セクション）**: 見出し付きで具体的な解決策。各セクションに1つ以上の具体例・数字
4. **まとめ**: 「今日からできる」アクション1つに絞る
5. **CTA**: フォロー・スキを促す自然な一文（押しつけがましくない）

## 文体ルール
- 「ですます調」で統一
- 一文は50文字以内（読みやすさ最優先）
- 段落は3文以内
- 段落間に空行を入れる
- 重要なポイントは**太字**
- 見出しは##を使用（3-5個）
- リスト・箇条書きを積極活用
- 「〜と思います」「〜かもしれません」は使わない。言い切る

## SEOルール
- タイトルは検索されやすいキーワードを含める
- タイトルに数字を入れる（「3つの方法」「5分で」等）
- タグはnote内で検索されやすいものを5つ選ぶ

## 下書き

タイトル: {title}

本文:
{content}

## 出力形式

以下のJSON形式で出力してください（他の文字は一切出力しないこと）:

```json
{{
  "title": "清書後のタイトル（30文字以内、数字を含め、好奇心を刺激する）",
  "hook": "導入部分（最初の3行のみ）",
  "summary": "記事の要約（1文、50文字以内）",
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"],
  "full_text": "清書後の本文全体（Markdown形式、フックからCTAまで全て含む）"
}}
```"""

    def _get_paid_article_prompt(self, title: str, content: str, price: int) -> str:
        """有料記事用の清書プロンプト（購入を促す構成）"""
        return f"""あなたはnoteで月30万円稼ぐプロのライターです。
以下の下書きを、{price}円の有料記事として最大限売れる構成に清書してください。

## 有料記事の構成ルール

noteの有料記事は「ここから先は有料」の境界線があります。
無料部分で「続きを読みたい」と強く思わせ、有料部分で期待以上の価値を提供する構造にしてください。

### 無料パート（全体の30-40%）
1. **フック（冒頭3行）**: 衝撃的な数字 or 成果を示す。「〜した結果、〇〇になりました」
2. **問題提起**: 読者が感じている痛み・悩みを具体的に描写
3. **解決策の概要**: 「この記事では〇〇を解説します」と要約。何が得られるか明示
4. **チラ見せ**: 本論の1つ目だけ無料で見せる（「これだけでも価値がある」と思わせる）
5. **有料パートへの橋渡し**: 「ここからは、さらに深い内容をお届けします」

### 有料パート（全体の60-70%）
6. **本論の核心**: 最も価値のあるノウハウ・データ・手順を詳細に
7. **具体的な手順**: ステップバイステップで再現可能な内容
8. **テンプレート・チェックリスト**: すぐ使える実用ツール
9. **まとめ+次のアクション**: 読者が今すぐ始められる具体的なステップ

## 文体ルール
- 「ですます調」で統一
- 一文は50文字以内
- 段落は3文以内
- **太字**と見出し（##）を効果的に使用
- 有料部分は無料部分より情報密度を高くする
- {price}円の価値を感じさせる深さと具体性

## 下書き

タイトル: {title}

本文:
{content}

## 出力形式

以下のJSON形式で出力してください（他の文字は一切出力しないこと）:

```json
{{
  "title": "清書後のタイトル（30文字以内、成果・数字を含める）",
  "hook": "導入部分（最初の3行のみ）",
  "summary": "記事の要約（1文、50文字以内）",
  "tags": ["タグ1", "タグ2", "タグ3", "タグ4", "タグ5"],
  "free_part": "無料パート全体（Markdown形式）",
  "paid_part": "有料パート全体（Markdown形式）",
  "full_text": "無料パート + 区切り線(---) + 有料パート の結合テキスト（Markdown形式）"
}}
```"""

    async def save_polished(
        self,
        draft_id: str,
        user_id: str,
        title: str,
        full_text: str,
        tags: list[str] | None = None,
        hook: str | None = None,
        summary: str | None = None,
    ) -> dict:
        """清書結果を保存"""
        # 既存の清書があれば削除（最新のみ保持）
        self.supabase.table("note_polished").delete().eq(
            "draft_id", draft_id
        ).eq("user_id", user_id).execute()

        polished_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        result = self.supabase.table("note_polished").insert({
            "id": polished_id,
            "draft_id": draft_id,
            "user_id": user_id,
            "title": title,
            "tags": json.dumps(tags or []),
            "full_text": full_text,
            "hook": hook,
            "summary": summary,
            "status": "polished",
            "polished_at": now,
        }).execute()

        if not result.data:
            raise ValueError("Failed to save polished content")

        # 下書きのステータスを更新
        self.supabase.table("note_drafts").update({
            "status": "polished",
            "updated_at": now,
        }).eq("id", draft_id).eq("user_id", user_id).execute()

        row = result.data[0]
        row["tags"] = self._parse_tags(row.get("tags"))
        return row

    async def get_polished(self, draft_id: str, user_id: str) -> Optional[dict]:
        """清書結果を取得"""
        result = (
            self.supabase.table("note_polished")
            .select("*")
            .eq("draft_id", draft_id)
            .eq("user_id", user_id)
            .order("polished_at", desc=True)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        row = result.data[0]
        row["tags"] = self._parse_tags(row.get("tags"))
        return row

    async def execute_polish(
        self,
        draft_id: str,
        user_id: str,
        article_type: str = "free",
        price: int | None = None,
    ) -> dict:
        """AI清書を実行（Claude APIで清書）

        Args:
            draft_id: 下書きID
            user_id: ユーザーID
            article_type: "free" or "paid"
            price: 有料記事の場合の価格（円）
        """
        import anthropic

        # 下書きを取得
        draft = await self.get_draft(draft_id, user_id)
        if not draft:
            raise ValueError("Draft not found")

        # プロンプト生成
        prompt = self.get_polish_prompt(
            draft["title"], draft["content"], article_type, price
        )

        # Claude APIで清書
        client = anthropic.Anthropic()
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": prompt}],
        )

        # レスポンスからJSONを抽出
        response_text = message.content[0].text
        polished_data = self._extract_json(response_text)

        if not polished_data:
            raise ValueError("Failed to parse AI response as JSON")

        # 保存
        result = await self.save_polished(
            draft_id=draft_id,
            user_id=user_id,
            title=polished_data.get("title", draft["title"]),
            full_text=polished_data.get("full_text", ""),
            tags=polished_data.get("tags", []),
            hook=polished_data.get("hook"),
            summary=polished_data.get("summary"),
        )

        return result

    # ==================== Posts ====================

    async def record_post(
        self,
        draft_id: str,
        user_id: str,
        note_url: str,
        published: bool = False,
    ) -> dict:
        """投稿記録を保存"""
        # 下書きのタイトルを取得
        draft = await self.get_draft(draft_id, user_id)
        title = draft["title"] if draft else "Untitled"

        post_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        status = "published" if published else "draft_on_note"

        result = self.supabase.table("note_posts").insert({
            "id": post_id,
            "draft_id": draft_id,
            "user_id": user_id,
            "note_url": note_url,
            "title": title,
            "published": published,
            "status": status,
            "posted_at": now,
        }).execute()

        if not result.data:
            raise ValueError("Failed to record post")

        # 下書きのステータスを更新
        new_status = "published" if published else "posted"
        self.supabase.table("note_drafts").update({
            "status": new_status,
            "updated_at": now,
        }).eq("id", draft_id).eq("user_id", user_id).execute()

        return result.data[0]

    async def list_posts(self, user_id: str) -> list[dict]:
        """投稿一覧を取得"""
        result = (
            self.supabase.table("note_posts")
            .select("*")
            .eq("user_id", user_id)
            .order("posted_at", desc=True)
            .execute()
        )
        return result.data or []

    # ==================== Stats ====================

    async def get_stats(self, user_id: str) -> dict:
        """統計情報を取得"""
        # 全下書き
        drafts_result = (
            self.supabase.table("note_drafts")
            .select("id, status")
            .eq("user_id", user_id)
            .execute()
        )
        drafts = drafts_result.data or []

        # 全投稿
        posts_result = (
            self.supabase.table("note_posts")
            .select("id, status, published")
            .eq("user_id", user_id)
            .execute()
        )
        posts = posts_result.data or []

        # スケジュール
        schedules_result = (
            self.supabase.table("note_schedules")
            .select("id, status")
            .eq("user_id", user_id)
            .execute()
        )
        schedules = schedules_result.data or []

        total_drafts = len(drafts)
        pending_drafts = sum(1 for d in drafts if d["status"] == "draft")
        polished_drafts = sum(1 for d in drafts if d["status"] == "polished")
        total_posts = len(posts)
        published = sum(1 for p in posts if p.get("published", False))
        draft_on_note = sum(1 for p in posts if p.get("status") == "draft_on_note")
        scheduled = sum(1 for s in schedules if s.get("status") == "scheduled")

        return {
            "total_drafts": total_drafts,
            "total_posts": total_posts,
            "published": published,
            "draft_on_note": draft_on_note,
            "pending_drafts": pending_drafts,
            "polished_drafts": polished_drafts,
            "scheduled": scheduled,
        }

    # ==================== Schedules ====================

    async def create_schedule(
        self,
        draft_id: str,
        user_id: str,
        scheduled_at: str,
        article_type: str = "free",
        price: int | None = None,
    ) -> dict:
        """投稿スケジュールを作成"""
        # 下書きの存在確認
        draft = await self.get_draft(draft_id, user_id)
        if not draft:
            raise ValueError("Draft not found")

        schedule_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc).isoformat()

        data = {
            "id": schedule_id,
            "draft_id": draft_id,
            "user_id": user_id,
            "scheduled_at": scheduled_at,
            "status": "scheduled",
            "article_type": article_type,
            "created_at": now,
            "updated_at": now,
        }
        if price is not None:
            data["price"] = price

        result = self.supabase.table("note_schedules").insert(data).execute()

        if not result.data:
            raise ValueError("Failed to create schedule")

        row = result.data[0]
        row["draft_title"] = draft["title"]
        return row

    async def list_schedules(self, user_id: str) -> list[dict]:
        """ユーザーのスケジュール一覧を取得"""
        result = (
            self.supabase.table("note_schedules")
            .select("*")
            .eq("user_id", user_id)
            .order("scheduled_at", desc=False)
            .execute()
        )
        rows = result.data or []

        # 下書きタイトルを付与
        draft_ids = list({r["draft_id"] for r in rows})
        if draft_ids:
            drafts_result = (
                self.supabase.table("note_drafts")
                .select("id, title")
                .in_("id", draft_ids)
                .execute()
            )
            title_map = {d["id"]: d["title"] for d in (drafts_result.data or [])}
            for row in rows:
                row["draft_title"] = title_map.get(row["draft_id"])

        return rows

    async def get_schedule(self, schedule_id: str, user_id: str) -> Optional[dict]:
        """スケジュールを取得"""
        result = (
            self.supabase.table("note_schedules")
            .select("*")
            .eq("id", schedule_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return None

        row = result.data[0]
        draft = await self.get_draft(row["draft_id"], user_id)
        row["draft_title"] = draft["title"] if draft else None
        return row

    async def update_schedule(
        self,
        schedule_id: str,
        user_id: str,
        **updates,
    ) -> Optional[dict]:
        """スケジュールを更新（scheduled状態のみ）"""
        # 現在のスケジュールを取得
        current = await self.get_schedule(schedule_id, user_id)
        if not current:
            return None
        if current["status"] != "scheduled":
            raise ValueError(f"Cannot update schedule in '{current['status']}' status")

        updates = {k: v for k, v in updates.items() if v is not None}
        if not updates:
            return current

        updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        result = (
            self.supabase.table("note_schedules")
            .update(updates)
            .eq("id", schedule_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return None

        row = result.data[0]
        row["draft_title"] = current.get("draft_title")
        return row

    async def cancel_schedule(self, schedule_id: str, user_id: str) -> Optional[dict]:
        """スケジュールをキャンセル"""
        current = await self.get_schedule(schedule_id, user_id)
        if not current:
            return None
        if current["status"] not in ("scheduled", "failed"):
            raise ValueError(f"Cannot cancel schedule in '{current['status']}' status")

        now = datetime.now(timezone.utc).isoformat()
        result = (
            self.supabase.table("note_schedules")
            .update({"status": "cancelled", "updated_at": now})
            .eq("id", schedule_id)
            .eq("user_id", user_id)
            .execute()
        )
        if not result.data:
            return None

        row = result.data[0]
        row["draft_title"] = current.get("draft_title")
        return row

    async def get_due_schedules(self) -> list[dict]:
        """実行すべきスケジュールを取得（ワーカー用）

        scheduled_atが現在時刻以前で、statusがscheduledのものを取得。
        """
        now = datetime.now(timezone.utc).isoformat()
        result = (
            self.supabase.table("note_schedules")
            .select("*, note_drafts(title)")
            .eq("status", "scheduled")
            .lte("scheduled_at", now)
            .order("scheduled_at", desc=False)
            .execute()
        )
        rows = result.data or []
        for row in rows:
            draft_data = row.pop("note_drafts", None)
            row["draft_title"] = draft_data["title"] if draft_data else None
        return rows

    async def mark_schedule_publishing(self, schedule_id: str) -> None:
        """スケジュールを投稿中に更新"""
        self.supabase.table("note_schedules").update({
            "status": "publishing",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", schedule_id).execute()

    async def mark_schedule_published(
        self, schedule_id: str, published_url: str
    ) -> None:
        """スケジュールを投稿完了に更新"""
        self.supabase.table("note_schedules").update({
            "status": "published",
            "published_url": published_url,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", schedule_id).execute()

    async def mark_schedule_failed(
        self, schedule_id: str, error_message: str
    ) -> None:
        """スケジュールを失敗に更新"""
        self.supabase.table("note_schedules").update({
            "status": "failed",
            "error_message": error_message,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", schedule_id).execute()

    # ==================== Helpers ====================

    @staticmethod
    def _parse_tags(tags_value) -> list[str]:
        """tagsフィールドをlist[str]に変換"""
        if tags_value is None:
            return []
        if isinstance(tags_value, list):
            return tags_value
        if isinstance(tags_value, str):
            try:
                parsed = json.loads(tags_value)
                return parsed if isinstance(parsed, list) else []
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    @staticmethod
    def _extract_json(text: str) -> Optional[dict]:
        """テキストからJSON部分を抽出"""
        import re

        # ```json ... ``` ブロックを探す
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # { ... } を直接探す
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        return None
