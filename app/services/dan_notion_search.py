"""ダン用Notion: 自然言語検索 (pgvector + ローカル埋め込みモデル)

API 課金ゼロ で実現するため、sentence-transformers の
multilingual-e5-small (384次元) をローカル実行する。

初回ロード時に約 470MB の重みをダウンロードする。
推論は CPU でも 1テキストあたり 50ms 程度。

依存:
  pip install sentence-transformers torch
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Optional

from app.services.supabase_client import get_supabase_client

logger = logging.getLogger(__name__)

_model = None
_MODEL_NAME = "intfloat/multilingual-e5-small"


def _get_model():
    """モデルを遅延ロード (Celery ワーカー起動時に1回だけ)"""
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(_MODEL_NAME)
            logger.info("loaded embedding model: %s", _MODEL_NAME)
        except ImportError:
            logger.error("sentence-transformers not installed. pip install sentence-transformers")
            raise
    return _model


def _block_to_text(block: dict) -> str:
    """ブロックを検索可能なテキストに正規化"""
    parts = []
    title = block.get("properties", {}).get("title")
    if title:
        parts.append(str(title))
    content = block.get("content")
    if isinstance(content, list):
        for c in content:
            if isinstance(c, dict):
                parts.append(str(c.get("text", "")))
            elif isinstance(c, str):
                parts.append(c)
    elif isinstance(content, str):
        parts.append(content)
    elif isinstance(content, dict):
        parts.append(json.dumps(content, ensure_ascii=False))
    return " ".join(p for p in parts if p).strip()


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def index_block(block_id: str) -> Optional[dict]:
    """単一ブロックの埋め込みを更新"""
    sb = get_supabase_client().client
    res = sb.table("blocks").select("*").eq("id", block_id).limit(1).execute()
    if not res.data:
        return None
    block = res.data[0]
    text = _block_to_text(block)
    if not text:
        return None

    text_hash = _hash(text)
    # 既存の hash と一致するならスキップ
    existing = (
        sb.table("block_embeddings")
        .select("text_hash")
        .eq("block_id", block_id)
        .limit(1)
        .execute()
    )
    if existing.data and existing.data[0]["text_hash"] == text_hash:
        return {"skipped": True}

    model = _get_model()
    # e5 系は "passage: " プレフィックスで埋め込み
    embedding = model.encode(f"passage: {text}", normalize_embeddings=True).tolist()

    summary = text[:200]
    sb.table("block_embeddings").upsert({
        "block_id": block_id,
        "user_id": block["user_id"],
        "embedding": embedding,
        "summary": summary,
        "auto_tags": block.get("tags") or [],
        "auto_category": block.get("type"),
        "model": "multilingual-e5-small",
        "text_hash": text_hash,
    }).execute()

    return {"indexed": True, "summary": summary}


def search(user_id: str, query: str, limit: int = 20) -> list[dict[str, Any]]:
    """自然言語クエリで類似ブロックを検索"""
    model = _get_model()
    query_emb = model.encode(f"query: {query}", normalize_embeddings=True).tolist()

    sb = get_supabase_client().client
    try:
        res = sb.rpc("search_blocks_by_embedding", {
            "p_user_id": user_id,
            "p_query_embedding": query_emb,
            "p_limit": limit,
        }).execute()
        return res.data or []
    except Exception as e:
        logger.warning("vector search failed (RPC), falling back: %s", e)
        return []


def reindex_user(user_id: str) -> dict:
    """指定ユーザーの全ブロックを再インデックス (バックフィル用)"""
    sb = get_supabase_client().client
    blocks = (
        sb.table("blocks")
        .select("id")
        .eq("user_id", user_id)
        .is_("deleted_at", "null")
        .execute()
        .data
        or []
    )
    indexed = 0
    skipped = 0
    for b in blocks:
        result = index_block(b["id"])
        if result and result.get("indexed"):
            indexed += 1
        elif result and result.get("skipped"):
            skipped += 1
    return {"total": len(blocks), "indexed": indexed, "skipped": skipped}
