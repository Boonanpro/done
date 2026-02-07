"""
ディープリサーチ - 6フェーズ調査パイプライン

Phase 1: SCOPE - クエリ分解・仮説生成
Phase 2: RETRIEVE - 検索 + ページ読み込み
Phase 3: TRIANGULATE - ソース検証・裏取り
Phase 4: SYNTHESIZE - 情報統合・レポート生成
Phase 5: CRITIQUE - 自己評価
Phase 6: REFINE - 追加調査（必要な場合のみ）
"""

import logging
import asyncio
import json
from typing import Dict, Any, List, Optional

import anthropic

from app.config import settings
from app.tools.source_evaluator import evaluate_source
from app.tools.jina_reader import read_url

logger = logging.getLogger(__name__)

# ディープリサーチ用モデル（本体Haikuとは別にSonnetを使用）
RESEARCH_MODEL = "claude-sonnet-4-5-20250929"

# バジェット制限
MAX_SEARCH_CALLS = 20
MAX_PAGE_READS = 10


async def _call_sonnet(
    system: str,
    prompt: str,
    max_tokens: int = 4000,
    use_web_search: bool = False,
) -> str:
    """
    Sonnetを呼び出す（web_searchオプション付き）

    Args:
        system: システムプロンプト
        prompt: ユーザープロンプト
        max_tokens: 最大トークン数
        use_web_search: web_searchツールを使用するか

    Returns:
        テキストレスポンス
    """
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    kwargs = {
        "model": RESEARCH_MODEL,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt}],
    }

    if use_web_search:
        kwargs["tools"] = [{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
            "user_location": {
                "type": "approximate",
                "country": "JP",
                "timezone": "Asia/Tokyo",
            },
        }]

    response = await client.messages.create(**kwargs)

    # テキスト部分を抽出
    text_parts = []
    for block in response.content:
        if hasattr(block, 'type') and block.type == "text":
            text_parts.append(block.text)

    return "\n".join(text_parts)


async def _call_sonnet_with_search(
    system: str,
    prompt: str,
    max_tokens: int = 4000,
) -> Dict[str, Any]:
    """
    Sonnet + web_searchで検索を実行し、テキストとソースURLを返す

    Returns:
        {"text": "...", "urls": ["url1", "url2", ...]}
    """
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = await client.messages.create(
        model=RESEARCH_MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": prompt}],
        tools=[{
            "type": "web_search_20250305",
            "name": "web_search",
            "max_uses": 5,
            "user_location": {
                "type": "approximate",
                "country": "JP",
                "timezone": "Asia/Tokyo",
            },
        }],
    )

    text_parts = []
    urls = []

    for block in response.content:
        if not hasattr(block, 'type'):
            continue
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "web_search_tool_result":
            # 検索結果からURLを抽出
            if hasattr(block, 'content') and isinstance(block.content, list):
                for item in block.content:
                    if hasattr(item, 'url') and item.url:
                        urls.append(item.url)
                    elif isinstance(item, dict) and item.get('url'):
                        urls.append(item['url'])

    return {
        "text": "\n".join(text_parts),
        "urls": list(dict.fromkeys(urls)),  # deduplicate while preserving order
    }


# ============================================
# Phase 1: SCOPE
# ============================================

async def _phase_scope(query: str, context: str = "") -> Dict[str, Any]:
    """クエリを分解し、サブクエリと仮説を生成"""
    logger.info(f"[DEEP_RESEARCH] Phase 1: SCOPE - {query}")

    system = """あなたはリサーチアナリストです。
ユーザーの調査テーマを分析し、効果的な調査計画を立てます。

以下のJSON形式で出力してください（JSONのみ、説明文不要）:
{
    "sub_queries": ["サブクエリ1", "サブクエリ2", ...],
    "hypotheses": ["仮説1", "仮説2", ...],
    "key_aspects": ["調査すべき観点1", "観点2", ...]
}

サブクエリは3-5個、仮説は2-3個、観点は2-4個にしてください。
検索エンジンで使えるような具体的なサブクエリにしてください。"""

    prompt = f"調査テーマ: {query}"
    if context:
        prompt += f"\n補足情報: {context}"

    text = await _call_sonnet(system, prompt, max_tokens=1000)

    # JSONをパース
    try:
        # ```json ... ``` の中身を抽出
        json_match = text
        if "```json" in text:
            json_match = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            json_match = text.split("```")[1].split("```")[0]

        result = json.loads(json_match.strip())
        return {
            "sub_queries": result.get("sub_queries", [query]),
            "hypotheses": result.get("hypotheses", []),
            "key_aspects": result.get("key_aspects", []),
        }
    except (json.JSONDecodeError, IndexError):
        logger.warning("[DEEP_RESEARCH] Failed to parse scope JSON, using fallback")
        return {
            "sub_queries": [query],
            "hypotheses": [],
            "key_aspects": [],
        }


# ============================================
# Phase 2: RETRIEVE
# ============================================

async def _phase_retrieve(
    sub_queries: List[str],
    original_query: str,
) -> Dict[str, Any]:
    """サブクエリで検索し、上位結果のURLを読み込む"""
    logger.info(f"[DEEP_RESEARCH] Phase 2: RETRIEVE - {len(sub_queries)} sub-queries")

    all_urls = []
    search_texts = []

    # 各サブクエリで検索（並列実行）
    system = f"""あなたはリサーチアシスタントです。
以下の調査テーマについてWeb検索し、見つかった情報を箇条書きで要約してください。
情報の出典URLも必ず記載してください。

調査テーマ: {original_query}"""

    async def search_one(sub_query: str) -> Dict[str, Any]:
        try:
            result = await _call_sonnet_with_search(
                system=system,
                prompt=f"以下について検索してください: {sub_query}",
                max_tokens=2000,
            )
            return result
        except Exception as e:
            logger.warning(f"[DEEP_RESEARCH] Search failed for '{sub_query}': {e}")
            return {"text": "", "urls": []}

    # 並列実行（最大5同時）
    semaphore = asyncio.Semaphore(5)

    async def search_with_limit(sq):
        async with semaphore:
            return await search_one(sq)

    results = await asyncio.gather(*[search_with_limit(sq) for sq in sub_queries])

    for result in results:
        search_texts.append(result["text"])
        all_urls.extend(result["urls"])

    # URLを重複排除
    unique_urls = list(dict.fromkeys(all_urls))

    # 上位URLをJina Readerで全文取得（最大MAX_PAGE_READS）
    page_contents = []
    urls_to_read = unique_urls[:MAX_PAGE_READS]

    async def read_one(url: str) -> Optional[Dict[str, Any]]:
        try:
            result = await read_url(url, timeout=20)
            if result.get("success"):
                content = result.get("content", "")
                # 長すぎるページは切り詰め
                if len(content) > 5000:
                    content = content[:5000]
                return {
                    "url": url,
                    "content": content,
                    "success": True,
                }
            return None
        except Exception as e:
            logger.debug(f"[DEEP_RESEARCH] Failed to read {url}: {e}")
            return None

    # 並列読み込み（最大3同時）
    read_semaphore = asyncio.Semaphore(3)

    async def read_with_limit(url):
        async with read_semaphore:
            return await read_one(url)

    read_results = await asyncio.gather(*[read_with_limit(u) for u in urls_to_read])
    page_contents = [r for r in read_results if r is not None]

    logger.info(
        f"[DEEP_RESEARCH] Retrieved: {len(search_texts)} search results, "
        f"{len(page_contents)} pages read"
    )

    return {
        "search_texts": search_texts,
        "page_contents": page_contents,
        "urls": unique_urls,
    }


# ============================================
# Phase 3: TRIANGULATE
# ============================================

def _phase_triangulate(
    page_contents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """ソースの信頼性を評価し、低品質ソースを除外"""
    logger.info(f"[DEEP_RESEARCH] Phase 3: TRIANGULATE - {len(page_contents)} sources")

    evaluated_sources = []
    filtered_sources = []

    for page in page_contents:
        url = page.get("url", "")
        content = page.get("content", "")

        evaluation = evaluate_source(url, content)
        source = {
            **page,
            "trust_score": evaluation["score"],
            "trust_level": evaluation["trust_level"],
            "trust_details": evaluation["details"],
        }
        evaluated_sources.append(source)

        # スコア60未満を除外
        if evaluation["score"] >= 60:
            filtered_sources.append(source)

    removed_count = len(evaluated_sources) - len(filtered_sources)
    if removed_count > 0:
        logger.info(f"[DEEP_RESEARCH] Filtered out {removed_count} low-quality sources")

    return {
        "evaluated_sources": evaluated_sources,
        "filtered_sources": filtered_sources,
    }


# ============================================
# Phase 4: SYNTHESIZE
# ============================================

async def _phase_synthesize(
    query: str,
    hypotheses: List[str],
    search_texts: List[str],
    filtered_sources: List[Dict[str, Any]],
) -> str:
    """検証済み情報を統合してレポートを生成"""
    logger.info("[DEEP_RESEARCH] Phase 4: SYNTHESIZE")

    # ソース情報をテキストにまとめる
    source_summaries = []
    for i, source in enumerate(filtered_sources, 1):
        source_summaries.append(
            f"### ソース{i}: {source['url']} (信頼度: {source['trust_score']}/100)\n"
            f"{source['content'][:2000]}"
        )

    sources_text = "\n\n".join(source_summaries) if source_summaries else "ソースなし"

    search_summary = "\n\n---\n\n".join(search_texts) if search_texts else "検索結果なし"

    hypotheses_text = ""
    if hypotheses:
        hypotheses_text = "\n\n仮説:\n" + "\n".join(f"- {h}" for h in hypotheses)

    system = """あなたはリサーチアナリストです。
複数のソースから得た情報を統合し、構造化された調査レポートを作成します。

レポートの要件:
- Markdown形式
- 主要な発見・結論を最初に
- 各主張にはソースURLを引用
- 仮説がある場合、それぞれについて確認/棄却を判定
- 矛盾する情報がある場合は明示
- 客観的・中立的な記述"""

    prompt = f"""## 調査テーマ
{query}
{hypotheses_text}

## 検索結果の要約
{search_summary}

## 詳細ソース
{sources_text}

上記の情報を統合して、調査レポートを作成してください。"""

    report = await _call_sonnet(system, prompt, max_tokens=4000)
    return report


# ============================================
# Phase 5: CRITIQUE
# ============================================

async def _phase_critique(query: str, report: str) -> Dict[str, Any]:
    """レポートの弱点を自己評価"""
    logger.info("[DEEP_RESEARCH] Phase 5: CRITIQUE")

    system = """あなたはリサーチレビュアーです。
調査レポートの品質を評価し、弱点や改善点を指摘します。

以下のJSON形式で出力してください（JSONのみ、説明文不要）:
{
    "quality_score": 1-10の品質スコア,
    "strengths": ["強み1", "強み2"],
    "weaknesses": ["弱み1", "弱み2"],
    "unanswered_questions": ["未回答の疑問1", "未回答の疑問2"],
    "needs_additional_research": true/false,
    "additional_queries": ["追加検索クエリ1"]
}"""

    prompt = f"""## 調査テーマ
{query}

## レポート
{report}

このレポートを批判的に評価してください。"""

    text = await _call_sonnet(system, prompt, max_tokens=1000)

    try:
        json_match = text
        if "```json" in text:
            json_match = text.split("```json")[1].split("```")[0]
        elif "```" in text:
            json_match = text.split("```")[1].split("```")[0]

        result = json.loads(json_match.strip())
        return result
    except (json.JSONDecodeError, IndexError):
        logger.warning("[DEEP_RESEARCH] Failed to parse critique JSON")
        return {
            "quality_score": 7,
            "strengths": [],
            "weaknesses": [],
            "unanswered_questions": [],
            "needs_additional_research": False,
            "additional_queries": [],
        }


# ============================================
# Phase 6: REFINE（条件付き）
# ============================================

async def _phase_refine(
    query: str,
    original_report: str,
    critique: Dict[str, Any],
) -> str:
    """追加検索→レポート改善"""
    logger.info("[DEEP_RESEARCH] Phase 6: REFINE")

    additional_queries = critique.get("additional_queries", [])
    unanswered = critique.get("unanswered_questions", [])

    if not additional_queries and unanswered:
        additional_queries = unanswered[:2]

    if not additional_queries:
        return original_report

    # 追加検索
    system = f"""あなたはリサーチアシスタントです。
以下の調査レポートの不足を補うためにWeb検索し、追加情報を提供してください。

元の調査テーマ: {query}"""

    search_prompt = "以下の疑問について追加検索してください:\n" + "\n".join(
        f"- {q}" for q in additional_queries[:3]
    )

    additional_result = await _call_sonnet_with_search(
        system=system,
        prompt=search_prompt,
        max_tokens=2000,
    )

    # レポートを改善
    refine_system = """あなたはリサーチアナリストです。
既存のレポートに追加情報を統合して、改善版を出力してください。
構造は維持しつつ、不足部分を補完してください。"""

    refine_prompt = f"""## 元のレポート
{original_report}

## 追加情報
{additional_result['text']}

## 指摘された弱点
{json.dumps(critique.get('weaknesses', []), ensure_ascii=False)}

レポートを改善してください。"""

    refined_report = await _call_sonnet(refine_system, refine_prompt, max_tokens=4000)
    return refined_report


# ============================================
# メインエントリポイント
# ============================================

async def run_deep_research(
    query: str,
    context: str = "",
) -> Dict[str, Any]:
    """
    6フェーズディープリサーチを実行

    Args:
        query: 調査テーマ
        context: 補足情報

    Returns:
        {
            "success": True,
            "report": "## 調査結果\n\n...",
            "sources": [{"url": "...", "title": "...", "trust_score": 85}, ...],
            "hypotheses": [...],
            "message": "6件のソースを検証し、調査レポートを作成しました"
        }
    """
    try:
        # Phase 1: SCOPE
        scope = await _phase_scope(query, context)
        sub_queries = scope["sub_queries"]
        hypotheses = scope["hypotheses"]

        logger.info(f"[DEEP_RESEARCH] Scope: {len(sub_queries)} sub-queries, {len(hypotheses)} hypotheses")

        # Phase 2: RETRIEVE
        retrieval = await _phase_retrieve(sub_queries, query)

        # Phase 3: TRIANGULATE
        triangulation = _phase_triangulate(retrieval["page_contents"])
        filtered_sources = triangulation["filtered_sources"]

        # Phase 4: SYNTHESIZE
        report = await _phase_synthesize(
            query,
            hypotheses,
            retrieval["search_texts"],
            filtered_sources,
        )

        # Phase 5: CRITIQUE
        critique = await _phase_critique(query, report)

        # Phase 6: REFINE（重大なギャップがある場合のみ）
        quality_score = critique.get("quality_score", 7)
        needs_refine = critique.get("needs_additional_research", False)

        if needs_refine and quality_score < 7:
            report = await _phase_refine(query, report, critique)
            logger.info("[DEEP_RESEARCH] Report refined")

        # ソース一覧を構築
        sources_list = []
        for source in triangulation["evaluated_sources"]:
            sources_list.append({
                "url": source["url"],
                "trust_score": source["trust_score"],
                "trust_level": source["trust_level"],
            })

        # 仮説の状態
        hypotheses_result = []
        for h in hypotheses:
            hypotheses_result.append({
                "statement": h,
                "status": "evaluated",
            })

        source_count = len(filtered_sources)
        return {
            "success": True,
            "report": report,
            "sources": sources_list,
            "hypotheses": hypotheses_result,
            "critique": {
                "quality_score": quality_score,
                "strengths": critique.get("strengths", []),
                "weaknesses": critique.get("weaknesses", []),
            },
            "message": f"{source_count}件のソースを検証し、調査レポートを作成しました",
        }

    except Exception as e:
        logger.exception(f"[DEEP_RESEARCH] Pipeline failed: {e}")
        return {
            "success": False,
            "error": f"調査パイプラインでエラーが発生しました: {e}",
        }
