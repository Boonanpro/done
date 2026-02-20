"""
TeamCoordinator - チーム提案生成の統括

計画フェーズで3人のエージェントが順番に作業し、
高品質な提案書を生成する。

フロー:
  1. リサーチャー: 調査 → findings
  2. クリティック: findings を検証 → critique
  3. リーダー: findings + critique を統合 → 最終提案書
"""

import logging
from typing import Optional, Dict, Any, Callable, Awaitable
from dataclasses import dataclass, field

from app.agent.v2.team.prompts import (
    get_researcher_prompt,
    get_critic_prompt,
    get_leader_prompt,
    build_researcher_message,
    build_critic_message,
    build_leader_message,
)

logger = logging.getLogger(__name__)


@dataclass
class TeamResult:
    """チーム提案の結果"""
    proposal: str                       # 最終提案書（リーダーの出力）
    research_findings: str              # リサーチャーの調査結果
    critique: str                       # クリティックの検証結果
    metadata: Dict[str, Any] = field(default_factory=dict)


class TeamCoordinator:
    """
    チーム提案生成の統括クラス

    3人のエージェント（リサーチャー、クリティック、リーダー）を
    順番に実行し、議論を経た最終提案書を生成する。

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
        チーム提案を実行する。

        Returns:
            TeamResult: 最終提案書、調査結果、検証結果を含む結果

        Raises:
            TeamMemberError: いずれかのメンバーが失敗した場合
        """
        logger.info(f"[Team] Starting team proposal for project {self.project_id}")

        # Step 1: リサーチャーが調査
        await self._notify("リサーチャーが調査を開始しています...")
        research_findings = await self._run_researcher()

        if not research_findings:
            logger.warning("[Team] Researcher returned empty findings, using fallback")
            research_findings = f"調査を実行できませんでした。プロジェクト情報: {self.title} - {self.description}"

        logger.info(f"[Team] Researcher completed: {len(research_findings)} chars")

        # Step 2: クリティックが検証
        await self._notify("クリティックが調査結果を検証しています...")
        critique = await self._run_critic(research_findings)

        if not critique:
            logger.warning("[Team] Critic returned empty critique, using fallback")
            critique = "検証を実行できませんでした。リサーチャーの調査結果をそのまま使用してください。"

        logger.info(f"[Team] Critic completed: {len(critique)} chars")

        # Step 3: リーダーが統合して最終提案
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
            metadata={
                "team_type": "planning",
                "members": ["researcher", "critic", "leader"],
                "research_length": len(research_findings),
                "critique_length": len(critique),
                "proposal_length": len(proposal),
            },
        )

    async def _run_researcher(self) -> str:
        """リサーチャーを実行"""
        system_prompt = get_researcher_prompt(
            self.title, self.description, self.user_messages,
        )
        message = build_researcher_message(
            self.title, self.description, self.user_messages,
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

        # resultメッセージのテキストを最優先、なければストリーミング中のtext全てを結合
        final = result_text or "\n".join(text_parts)
        logger.info(f"[Team] {role} result: result_text={len(result_text)} chars, "
                     f"text_parts={len(text_parts)} parts ({sum(len(t) for t in text_parts)} chars), "
                     f"final={len(final)} chars")
        return final

    async def _notify(self, message: str) -> None:
        """ステータスをコールバック経由で通知"""
        logger.info(f"[Team] {message}")
        if self._on_status:
            try:
                await self._on_status(message)
            except Exception as e:
                logger.warning(f"[Team] Status callback failed: {e}")
