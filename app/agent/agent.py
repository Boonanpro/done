"""
AI Secretary Agent - LangGraph Implementation
"""
from typing import TypedDict, Annotated, Sequence, Optional, Any
from datetime import datetime
import uuid
import operator
import logging

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from app.config import settings
from app.models.schemas import TaskStatus, TaskType, TaskResponse
from app.tools import get_tools, get_available_tool_names

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """Agent state"""
    messages: Annotated[Sequence[BaseMessage], operator.add]
    task_id: str
    user_id: Optional[str]
    original_wish: str
    task_type: Optional[TaskType]
    proposed_actions: list[str]
    requires_confirmation: bool
    execution_result: Optional[dict[str, Any]]
    status: TaskStatus


class AISecretaryAgent:
    """AI Secretary Agent"""
    
    # クラス変数としてタスクストレージを共有（すべてのインスタンス間で共有）
    _tasks: dict[str, dict] = {}
    
    SYSTEM_PROMPT = """あなたは優秀なAI秘書「Done」です。
ユーザーの「○○したい」「○○して」という願望に対して、具体的なアクションを提案し実行します。

## 最重要原則：アクションファースト

1. **絶対に質問で返さない**
   - ❌「どんなPCが欲しいですか？」
   - ❌「予算はいくらですか？」
   - ❌「具体的に何時ですか？」
   - ✅ 情報が不足していても仮説を立てて具体的なアクションを提案する

2. **仮説を立てて提案する**
   - 「夕方」→「17時」と仮定
   - 「PC」→ ユーザーの過去の傾向や一般的な選択肢から仮定
   - 「税理士」→ 一般的な条件で仮定

3. **訂正ベースの対話**
   - ユーザーは提案を見てから「17時じゃなくて16時にして」と訂正する方が楽
   - 事前に質問攻めにするより、具体的な提案を見せてから調整する

4. **認証情報は必要になったら要求**
   - 最初から「ログイン情報をください」と言わない
   - 実行時に必要になったら「実行にはログイン情報が必要です」と伝える

## 提案のフォーマット

必ず以下の形式で回答してください：

【アクション】
（何をするか具体的に。サービス名、連絡先、操作内容を明記）

【詳細】
（送信する文面、予約内容、購入する商品など具体的な内容）

【補足】
（仮定した部分や、訂正可能なポイントがあれば記載）

## 実行可能なツール
- send_email: メール送信
- search_email: メール検索
- read_email: メール読み取り
- send_line_message: LINEメッセージ送信
- browse_website: Webサイト閲覧・操作
- fill_form: フォーム入力
- click_element: Web要素クリック
- search_web: Web検索

## 回答例

ユーザー: 「PCを新調したい」
回答:
【アクション】
MDLmakeにLINEで相談メッセージを送信します。

【詳細】
「お世話になっております。PCの新調を検討しています。現在の用途は主に開発作業で、予算は20万円程度を想定しています。おすすめの構成があればご提案いただけますか？」

【補足】
予算や用途は仮定です。訂正があればお知らせください。

---

ユーザー: 「12月28の夕方に新大阪発博多着の新幹線のチケット取って」
回答:
【アクション】
EX予約で12月28日17:00発の新幹線を予約します。

【詳細】
- 区間: 新大阪 → 博多
- 日時: 12月28日 17:00発（のぞみ○号）
- 座席: 普通車指定席・窓側

【補足】
17:00発は仮定です。「16時にして」「グリーン車にして」など訂正があればお知らせください。

日本語で回答してください。"""

    def __init__(self, tool_names: Optional[list[str]] = None):
        """
        Initialize the agent
        
        Args:
            tool_names: List of tool names to use. If None, initialize without tools
                       Example: ["search_web", "browse_website"]
                       Available tools: browse_website, fill_form, click_element,
                                        take_screenshot, send_email, search_email,
                                        read_email, send_line_message, search_web
        """
        self.llm = ChatAnthropic(
            model="claude-sonnet-4-20250514",
            api_key=settings.ANTHROPIC_API_KEY,
            max_tokens=4096,
        )
        self.tools = get_tools(tool_names)
        self.tool_names = tool_names or []
        
        if self.tools:
            self.llm_with_tools = self.llm.bind_tools(self.tools)
        else:
            self.llm_with_tools = self.llm
        
        self.graph = self._build_graph()
    
    def _build_graph(self) -> StateGraph:
        """Build LangGraph workflow"""
        workflow = StateGraph(AgentState)
        
        # Add nodes
        workflow.add_node("analyze", self._analyze_wish)
        workflow.add_node("propose", self._propose_actions)
        workflow.add_node("tools", ToolNode(self.tools))
        workflow.add_node("execute", self._execute_actions)
        workflow.add_node("respond", self._generate_response)
        
        # Set entry point
        workflow.set_entry_point("analyze")
        
        # Add edges
        workflow.add_edge("analyze", "propose")
        workflow.add_conditional_edges(
            "propose",
            self._should_execute,
            {
                "execute": "execute",
                "wait": "respond",
            }
        )
        workflow.add_conditional_edges(
            "execute",
            self._needs_tools,
            {
                "tools": "tools",
                "respond": "respond",
            }
        )
        workflow.add_edge("tools", "execute")
        workflow.add_edge("respond", END)
        
        return workflow.compile()
    
    async def _analyze_wish(self, state: AgentState) -> AgentState:
        """Analyze the wish and determine task type"""
        wish = state["original_wish"]
        
        # Prompt for task type classification
        analysis_prompt = f"""以下のユーザーリクエストを分析し、タスクタイプを判定してください。

リクエスト: {wish}

タスクタイプ:
- email: メール関連（送信、検索、返信など）
- line: LINE関連（メッセージ送信など）
- purchase: 商品購入関連
- payment: 支払い・決済関連
- research: 情報調査・リサーチ関連
- other: その他

JSON形式で回答: {{"task_type": "タイプ名", "summary": "要約"}}"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=analysis_prompt),
        ]
        
        response = await self.llm.ainvoke(messages)
        
        # Extract task type (simple implementation)
        content = response.content.lower()
        if "email" in content or "メール" in content:
            task_type = TaskType.EMAIL
        elif "line" in content:
            task_type = TaskType.LINE
        elif "purchase" in content or "購入" in content or "買" in content:
            task_type = TaskType.PURCHASE
        elif "payment" in content or "支払" in content or "決済" in content:
            task_type = TaskType.PAYMENT
        elif "research" in content or "調査" in content or "検索" in content or "リサーチ" in content:
            task_type = TaskType.RESEARCH
        else:
            task_type = TaskType.OTHER
        
        return {
            **state,
            "task_type": task_type,
            "status": TaskStatus.ANALYZING,
            "messages": state["messages"] + [response],
        }
    
    async def _propose_actions(self, state: AgentState) -> AgentState:
        """Propose actions to execute"""
        wish = state["original_wish"]
        task_type = state["task_type"]
        
        proposal_prompt = f"""以下のユーザーの願望に対して、アクションファーストで具体的な提案をしてください。

ユーザーの願望: {wish}
タスクタイプ: {task_type}

重要なルール:
- 絶対に質問で返さない（「どんな○○が欲しいですか？」はNG）
- 情報が不足していても仮説を立てて具体的なアクションを提案する
- 仮定した部分は【補足】で明記し、ユーザーが訂正できるようにする

以下のフォーマットで回答してください：

【アクション】
（何をするか具体的に）

【詳細】
（具体的な内容：送信文面、予約詳細、購入商品など）

【補足】
（仮定した部分、訂正可能なポイント）"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=proposal_prompt),
        ]
        response = await self.llm.ainvoke(messages)
        
        # レスポンス全体をアクションとして保存
        content = response.content
        
        # アクション部分を抽出（【アクション】セクション）
        actions = []
        if "【アクション】" in content:
            # 【アクション】から次の【までを抽出
            action_start = content.find("【アクション】") + len("【アクション】")
            action_end = content.find("【", action_start)
            if action_end == -1:
                action_end = len(content)
            action_text = content[action_start:action_end].strip()
            actions = [action_text] if action_text else [content]
        else:
            actions = [content]
        
        # 全ての願望に対して承認を必須にする（アクションファースト原則）
        # ユーザーが提案を確認してから実行する
        requires_confirmation = True
        
        return {
            **state,
            "proposed_actions": actions,
            "requires_confirmation": requires_confirmation,
            "status": TaskStatus.PROPOSED,
            "messages": state["messages"] + [response],
            # 詳細なレスポンスも保存
            "execution_result": {"full_proposal": content},
        }
    
    def _should_execute(self, state: AgentState) -> str:
        """Determine whether to execute or wait for confirmation"""
        if state["requires_confirmation"]:
            return "wait"
        return "execute"
    
    async def _execute_actions(self, state: AgentState) -> AgentState:
        """Execute actions"""
        # Execute actions using tools
        execution_prompt = f"""Execute the following actions.

Request: {state['original_wish']}
Proposed actions:
{chr(10).join('- ' + action for action in state['proposed_actions'])}

Use the available tools to execute."""
        
        messages = state["messages"] + [HumanMessage(content=execution_prompt)]
        response = await self.llm_with_tools.ainvoke(messages)
        
        return {
            **state,
            "status": TaskStatus.EXECUTING,
            "messages": state["messages"] + [response],
        }
    
    def _needs_tools(self, state: AgentState) -> str:
        """Determine if tool execution is needed"""
        last_message = state["messages"][-1]
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "tools"
        return "respond"
    
    async def _generate_response(self, state: AgentState) -> AgentState:
        """Generate final response"""
        return {
            **state,
            "status": TaskStatus.COMPLETED if not state["requires_confirmation"] else TaskStatus.PROPOSED,
        }
    
    async def process_wish(
        self,
        wish: str,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Process wish and create task"""
        task_id = str(uuid.uuid4())
        
        initial_state: AgentState = {
            "messages": [HumanMessage(content=wish)],
            "task_id": task_id,
            "user_id": user_id,
            "original_wish": wish,
            "task_type": None,
            "proposed_actions": [],
            "requires_confirmation": False,
            "execution_result": None,
            "status": TaskStatus.PENDING,
        }
        
        # Execute graph
        final_state = await self.graph.ainvoke(initial_state)
        
        # Save task (クラス変数に保存)
        try:
            AISecretaryAgent._tasks[task_id] = {
                "id": task_id,
                "user_id": user_id,
                "type": final_state["task_type"],
                "status": final_state["status"],
                "original_wish": wish,
                "proposed_actions": final_state["proposed_actions"],
                "execution_result": final_state["execution_result"],
                "created_at": datetime.utcnow(),
            }
            # デバッグ: タスクが保存されたことを確認
            logger.info(f"Task saved: {task_id}, Total tasks: {len(AISecretaryAgent._tasks)}")
        except Exception as e:
            logger.error(f"Failed to save task {task_id}: {e}", exc_info=True)
            raise
        
        # Generate response message (English for API, frontend handles i18n)
        if final_state["requires_confirmation"]:
            message = "Action proposed. Please confirm to execute, or request revisions."
        else:
            message = "Request processed successfully."
        
        # 提案の詳細を取得
        proposal_detail = None
        if final_state["execution_result"] and "full_proposal" in final_state["execution_result"]:
            proposal_detail = final_state["execution_result"]["full_proposal"]
        
        return {
            "task_id": task_id,
            "message": message,
            "proposed_actions": final_state["proposed_actions"],
            "proposal_detail": proposal_detail,
            "requires_confirmation": final_state["requires_confirmation"],
        }
    
    async def execute_task(self, task_id: str) -> dict[str, Any]:
        """Execute confirmed task"""
        task = AISecretaryAgent._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        # Execute task (resume graph in actual implementation)
        task["status"] = TaskStatus.EXECUTING
        
        # TODO: Actual execution logic
        
        task["status"] = TaskStatus.COMPLETED
        return {"status": "completed", "task_id": task_id}
    
    async def revise_task(self, task_id: str, revision: str) -> dict[str, Any]:
        """
        Revise an existing task based on user feedback
        
        Args:
            task_id: The ID of the task to revise
            revision: The revision request (e.g., "17時じゃなくて16時にして")
        
        Returns:
            Updated task with new proposal
        """
        task = AISecretaryAgent._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        original_wish = task["original_wish"]
        previous_proposal = task.get("execution_result", {}).get("full_proposal", "")
        
        # Build revision prompt with context
        revision_prompt = f"""以下のユーザーの願望に対して、訂正リクエストを反映した新しい提案をしてください。

## 元の願望
{original_wish}

## 前回の提案
{previous_proposal}

## ユーザーからの訂正リクエスト
{revision}

重要なルール:
- 訂正リクエストを正確に反映する
- 訂正されていない部分は前回の提案を維持する
- 絶対に質問で返さない
- 仮定した部分は【補足】で明記する

以下のフォーマットで回答してください：

【アクション】
（何をするか具体的に）

【詳細】
（具体的な内容：送信文面、予約詳細、購入商品など）

【補足】
（仮定した部分、訂正可能なポイント）"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=revision_prompt),
        ]
        response = await self.llm.ainvoke(messages)
        
        content = response.content
        
        # Extract action from response
        actions = []
        if "【アクション】" in content:
            action_start = content.find("【アクション】") + len("【アクション】")
            action_end = content.find("【", action_start)
            if action_end == -1:
                action_end = len(content)
            action_text = content[action_start:action_end].strip()
            actions = [action_text] if action_text else [content]
        else:
            actions = [content]
        
        # Update task with new proposal
        task["proposed_actions"] = actions
        task["execution_result"] = {"full_proposal": content}
        task["status"] = TaskStatus.PROPOSED
        
        logger.info(f"Task revised: {task_id}")
        
        return {
            "task_id": task_id,
            "message": "Proposal revised based on your feedback. Please confirm to execute, or request further revisions.",
            "proposed_actions": actions,
            "proposal_detail": content,
            "requires_confirmation": True,
        }
    
    async def get_task(self, task_id: str) -> Optional[TaskResponse]:
        """Get task"""
        task = AISecretaryAgent._tasks.get(task_id)
        if not task:
            return None
        
        return TaskResponse(
            id=task["id"],
            user_id=task["user_id"],
            type=task["type"] or TaskType.OTHER,
            status=task["status"],
            original_wish=task["original_wish"],
            proposed_actions=task["proposed_actions"],
            execution_result=task["execution_result"],
            created_at=task["created_at"],
        )
    
    async def list_tasks(
        self,
        user_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[TaskResponse]:
        """Get task list"""
        tasks = list(AISecretaryAgent._tasks.values())
        
        if user_id:
            tasks = [t for t in tasks if t["user_id"] == user_id]
        
        tasks = sorted(tasks, key=lambda t: t["created_at"], reverse=True)[:limit]
        
        return [
            TaskResponse(
                id=t["id"],
                user_id=t["user_id"],
                type=t["type"] or TaskType.OTHER,
                status=t["status"],
                original_wish=t["original_wish"],
                proposed_actions=t["proposed_actions"],
                execution_result=t["execution_result"],
                created_at=t["created_at"],
            )
            for t in tasks
        ]
