"""
TeamCoordinator - チーム提案生成の統括

計画フェーズでエージェントチームが進化的探索を行い、
高品質な提案書を生成する。

フロー:
  1. エバリュエーター: ユーザーの「問い」自体を評価・再構成
  2. リサーチャー (Round 1): 初期仮説を立てて調査 → findings
  3. エボルバー: findings から仮説を変異・交叉 → evolved hypotheses
  4. リサーチャー (Round 2): 進化した仮説を検証 → evolved findings
  5. クリティック: 統合 findings を検証 → critique (差し戻し可)
  6. (差し戻し時) リサーチャー追加調査 → 改訂 findings
  7. リーダー: 最終 findings + critique を統合 → 最終提案書

進化的探索: AlphaEvolve パターン（生成→評価→選択→変異→再検証）
差し戻し最大回数: MAX_RESEARCH_ROUNDS (デフォルト2)
"""

import logging
import re
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime

from app.agent.v2.team.prompts import (
    get_evaluator_prompt,
    get_researcher_prompt,
    get_researcher_followup_prompt,
    get_evolver_prompt,
    get_critic_prompt,
    get_leader_prompt,
    build_evaluator_message,
    build_researcher_message,
    build_researcher_followup_message,
    build_evolver_message,
    build_researcher_evolution_message,
    build_critic_message,
    build_leader_message,
)

logger = logging.getLogger(__name__)

# Critic → Researcher の差し戻し最大回数
MAX_RESEARCH_ROUNDS = 2

# 失敗記録ファイル
FAILURES_FILE = Path("D:/dan-workspace/failures.md")


@dataclass
class TeamResult:
    """チーム提案の結果"""
    proposal: str                       # 最終提案書（リーダーの出力）
    research_findings: str              # リサーチャーの調査結果（最終版）
    critique: str                       # クリティックの検証結果（最終版）
    evaluation: str = ""                # エバリュエーターの問い評価
    evolved_hypotheses: str = ""        # エボルバーが生成した進化仮説
    research_rounds: int = 1            # リサーチ実行回数
    metadata: Dict[str, Any] = field(default_factory=dict)


def _parse_additional_research_needed(critique: str) -> bool:
    """クリティックの出力から追加調査要否を判定する"""
    # ADDITIONAL_RESEARCH_NEEDED: YES/NO パターンを探す
    match = re.search(
        r'ADDITIONAL_RESEARCH_NEEDED:\s*(YES|NO)',
        critique,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).upper() == "YES"
    # パターンが見つからない場合は追加調査不要とみなす
    return False


class TeamCoordinator:
    """
    チーム提案生成の統括クラス

    エバリュエーター → リサーチャー ⇄ クリティック → リーダー の流れで
    議論を経た最終提案書を生成する。

    各エージェントは Claude CLI (process_message_cli) 経由で実行される。
    """

    def __init__(
        self,
        project_id: str,
        room_id: str,
        user_id: str,
        title: str,
        description: str,
        user_messages: str = "",
        on_status: Optional[Callable[[str], Awaitable[None]]] = None,
    ):
        self.project_id = project_id
        self.room_id = room_id
        self.user_id = user_id
        self.title = title
        self.description = description
        self.user_messages = user_messages
        self._on_status = on_status

    async def run(self) -> TeamResult:
        """
        チーム提案を実行する（進化的探索付き）。

        フロー:
          Evaluator → Researcher(初期調査) → Evolver(仮説進化)
          → Researcher(進化仮説検証) → Critic ⇄ Researcher(差し戻し) → Leader

        Returns:
            TeamResult: 最終提案書、調査結果、検証結果を含む結果
        """
        logger.info(f"[Team] Starting team proposal for project {self.project_id}")

        # ── Phase 1: 問いの評価 ──
        await self._notify("エバリュエーターがプロジェクトの問いを評価しています...")
        evaluation = await self._run_evaluator()

        if not evaluation:
            logger.warning("[Team] Evaluator returned empty, proceeding without evaluation")
            evaluation = ""
        else:
            logger.info(f"[Team] Evaluator completed: {len(evaluation)} chars")

        # ── Phase 2: 初期調査 ──
        await self._notify("リサーチャーが初期調査を開始しています...")
        research_findings = await self._run_researcher(evaluation=evaluation)

        if not research_findings:
            logger.warning("[Team] Researcher returned empty findings, using fallback")
            research_findings = (
                f"調査を実行できませんでした。プロジェクト情報: "
                f"{self.title} - {self.description}"
            )

        logger.info(f"[Team] Researcher initial findings: {len(research_findings)} chars")

        # ── Phase 3: 進化的探索 (AlphaEvolve パターン) ──
        # 3a. エボルバーが仮説を変異・交叉させる
        await self._notify("エボルバーが仮説を進化させています...")
        evolved_hypotheses = await self._run_evolver(research_findings)

        if not evolved_hypotheses:
            logger.warning("[Team] Evolver returned empty, skipping evolution phase")
            evolved_hypotheses = ""
        else:
            logger.info(f"[Team] Evolver completed: {len(evolved_hypotheses)} chars")

            # 3b. リサーチャーが進化した仮説を検証する
            await self._notify("リサーチャーが進化した仮説を検証しています...")
            evolved_findings = await self._run_researcher_evolution(
                previous_findings=research_findings,
                evolved_hypotheses=evolved_hypotheses,
            )

            if evolved_findings:
                # 進化仮説の検証結果を統合版として使う
                research_findings = evolved_findings
                logger.info(
                    f"[Team] Researcher evolution findings: {len(research_findings)} chars"
                )
            else:
                logger.warning("[Team] Researcher evolution returned empty, keeping initial findings")

        # ── Phase 4: クリティック検証 + 差し戻しループ ──
        research_rounds = 1
        critique = ""

        for round_num in range(1, MAX_RESEARCH_ROUNDS + 1):
            round_label = f"(ラウンド {round_num}/{MAX_RESEARCH_ROUNDS})" if MAX_RESEARCH_ROUNDS > 1 else ""
            await self._notify(f"クリティックが調査結果を検証しています{round_label}...")
            critique = await self._run_critic(research_findings)

            if not critique:
                logger.warning("[Team] Critic returned empty critique, using fallback")
                critique = "検証を実行できませんでした。リサーチャーの調査結果をそのまま使用してください。"
                break

            logger.info(f"[Team] Critic completed (round {round_num}): {len(critique)} chars")

            needs_more = _parse_additional_research_needed(critique)

            if not needs_more:
                logger.info("[Team] Critic says no additional research needed. Proceeding to leader.")
                break

            if round_num >= MAX_RESEARCH_ROUNDS:
                logger.info(
                    f"[Team] Max research rounds ({MAX_RESEARCH_ROUNDS}) reached. "
                    f"Proceeding to leader with current findings."
                )
                break

            # 差し戻し: リサーチャー追加調査
            research_rounds += 1
            await self._notify(
                "クリティックから追加調査の要求がありました。リサーチャーが追加調査を行います..."
            )
            research_findings = await self._run_researcher_followup(
                previous_findings=research_findings,
                critique=critique,
            )

            if not research_findings:
                logger.warning("[Team] Researcher followup returned empty, using previous findings")
                break

            logger.info(
                f"[Team] Researcher followup completed (round {research_rounds}): "
                f"{len(research_findings)} chars"
            )

        # ── Phase 5: リーダーが統合して最終提案 ──
        await self._notify("リーダーが最終提案書を作成しています...")
        proposal = await self._run_leader(research_findings, critique)

        if not proposal:
            logger.warning("[Team] Leader returned empty proposal, falling back to research")
            proposal = research_findings

        logger.info(f"[Team] Leader completed: {len(proposal)} chars")
        await self._notify("チーム提案が完了しました。")

        return TeamResult(
            proposal=proposal,
            research_findings=research_findings,
            critique=critique,
            evaluation=evaluation,
            evolved_hypotheses=evolved_hypotheses,
            research_rounds=research_rounds,
            metadata={
                "team_type": "planning_with_evolution",
                "members": ["evaluator", "researcher", "evolver", "critic", "leader"],
                "evaluation_length": len(evaluation),
                "research_length": len(research_findings),
                "evolved_hypotheses_length": len(evolved_hypotheses),
                "critique_length": len(critique),
                "proposal_length": len(proposal),
                "research_rounds": research_rounds,
            },
        )

    # ------------------------------------------------------------------
    # 各メンバーの実行
    # ------------------------------------------------------------------

    async def _run_evaluator(self) -> str:
        """エバリュエーターを実行"""
        system_prompt = get_evaluator_prompt(
            self.title, self.description, self.user_messages,
        )
        message = build_evaluator_message(
            self.title, self.description, self.user_messages,
        )
        return await self._run_cli_member(
            role="evaluator",
            system_prompt=system_prompt,
            message=message,
        )

    async def _run_researcher(self, evaluation: str = "") -> str:
        """リサーチャーを実行（初回）"""
        system_prompt = get_researcher_prompt(
            self.title, self.description, self.user_messages,
        )
        message = build_researcher_message(
            self.title, self.description, self.user_messages,
            evaluation=evaluation,
        )
        return await self._run_cli_member(
            role="researcher",
            system_prompt=system_prompt,
            message=message,
        )

    async def _run_researcher_followup(
        self, previous_findings: str, critique: str,
    ) -> str:
        """リサーチャーを実行（追加調査）"""
        system_prompt = get_researcher_followup_prompt(
            self.title, self.description, self.user_messages,
        )
        message = build_researcher_followup_message(
            previous_findings=previous_findings,
            critique=critique,
        )
        return await self._run_cli_member(
            role="researcher",
            system_prompt=system_prompt,
            message=message,
        )

    async def _run_evolver(self, research_findings: str) -> str:
        """エボルバーを実行（仮説を進化させる）"""
        system_prompt = get_evolver_prompt(self.title, self.description)
        message = build_evolver_message(research_findings)
        return await self._run_cli_member(
            role="evolver",
            system_prompt=system_prompt,
            message=message,
        )

    async def _run_researcher_evolution(
        self, previous_findings: str, evolved_hypotheses: str,
    ) -> str:
        """リサーチャーを実行（進化した仮説の検証）"""
        system_prompt = get_researcher_followup_prompt(
            self.title, self.description, self.user_messages,
        )
        message = build_researcher_evolution_message(
            previous_findings=previous_findings,
            evolved_hypotheses=evolved_hypotheses,
        )
        return await self._run_cli_member(
            role="researcher",
            system_prompt=system_prompt,
            message=message,
        )

    async def _run_critic(self, research_findings: str) -> str:
        """クリティックを実行"""
        system_prompt = get_critic_prompt(self.title, self.description)
        message = build_critic_message(research_findings)
        return await self._run_cli_member(
            role="critic",
            system_prompt=system_prompt,
            message=message,
        )

    async def _run_leader(self, research_findings: str, critique: str) -> str:
        """リーダーを実行"""
        system_prompt = get_leader_prompt(self.title, self.description)
        message = build_leader_message(research_findings, critique)
        return await self._run_cli_member(
            role="leader",
            system_prompt=system_prompt,
            message=message,
        )

    # ------------------------------------------------------------------
    # CLI実行共通
    # ------------------------------------------------------------------

    async def _run_cli_member(
        self,
        role: str,
        system_prompt: str,
        message: str,
    ) -> str:
        """
        CLI Runner経由でチームメンバーを実行する。

        各メンバーは独立したCLIセッションとして実行される。
        room_idにロール名を付加して、セッション管理の衝突を避ける。
        """
        from app.agent.cli_runner import process_message_cli

        # ロール別の仮想room_id（セッション管理の衝突回避）
        member_room_id = f"{self.room_id}_team_{role}"

        text_parts = []       # ストリーミング中のtextイベントを蓄積
        result_text = ""      # CLIのresultメッセージのテキスト（最優先）
        try:
            async for event in process_message_cli(
                room_id=member_room_id,
                user_id=self.user_id,
                content=message,
                project_title=self.title,
                project_description=self.description or "",
                project_status="planning",
                system_prompt=system_prompt,
            ):
                etype = event.get("type", "")
                if etype == "text":
                    text = event.get("text", "")
                    if text.strip():
                        text_parts.append(text)
                elif etype == "result":
                    result_text = event.get("text", "")
                elif etype == "error":
                    error_msg = event.get("message", "")
                    logger.warning(f"[Team] {role} error: {error_msg[:200]}")

        except Exception as e:
            logger.exception(f"[Team] {role} failed: {e}")
            await self._record_failure(role, "exception", str(e))

        # resultメッセージのテキストを最優先、なければストリーミング中のtext全てを結合
        final = result_text or "\n".join(text_parts)

        if not final.strip():
            await self._record_failure(role, "empty_result", "出力が空")

        logger.info(f"[Team] {role} result: result_text={len(result_text)} chars, "
                     f"text_parts={len(text_parts)} parts ({sum(len(t) for t in text_parts)} chars), "
                     f"final={len(final)} chars")
        return final

    async def _record_failure(self, role: str, failure_type: str, detail: str):
        """失敗をファイルに記録する"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = (
            f"\n## {timestamp} | {role} | {failure_type}\n"
            f"- プロジェクト: {self.title}\n"
            f"- project_id: {self.project_id}\n"
            f"- 詳細: {detail[:500]}\n"
        )
        try:
            FAILURES_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(FAILURES_FILE, "a", encoding="utf-8") as f:
                f.write(entry)
        except Exception as e:
            logger.warning(f"[Team] Failed to record failure: {e}")

    async def _notify(self, message: str) -> None:
        """ステータスをコールバック経由で通知"""
        logger.info(f"[Team] {message}")
        if self._on_status:
            try:
                await self._on_status(message)
            except Exception as e:
                logger.warning(f"[Team] Status callback failed: {e}")
