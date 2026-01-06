"""
Critic（評価器）- 提案を評価し、問題があれば修正を促す

ユーザーには見せず、内部で自動修正する。
ナレーション（reasoning_steps）には問題と修正内容を記録。
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
    ) -> dict:
        """
        問題を修正した新しい提案を生成
        
        Returns:
            修正された提案
        """
        if not self.llm_client:
            return proposal
        
        try:
            prompt = f"""
以下の提案に問題があります。修正してください。

## 現在の提案
{json.dumps(proposal, ensure_ascii=False, indent=2)}

## 問題点
{json.dumps(issues, ensure_ascii=False)}

## 修正案
{json.dumps(suggestions, ensure_ascii=False)}

## タスク
問題を修正した新しい提案をJSON形式で出力してください。
元の提案と同じ構造を維持してください。
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
            
            return json.loads(json_str)
        
        except Exception as e:
            logger.exception(f"Critic fix suggestion failed: {e}")
            return proposal

