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
from app.models.schemas import TaskStatus, TaskType, TaskResponse, SearchResultCategory
from app.tools import get_tools, get_available_tool_names
from app.tools.tavily_search import tavily_search
from app.tools.travel_search import search_train, search_bus, search_flight
from app.tools.product_search import search_amazon, search_products

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
    search_results: list[dict]  # Phase 3A: 検索結果を保存


class AISecretaryAgent:
    """AI Secretary Agent"""
    
    # クラス変数としてタスクストレージを共有（すべてのインスタンス間で共有）
    _tasks: dict[str, dict] = {}
    
    SYSTEM_PROMPT = """You are an excellent AI secretary called "Done".
You propose and execute specific actions for user requests like "I want to..." or "Please do...".

## Core Principle: Action First

1. **Never respond with questions**
   - BAD: "What kind of PC do you want?"
   - BAD: "What's your budget?"
   - BAD: "What time exactly?"
   - GOOD: Propose a specific action even with incomplete information

2. **Make assumptions and propose**
   - "evening" -> assume "5pm"
   - "PC" -> assume based on common choices
   - "accountant" -> assume general requirements

3. **Correction-based dialogue**
   - Users prefer to see a concrete proposal and then correct it
   - "Change 5pm to 4pm" is easier than answering 10 questions upfront

4. **Request credentials only when needed**
   - Don't ask for login info upfront
   - Request it when actually needed during execution

## Response Format

Always respond in this format:

[ACTION]
(What you will do - be specific with service names, contacts, operations)

[DETAILS]
(Specific content: message text, booking details, items to purchase)

[NOTES]
(Assumptions made, points that can be corrected)

## Available Tools
- send_email: Send emails
- search_email: Search emails
- read_email: Read emails
- send_line_message: Send LINE messages
- browse_website: Browse and operate websites
- fill_form: Fill in forms
- click_element: Click web elements
- search_web: Web search

## Examples

User: "I want to buy a new PC"
Response:
[ACTION]
Send a consultation message to MDLmake via LINE.

[DETAILS]
"Hello, I'm considering getting a new PC. My primary use is development work, and my budget is around $1,500. Could you recommend a configuration?"

[NOTES]
Budget and usage are assumptions. Let me know if you'd like to correct them.

---

User: "Book a Shinkansen ticket from Shin-Osaka to Hakata on December 28th around 5pm"
Response:
[ACTION]
Book a Shinkansen ticket departing 5:00 PM on December 28th via EX Reservation.

[DETAILS]
- Route: Shin-Osaka -> Hakata
- Date/Time: December 28th, 5:00 PM (Nozomi)
- Seat: Reserved, ordinary car, window side

[NOTES]
5:00 PM is an assumption. Let me know if you want "4pm instead" or "Green car" etc.

Always respond in English."""

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
        analysis_prompt = f"""Analyze the following user request and determine the task type.

Request: {wish}

Task types:
- email: Email related (send, search, reply, etc.)
- line: LINE messaging related
- purchase: Product purchase related
- payment: Payment/billing related
- research: Information research related
- other: Other

Respond in JSON format: {{"task_type": "type_name", "summary": "summary"}}"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=analysis_prompt),
        ]
        
        response = await self.llm.ainvoke(messages)
        
        # Extract task type (simple implementation)
        content = response.content.lower()
        wish_lower = state["original_wish"].lower()
        
        if "email" in content:
            task_type = TaskType.EMAIL
        elif "line" in content:
            task_type = TaskType.LINE
        elif "travel" in content or "train" in content or "shinkansen" in content or \
             "新幹線" in wish_lower or "電車" in wish_lower or "飛行機" in wish_lower or \
             "バス" in wish_lower or "予約" in wish_lower:
            task_type = TaskType.TRAVEL
        elif "purchase" in content or "buy" in content or \
             "買いたい" in wish_lower or "欲しい" in wish_lower or "購入" in wish_lower:
            task_type = TaskType.PURCHASE
        elif "payment" in content or "pay" in content or "bill" in content:
            task_type = TaskType.PAYMENT
        elif "research" in content or "search" in content or "find" in content:
            task_type = TaskType.RESEARCH
        else:
            task_type = TaskType.OTHER
        
        return {
            **state,
            "task_type": task_type,
            "status": TaskStatus.ANALYZING,
            "messages": state["messages"] + [response],
        }
    
    async def _search_for_proposal(self, wish: str, task_type: TaskType) -> list[dict]:
        """
        Phase 3A: タスクタイプに応じて実際の検索を行う
        
        Args:
            wish: ユーザーの願望
            task_type: タスクタイプ
            
        Returns:
            検索結果のリスト（SearchResult形式）
        """
        search_results = []
        
        try:
            # タスクタイプに応じて検索ツールを選択
            if task_type == TaskType.TRAVEL:
                # 交通関連: 駅名や日時を抽出して検索
                # TODO: より高度な抽出ロジック
                search_results = await search_train.ainvoke({
                    "departure": "東京",  # 仮のデフォルト
                    "arrival": "大阪",
                })
                
            elif task_type == TaskType.PURCHASE:
                # 購入関連: 商品名を抽出して検索
                # 願望からキーワードを抽出（簡易実装）
                keywords = wish.replace("買いたい", "").replace("欲しい", "").replace("購入", "").strip()
                if keywords:
                    search_results = await search_amazon.ainvoke({
                        "query": keywords,
                        "max_results": 5
                    })
                    
            elif task_type == TaskType.RESEARCH:
                # 調査関連: Tavily検索
                search_results = await tavily_search.ainvoke({
                    "query": wish,
                    "max_results": 5
                })
                
            else:
                # その他: 汎用Web検索
                search_results = await tavily_search.ainvoke({
                    "query": wish,
                    "max_results": 3
                })
                
        except Exception as e:
            logger.warning(f"Search failed: {e}")
            # 検索失敗時は空のリストを返す（フォールバック）
            search_results = []
        
        # エラー結果を除外
        search_results = [r for r in search_results if not r.get("error")]
        
        return search_results
    
    def _format_search_results_for_prompt(self, search_results: list[dict]) -> str:
        """検索結果をプロンプト用にフォーマット"""
        if not search_results:
            return "（検索結果なし - AIの推測で提案します）"
        
        formatted = []
        for i, r in enumerate(search_results[:5], 1):
            title = r.get("title", "不明")
            price = r.get("price")
            url = r.get("url", "")
            details = r.get("details", {})
            
            line = f"{i}. {title}"
            if price:
                line += f" - ¥{price:,}"
            if details.get("source"):
                line += f" ({details['source']})"
            formatted.append(line)
        
        return "\n".join(formatted)
    
    async def _propose_actions(self, state: AgentState) -> AgentState:
        """Propose actions to execute"""
        wish = state["original_wish"]
        task_type = state["task_type"]
        
        # Phase 3A: 実際の検索を行う
        search_results = await self._search_for_proposal(wish, task_type)
        search_results_text = self._format_search_results_for_prompt(search_results)
        
        proposal_prompt = f"""Propose a specific action for the following user request using Action First principle.

User request: {wish}
Task type: {task_type}

## Real Search Results (use these for your proposal)
{search_results_text}

Important rules:
- **Use the search results above** to make specific proposals with real data
- If search results are available, reference actual products/services/prices
- Never respond with questions (e.g., "What kind of X do you want?" is NOT allowed)
- Make assumptions and propose specific actions even with incomplete information
- List assumptions in [NOTES] so user can correct them

Respond in this format:

[ACTION]
(What you will do specifically)

[DETAILS]
(Specific content based on search results: actual products, real prices, real options)

[NOTES]
(Assumptions made, points that can be corrected)"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=proposal_prompt),
        ]
        response = await self.llm.ainvoke(messages)
        
        # Save full response
        content = response.content
        
        # Extract action section
        actions = []
        if "[ACTION]" in content:
            action_start = content.find("[ACTION]") + len("[ACTION]")
            action_end = content.find("[", action_start)
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
            "search_results": search_results,  # Phase 3A: 検索結果を保存
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
            "search_results": [],  # Phase 3A: 検索結果
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
                "search_results": final_state.get("search_results", []),  # Phase 3A
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
            "search_results": final_state.get("search_results", []),  # Phase 3A: 検索結果
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
        revision_prompt = f"""Revise the proposal based on the user's correction request.

## Original Request
{original_wish}

## Previous Proposal
{previous_proposal}

## User's Correction Request
{revision}

Important rules:
- Apply the correction request accurately
- Keep unchanged parts from the previous proposal
- Never respond with questions
- List assumptions in [NOTES]

Respond in this format:

[ACTION]
(What you will do specifically)

[DETAILS]
(Specific content: message text, booking details, items to purchase, etc.)

[NOTES]
(Assumptions made, points that can be corrected)"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=revision_prompt),
        ]
        response = await self.llm.ainvoke(messages)
        
        content = response.content
        
        # Extract action from response
        actions = []
        if "[ACTION]" in content:
            action_start = content.find("[ACTION]") + len("[ACTION]")
            action_end = content.find("[", action_start)
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
