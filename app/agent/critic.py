"""
Critic（評価器）- 提案を評価し、問題があれば修正を促す

ユーザーには見せず、内部で自動修正する。
ナレーション（reasoning_steps）には自問形式で記録。

例:
  Criticログ: { "issue": "価格根拠が不足" }
  表示: 「価格の根拠が弱い。公式ページで確認する必要がありそう。」
"""
import json
import logging
from typing import Any, Optional

import anthropic

from app.config import settings

logger = logging.getLogger(__name__)


CRITIC_PROMPT = """
あなたは提案の品質を評価する評価者です。

## ユーザーの要望
{intake_result}

## 提案内容
{proposal}

## 評価タスク
以下の観点で提案を評価してください：

1. **要望との一致**: ユーザーの**元の発言**に合っているか
2. **仮定の妥当性**: 仮定した項目（時間、人数など）は妥当か
3. **情報の完全性**: 必要な情報が揃っているか
4. **選択肢の質**: おすすめと代替案のバランスは適切か

## 重要なルール
- **検索結果・Executorの情報を信頼すること**（自分の知識で否定しない）
- **事実確認は行わない**（列車名、料金、時刻などは検索結果を正とする）
- **LLMの推論過程は評価しない**（ユーザーの元の要望のみに基づいて判断）
- 小さな問題は無視する（重大な問題のみ指摘）

## 出力形式
```json
{{
  "is_valid": true/false,
  "score": 0-100,
  "issues": ["問題点1", "問題点2"],
  "suggestions": ["修正案1", "修正案2"],
  "reasoning": "評価の理由"
}}
```

問題がなければ is_valid: true、score: 80以上にしてください。
重大な問題とは「ユーザーの元の要望と明らかに違う」「必須情報が欠けている」などです。
"""


class Critic:
    """提案の品質を評価する評価器"""
    
    def __init__(self, llm_client: Optional[Any] = None):
        if llm_client:
            self.llm_client = llm_client
        elif settings.ANTHROPIC_API_KEY:
            self.llm_client = anthropic.AsyncAnthropic(
                api_key=settings.ANTHROPIC_API_KEY
            )
        else:
            self.llm_client = None
            logger.warning("ANTHROPIC_API_KEY not set, Critic will skip evaluation")
    
    async def evaluate_proposal(
        self,
        proposal: dict,
        intake_result: dict,
    ) -> dict:
        """
        提案を評価
        
        Returns:
            {
                "is_valid": bool,
                "score": int,
                "issues": list[str],
                "suggestions": list[str],
                "reasoning": str,
            }
        """
        if not self.llm_client:
            # LLMがない場合はスキップ（常にvalid）
            return {
                "is_valid": True,
                "score": 100,
                "issues": [],
                "suggestions": [],
                "reasoning": "Critic skipped (no LLM client)",
            }
        
        try:
            prompt = CRITIC_PROMPT.format(
                intake_result=json.dumps(intake_result, ensure_ascii=False, indent=2),
                proposal=json.dumps(proposal, ensure_ascii=False, indent=2),
            )
            
            response = await self.llm_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1000,
                messages=[{"role": "user", "content": prompt}],
            )
            
            result_text = response.content[0].text
            
            # JSONを抽出
            if "```json" in result_text:
                start = result_text.find("```json") + 7
                end = result_text.find("```", start)
                json_str = result_text[start:end].strip()
            elif "```" in result_text:
                start = result_text.find("```") + 3
                end = result_text.find("```", start)
                json_str = result_text[start:end].strip()
            else:
                json_str = result_text.strip()
            
            return json.loads(json_str)
        
        except Exception as e:
            logger.exception(f"Critic evaluation failed: {e}")
            # エラー時はスキップ（常にvalid）
            return {
                "is_valid": True,
                "score": 100,
                "issues": [],
                "suggestions": [],
                "reasoning": f"Critic error: {e}",
            }
    
    async def suggest_fix(
        self,
        proposal: dict,
        issues: list[str],
        suggestions: list[str],
        intake_result: dict = None,
    ) -> tuple[dict, list[str]]:
        """
        問題を修正した新しい提案を生成
        
        必要に応じてJina + Tavilyで再検索を実行する。
        
        Args:
            proposal: 現在の提案
            issues: 問題点のリスト
            suggestions: 修正案のリスト
            intake_result: ユーザーの要望（再検索用）
        
        Returns:
            (修正された提案, 追加のreasoning_steps)
        """
        reasoning_steps = []
        
        if not self.llm_client:
            return proposal, reasoning_steps
        
        try:
            # 再検索が必要かどうか判定
            needs_research = self._needs_additional_research(issues, suggestions)
            
            additional_info = {}
            if needs_research and intake_result:
                reasoning_steps.append("根拠を確認するためにWeb検索を実行中...")
                additional_info = await self._research_for_fix(intake_result, issues)
                if additional_info:
                    reasoning_steps.append(f"検索結果を取得しました（{len(additional_info.get('results', []))}件）")
            
            # 修正プロンプトを生成
            prompt = f"""
以下の提案に問題があります。修正してください。

## 現在の提案
{json.dumps(proposal, ensure_ascii=False, indent=2)}

## 問題点
{json.dumps(issues, ensure_ascii=False)}

## 修正案
{json.dumps(suggestions, ensure_ascii=False)}
"""
            
            # 追加情報があれば含める
            if additional_info:
                prompt += f"""
## 追加で取得した情報（これを根拠にしてください）
{json.dumps(additional_info, ensure_ascii=False, indent=2)}
"""
            
            prompt += """
## タスク
問題を修正した新しい提案をJSON形式で出力してください。
元の提案と同じ構造を維持してください。
追加情報がある場合は、その情報を根拠として使用してください。
"""
            
            response = await self.llm_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}],
            )
            
            result_text = response.content[0].text
            
            # JSONを抽出
            if "```json" in result_text:
                start = result_text.find("```json") + 7
                end = result_text.find("```", start)
                json_str = result_text[start:end].strip()
            elif "```" in result_text:
                start = result_text.find("```") + 3
                end = result_text.find("```", start)
                json_str = result_text[start:end].strip()
            else:
                json_str = result_text.strip()
            
            return json.loads(json_str), reasoning_steps
        
        except Exception as e:
            logger.exception(f"Critic fix suggestion failed: {e}")
            return proposal, reasoning_steps
    
    def _needs_additional_research(self, issues: list[str], suggestions: list[str]) -> bool:
        """
        再検索が必要かどうか判定
        
        以下のキーワードが含まれていれば再検索が必要：
        - 価格、料金、コスト
        - 根拠、確認、検証
        - 公式、最新、正確
        """
        research_keywords = [
            "価格", "料金", "コスト", "金額",
            "根拠", "確認", "検証", "裏付け",
            "公式", "最新", "正確", "実際",
            "時刻", "時間", "スケジュール",
            "在庫", "空席", "availability",
        ]
        
        all_text = " ".join(issues + suggestions).lower()
        return any(keyword in all_text for keyword in research_keywords)
    
    async def _research_for_fix(self, intake_result: dict, issues: list[str]) -> dict:
        """
        問題を修正するための追加検索を実行
        
        Jina AI Reader + Tavilyで正確な情報を取得
        """
        try:
            from app.tools.tavily_search import search_with_tavily
            from app.tools.jina_reader import search_and_read
            
            # 検索クエリを構築
            intent = intake_result.get("intent", "")
            details = intake_result.get("details", {})
            
            # issuesからキーワードを抽出
            issue_keywords = " ".join(issues)
            
            # クエリを組み立て
            query_parts = [intent]
            for key in ["departure", "arrival", "product"]:
                if details.get(key):
                    query_parts.append(str(details[key]))
            
            # 価格や料金が問題の場合、「料金」「価格」を追加
            if "価格" in issue_keywords or "料金" in issue_keywords:
                query_parts.append("料金 価格 公式")
            
            query = " ".join(query_parts)
            
            logger.info(f"Critic re-search query: {query}")
            
            # Tavilyで検索
            tavily_results = await search_with_tavily(query, max_results=3)
            
            if not tavily_results:
                return {}
            
            # Jinaでページ内容を取得
            results_with_content = await search_and_read(
                [r.model_dump() for r in tavily_results],
                max_pages=2,
            )
            
            return {
                "source": "critic_research",
                "query": query,
                "results": results_with_content,
            }
        
        except Exception as e:
            logger.exception(f"Critic research failed: {e}")
            return {}
    
    async def format_as_self_question(
        self,
        issues: list[str],
        suggestions: list[str],
    ) -> str:
        """
        問題点と修正案を自問形式の自然な日本語に変換
        
        例:
          入力: issues=["価格根拠が不足"], suggestions=["公式ページで確認"]
          出力: "価格の根拠が弱い。公式ページで確認する必要がありそう。"
        
        Returns:
            自問形式の文字列（問題がなければ空文字列）
        """
        if not issues and not suggestions:
            return ""
        
        if not self.llm_client:
            # LLMがない場合はシンプルな形式で返す
            parts = []
            for issue in issues:
                parts.append(f"{issue}かもしれない。")
            for suggestion in suggestions:
                parts.append(f"{suggestion}必要がありそう。")
            return "".join(parts) if parts else ""
        
        try:
            prompt = f"""以下の問題点と修正案を、自問形式の自然な日本語1文に変換してください。

## 問題点
{json.dumps(issues, ensure_ascii=False)}

## 修正案
{json.dumps(suggestions, ensure_ascii=False)}

## ルール
- 「〇〇が弱い。〇〇する必要がありそう。」のような自問形式
- 1〜2文で簡潔に
- 箇条書きではなく自然な文章で
- 「問題:」「修正:」などのプレフィックスは使わない

## 出力例
「価格の根拠が弱い。公式ページで確認する必要がありそう。」
「時間の仮定が曖昧。もう少し具体的にした方がいいかも。」

出力（1〜2文のみ、余計な説明なし）:"""

            response = await self.llm_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            
            result = response.content[0].text.strip()
            # 余計な引用符を除去
            if result.startswith("「") and result.endswith("」"):
                result = result[1:-1]
            return result
        
        except Exception as e:
            logger.exception(f"format_as_self_question failed: {e}")
            # フォールバック
            return f"{issues[0]}かもしれない。" if issues else ""

