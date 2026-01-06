"""
StateMachine テスト

状態機械の動作確認テスト。
LLM APIを使用するため、ANTHROPIC_API_KEYが必要。
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agent.state_machine import StateMachine
from app.agent.states import State


class TestStateMachineBasic:
    """StateMachineの基本テスト（モック使用）"""

    @pytest.fixture
    def mock_llm_client(self):
        """LLMクライアントのモック"""
        client = MagicMock()
        client.messages = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_initial_state_is_intake(self):
        """初期状態がINTAKEであること"""
        sm = StateMachine(session_id="test-1", user_id="user-1")
        assert sm.state.current_state == State.INTAKE

    @pytest.mark.asyncio
    async def test_task_message_with_mock(self, mock_llm_client):
        """タスクメッセージの処理（モック）"""
        # INTAKEのモックレスポンス
        intake_response = MagicMock()
        intake_response.content = [MagicMock(text='''```json
{
    "intent": "新大阪から博多まで新幹線で移動したい",
    "task_type": "travel",
    "details": {
        "departure": "新大阪駅",
        "arrival": "博多駅",
        "date": "明日",
        "time": "18:00"
    },
    "constraints": {},
    "deadline": "明日",
    "assumptions": ["人数: 1人", "座席: 普通車指定席"],
    "reasoning_steps": ["新幹線移動と判断", "1人と仮定"]
}
```''')]

        # PLANのモックレスポンス
        plan_response = MagicMock()
        plan_response.content = [MagicMock(text='''```json
{
    "tasks": [{"id": 1, "description": "新幹線を検索", "executor": "ex_reservation"}],
    "tools": ["ex_reservation"],
    "stop_conditions": ["予約完了"],
    "risks": [],
    "reasoning_steps": ["EX予約を使用"]
}
```''')]

        # RESEARCHのモックレスポンス
        research_response = MagicMock()
        research_response.content = [MagicMock(text='''```json
{
    "options": [
        {"title": "のぞみ45号", "price": 14720, "departure_time": "18:03"}
    ],
    "sufficient_info": true,
    "reasoning_steps": ["のぞみ45号が最適"]
}
```''')]

        # PROPOSEのモックレスポンス
        propose_response = MagicMock()
        propose_response.content = [MagicMock(text='''```json
{
    "recommendation": {
        "title": "のぞみ45号（新大阪駅→博多駅）",
        "price": 14720
    },
    "recommendation_reason": "18時に最も近い",
    "alternatives": [],
    "reasoning_steps": ["18:03発が最適"]
}
```''')]

        # Criticのモックレスポンス
        critic_response = MagicMock()
        critic_response.content = [MagicMock(text='''```json
{
    "is_valid": true,
    "score": 90,
    "issues": [],
    "suggestions": [],
    "reasoning": "提案は妥当"
}
```''')]

        mock_llm_client.messages.create = AsyncMock(
            side_effect=[
                intake_response,
                plan_response,
                research_response,
                propose_response,
                critic_response,
            ]
        )

        sm = StateMachine(
            session_id="test-1",
            user_id="user-1",
            llm_client=mock_llm_client,
        )

        # Executor検索をモック
        with patch.object(sm, '_call_executor_search', new_callable=AsyncMock) as mock_search:
            mock_search.return_value = {
                "success": True,
                "options": [
                    {"title": "のぞみ45号", "price": 14720, "departure_time": "18:03"}
                ],
            }

            result = await sm.process_message("明日18時に新大阪から博多まで行きたい")

        # 状態がCONFIRMになっていること
        assert result.get("state") == "confirm"
        # 応答が含まれていること
        assert result.get("response") is not None
        # reasoning_stepsが存在すること
        assert "reasoning_steps" in result
        assert len(result["reasoning_steps"]) > 0

    @pytest.mark.asyncio
    async def test_chat_message_with_mock(self, mock_llm_client):
        """雑談メッセージの処理（モック）"""
        # INTAKEのモックレスポンス（task_type: other）
        intake_response = MagicMock()
        intake_response.content = [MagicMock(text='''```json
{
    "intent": "挨拶",
    "task_type": "other",
    "details": {},
    "constraints": {},
    "deadline": "",
    "assumptions": [],
    "reasoning_steps": ["挨拶と判断"]
}
```''')]

        # チャット応答のモックレスポンス
        chat_response = MagicMock()
        chat_response.content = [MagicMock(text="おはようございます！")]

        mock_llm_client.messages.create = AsyncMock(
            side_effect=[intake_response, chat_response]
        )

        sm = StateMachine(
            session_id="test-2",
            user_id="user-1",
            llm_client=mock_llm_client,
        )

        result = await sm.process_message("おはよう")

        # 状態がCHATになっていること
        assert result.get("state") == "CHAT"
        # is_chatフラグがTrueであること
        assert result.get("is_chat") is True
        # 応答が含まれていること
        assert result.get("response") is not None


class TestStateMachineIntegration:
    """StateMachineの統合テスト（実際のLLM使用、要API KEY）"""

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not pytest.importorskip("app.config").settings.ANTHROPIC_API_KEY,
        reason="ANTHROPIC_API_KEY not set"
    )
    async def test_task_message_real_llm(self):
        """タスクメッセージの処理（実際のLLM）"""
        sm = StateMachine(session_id="test-real-1", user_id="user-1")

        result = await sm.process_message("明日18時に新大阪から博多まで行きたい")

        # 状態がCONFIRMまたはERRORになっていること
        assert result.get("state") in ["confirm", "ERROR", State.CONFIRM.value, State.ERROR.value]
        # reasoning_stepsが存在すること
        assert "reasoning_steps" in result

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not pytest.importorskip("app.config").settings.ANTHROPIC_API_KEY,
        reason="ANTHROPIC_API_KEY not set"
    )
    async def test_chat_message_real_llm(self):
        """雑談メッセージの処理（実際のLLM）"""
        sm = StateMachine(session_id="test-real-2", user_id="user-1")

        result = await sm.process_message("おはよう")

        # 状態がCHATになっていること
        assert result.get("state") == "CHAT"
        # is_chatフラグがTrueであること
        assert result.get("is_chat") is True

