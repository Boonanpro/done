"""
StateMachine テスト

状態機械の動作確認テスト。
LLM APIを使用するため、ANTHROPIC_API_KEYが必要。

Step 6追加: agent.py統合テスト
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.agent.state_machine import StateMachine
from app.agent.states import State
from app.agent.agent import AISecretaryAgent


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


class TestAgentStateMachineIntegration:
    """Step 6: agent.py統合テスト"""

    @pytest.fixture
    def mock_llm_client(self):
        """LLMクライアントのモック"""
        client = MagicMock()
        client.messages = MagicMock()
        return client

    @pytest.mark.asyncio
    async def test_process_with_state_machine_new_session(self, mock_llm_client):
        """新規セッションでの処理（モック）"""
        agent = AISecretaryAgent()

        # StateMachineをモック注入（メソッド内でインポートされるのでstate_machineモジュールをパッチ）
        with patch('app.agent.state_machine.StateMachine') as MockSM:
            mock_sm_instance = MagicMock()
            mock_sm_instance.process_message = AsyncMock(return_value={
                "state": "CHAT",
                "response": "こんにちは！",
                "reasoning_steps": ["挨拶と判断"],
                "is_chat": True,
            })
            MockSM.return_value = mock_sm_instance

            result = await agent.process_with_state_machine(
                message="こんにちは",
                user_id="test-user",
            )

        # session_idが返されること
        assert "session_id" in result
        # 状態がCHATであること
        assert result.get("state") == "CHAT"
        # is_chatフラグがTrueであること
        assert result.get("is_chat") is True

    @pytest.mark.asyncio
    async def test_process_with_state_machine_task(self, mock_llm_client):
        """タスクメッセージの処理（モック）"""
        agent = AISecretaryAgent()

        with patch('app.agent.state_machine.StateMachine') as MockSM:
            mock_sm_instance = MagicMock()
            mock_sm_instance.process_message = AsyncMock(return_value={
                "state": "confirm",
                "response": "**おすすめ**: のぞみ45号",
                "reasoning_steps": ["新幹線移動と判断", "EX予約を使用"],
                "needs_confirmation": True,
                "proposal": {
                    "recommendation": {"title": "のぞみ45号", "price": 14720}
                },
            })
            mock_sm_instance.state = MagicMock()
            mock_sm_instance.state.to_dict = MagicMock(return_value={"current_state": "confirm"})
            MockSM.return_value = mock_sm_instance

            result = await agent.process_with_state_machine(
                message="明日18時に新大阪から博多まで行きたい",
                session_id="test-session-1",
                user_id="test-user",
            )

        # session_idが返されること
        assert result.get("session_id") == "test-session-1"
        # 状態がconfirmであること
        assert result.get("state") == "confirm"
        # needs_confirmationがTrueであること
        assert result.get("needs_confirmation") is True
        # proposalが含まれていること
        assert result.get("proposal") is not None

    @pytest.mark.asyncio
    async def test_confirm_state_machine(self, mock_llm_client):
        """提案の承認（モック）"""
        agent = AISecretaryAgent()

        # まずセッションを作成
        with patch('app.agent.state_machine.StateMachine') as MockSM:
            mock_sm_instance = MagicMock()
            mock_sm_instance.process_message = AsyncMock(return_value={
                "state": "confirm",
                "response": "提案内容",
                "reasoning_steps": [],
                "needs_confirmation": True,
            })
            mock_sm_instance.state = MagicMock()
            mock_sm_instance.state.to_dict = MagicMock(return_value={"current_state": "confirm"})
            MockSM.return_value = mock_sm_instance

            await agent.process_with_state_machine(
                message="テスト",
                session_id="test-confirm-session",
                user_id="test-user",
            )

            # 承認時のモック
            mock_sm_instance.process_message = AsyncMock(return_value={
                "state": "REPORT",
                "response": "予約が完了しました",
                "reasoning_steps": ["承認されました", "実行完了"],
                "needs_confirmation": False,
            })

            result = await agent.confirm_state_machine("test-confirm-session")

        # 状態がREPORTであること
        assert result.get("state") == "REPORT"
        # needs_confirmationがFalseであること
        assert result.get("needs_confirmation") is False

    @pytest.mark.asyncio
    async def test_get_state_machine_state(self, mock_llm_client):
        """状態取得（モック）"""
        agent = AISecretaryAgent()

        with patch('app.agent.state_machine.StateMachine') as MockSM:
            mock_sm_instance = MagicMock()
            mock_sm_instance.process_message = AsyncMock(return_value={
                "state": "confirm",
                "response": "提案内容",
                "reasoning_steps": [],
            })
            mock_sm_instance.state = MagicMock()
            mock_sm_instance.state.to_dict = MagicMock(return_value={
                "current_state": "confirm",
                "session_id": "test-state-session",
                "user_id": "test-user",
            })
            MockSM.return_value = mock_sm_instance

            await agent.process_with_state_machine(
                message="テスト",
                session_id="test-state-session",
                user_id="test-user",
            )

            state = agent.get_state_machine_state("test-state-session")

        # 状態が取得できること
        assert state is not None
        assert state.get("current_state") == "confirm"

    @pytest.mark.asyncio
    async def test_get_state_machine_state_not_found(self):
        """存在しないセッションの状態取得"""
        agent = AISecretaryAgent()

        state = agent.get_state_machine_state("non-existent-session")

        # Noneが返されること
        assert state is None

