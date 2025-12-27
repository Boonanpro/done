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
from app.services.supabase_client import get_supabase_client

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
    
    # キャッシュ用のメモリストレージ（高速アクセス用、DBと同期）
    _tasks_cache: dict[str, dict] = {}
    
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
    
    async def _get_task(self, task_id: str) -> Optional[dict]:
        """
        Get task from cache or DB.
        
        Args:
            task_id: Task ID
            
        Returns:
            Task data or None if not found
        """
        # Check cache first
        if task_id in AISecretaryAgent._tasks_cache:
            return AISecretaryAgent._tasks_cache[task_id]
        
        # Fallback to DB
        try:
            db = get_supabase_client()
            task = await db.get_task(task_id)
            if task:
                # Convert DB format to internal format
                task_data = {
                    "id": task["id"],
                    "user_id": task.get("user_id"),
                    "type": TaskType(task.get("type", "other")),
                    "status": TaskStatus(task.get("status", "pending")),
                    "original_wish": task.get("original_wish", ""),
                    "proposed_actions": task.get("proposed_actions", []),
                    "execution_result": task.get("execution_result"),
                    "search_results": task.get("search_results", []),
                    "created_at": task.get("created_at"),
                }
                # Cache it
                AISecretaryAgent._tasks_cache[task_id] = task_data
                return task_data
        except Exception as e:
            logger.error(f"Failed to get task from DB: {task_id}, error: {e}")
        
        return None
    
    async def _update_task(self, task_id: str, **updates) -> bool:
        """
        Update task in cache and DB.
        
        Args:
            task_id: Task ID
            **updates: Fields to update
            
        Returns:
            True if successful
        """
        # Update cache
        if task_id in AISecretaryAgent._tasks_cache:
            AISecretaryAgent._tasks_cache[task_id].update(updates)
        
        # Update DB
        try:
            db = get_supabase_client()
            # Convert enum values to strings for DB
            db_updates = {}
            for key, value in updates.items():
                if hasattr(value, 'value'):  # Enum
                    db_updates[key] = value.value
                else:
                    db_updates[key] = value
            await db.update_task(task_id, **db_updates)
            return True
        except Exception as e:
            logger.error(f"Failed to update task in DB: {task_id}, error: {e}")
            return False
    
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
        
        # TRAVEL must be checked first (before LINE) because "Bus Lines" contains "line"
        if "travel" in content or "train" in content or "shinkansen" in content or \
             "bus" in content or "bus" in wish_lower or "highway" in wish_lower or \
             "flight" in content or "book" in wish_lower or "yonago" in wish_lower or \
             "umeda" in wish_lower or "willer" in content or "reservation" in wish_lower:
            task_type = TaskType.TRAVEL
        elif "email" in content:
            task_type = TaskType.EMAIL
        elif "line message" in content or "send line" in content:
            task_type = TaskType.LINE
        elif "purchase" in content or "buy" in content:
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
        
        # Ensure search_results is a list
        if not isinstance(search_results, list):
            if isinstance(search_results, dict):
                search_results = [search_results] if not search_results.get("error") else []
            else:
                search_results = []
        
        # エラー結果を除外
        search_results = [r for r in search_results if isinstance(r, dict) and not r.get("error")]
        
        return search_results
    
    async def _generate_fallback_proposals(
        self, 
        wish: str, 
        task_type: TaskType,
        failed_action: str,
        error_message: str
    ) -> str:
        """
        Generate smart fallback proposals using LLM.
        
        Uses AI to suggest best alternatives based on:
        - Task type (travel, purchase, etc.)
        - Distance/context for travel tasks
        - What failed and why
        
        Args:
            wish: Original user wish
            task_type: Type of task (TRAVEL, PURCHASE, etc.)
            failed_action: What action failed
            error_message: Error message from the failed attempt
            
        Returns:
            Formatted string of ranked alternative options
        """
        try:
            # Build context-aware prompt for LLM
            fallback_prompt = f"""The user's request failed. Suggest alternative solutions.

## Original Request
{wish}

## Task Type
{task_type.value if task_type else "unknown"}

## What Failed
{failed_action}

## Error
{error_message}

## Your Task
Suggest 2-3 alternative solutions, ranked by recommendation.
Consider:
- For travel: distance, time, cost, convenience (e.g., short distance → taxi/train, long distance → shinkansen/flight)
- For purchases: alternative stores, similar products, different delivery options
- For other tasks: creative alternatives to achieve the same goal

## Response Format (Japanese)
🥇 **おすすめ**: [Best alternative with brief reason]
🥈 **次点**: [Second best alternative]
🥉 **その他**: [Other options if any]

Keep each option to 1-2 lines. Be specific and actionable."""

            response = await self.llm.ainvoke([
                SystemMessage(content="You are a helpful assistant suggesting alternatives when the primary option fails. Respond in Japanese."),
                HumanMessage(content=fallback_prompt)
            ])
            
            return response.content
            
        except Exception as e:
            logger.error(f"Fallback generation failed: {e}")
            # Simple fallback if LLM fails
            if task_type == TaskType.TRAVEL:
                return """🥇 **おすすめ**: Yahoo!乗換案内やGoogle Mapsで他のルートを検索
🥈 **次点**: 旅行代理店に相談（JTB、HISなど）
🥉 **その他**: 日程を変更して再検索"""
            elif task_type == TaskType.PURCHASE:
                return """🥇 **おすすめ**: 別のECサイト（楽天、Yahoo!ショッピング）で検索
🥈 **次点**: 類似商品を検索
🥉 **その他**: 実店舗での購入を検討"""
            else:
                return """🥇 **おすすめ**: 別のアプローチを試す
🥈 **次点**: 専門家に相談
🥉 **その他**: 目的を見直して再検討"""
    
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
        
        # Save task to Supabase DB (with cache)
        task_data = {
            "id": task_id,
            "user_id": user_id,
            "type": final_state["task_type"].value if final_state["task_type"] else "other",
            "status": final_state["status"].value if final_state["status"] else "pending",
            "original_wish": wish,
            "proposed_actions": final_state["proposed_actions"],
            "execution_result": final_state["execution_result"],
            "search_results": final_state.get("search_results", []),
            "created_at": datetime.utcnow(),
        }
        
        try:
            # Save to Supabase (直接挿入)
            db = get_supabase_client()
            db_data = {
                "id": task_id,
                "user_id": user_id,
                "type": task_data["type"],
                "status": task_data["status"],
                "original_wish": wish,
                "proposed_actions": task_data["proposed_actions"],
                "execution_result": task_data["execution_result"],
            }
            db.client.table("tasks").insert(db_data).execute()
            logger.info(f"Task saved to DB: {task_id}")
        except Exception as e:
            logger.error(f"Failed to save task to DB {task_id}: {e}", exc_info=True)
            logger.warning(f"Task {task_id} will be saved to memory only")
        
        # Always cache in memory for fast access
        AISecretaryAgent._tasks_cache[task_id] = task_data
        
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
        """Execute confirmed task using appropriate Executor"""
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        task["status"] = TaskStatus.EXECUTING
        await self._update_task(task_id, status=TaskStatus.EXECUTING)
        logger.info(f"Executing task: {task_id}, type: {task.get('type')}")
        
        try:
            # タスクタイプに応じてExecutorを選択
            task_type = task.get("type")
            search_results = task.get("search_results", [])
            
            # 検索結果からSearchResultオブジェクトを作成
            from app.models.schemas import SearchResult
            from app.executors.base import ExecutorFactory
            
            execution_result = None
            
            if task_type == TaskType.TRAVEL:
                # 交通関連: バス/電車のExecutorを使用
                # 願望からカテゴリを判定（検索結果よりも優先）
                original_wish = task.get("original_wish", "").lower()
                
                if "bus" in original_wish or "バス" in original_wish:
                    category = "bus"
                    service_name = "willer"
                elif "train" in original_wish or "新幹線" in original_wish or "電車" in original_wish:
                    category = "train"
                    service_name = "ex_reservation"
                else:
                    # 検索結果からカテゴリを判定
                    category = "bus"  # デフォルトはバス
                    service_name = "willer"
                    
                    for sr in search_results:
                        if sr.get("category") == "train":
                            category = "train"
                            service_name = "ex_reservation"
                            break
                        elif sr.get("category") == "bus":
                            category = "bus"
                            service_name = "willer"
                            break
                
                print(f"[AGENT DEBUG] Travel category: {category}, service: {service_name}")
                
                # Executorを取得
                executor = ExecutorFactory.get_executor(category, service_name)
                
                # 最初の検索結果を使用（または願望から詳細を抽出）
                original_wish = task["original_wish"]
                if search_results:
                    first_result = search_results[0]
                    # 元のwishをdetailsに追加して渡す
                    result_details = first_result.get("details", {}).copy() if first_result.get("details") else {}
                    result_details["raw_wish"] = original_wish
                    
                    search_result_obj = SearchResult(
                        id=first_result.get("id", task_id),
                        service_name=service_name,
                        category=category,
                        title=original_wish,  # 常に元のwishを使用
                        url=first_result.get("url"),
                        details=result_details,
                    )
                else:
                    # 検索結果がない場合は願望から推測
                    search_result_obj = SearchResult(
                        id=task_id,
                        service_name=service_name,
                        category=category,
                        title=original_wish,
                        details={"raw_wish": original_wish},
                    )
                
                # 実行（認証情報なしで開始、必要に応じて要求される）
                execution_result = await executor.execute(
                    task_id=task_id,
                    user_id=task.get("user_id") or "default-user",
                    search_result=search_result_obj,
                    credentials=None,
                )
                
            elif task_type == TaskType.PURCHASE:
                # 購入関連: Amazon/楽天のExecutorを使用
                executor = ExecutorFactory.get_executor("product", "amazon")
                
                if search_results:
                    first_result = search_results[0]
                    search_result_obj = SearchResult(
                        id=first_result.get("id", task_id),
                        service_name="amazon",
                        category="product",
                        title=first_result.get("title", ""),
                        url=first_result.get("url"),
                        price=first_result.get("price"),
                        details=first_result.get("details", {}),
                    )
                    
                    execution_result = await executor.execute(
                        task_id=task_id,
                        user_id=task.get("user_id") or "default-user",
                        search_result=search_result_obj,
                        credentials=None,
                    )
            
            # 実行結果を保存
            if execution_result:
                exec_result_data = {
                    "success": execution_result.success,
                    "message": execution_result.message,
                    "confirmation_number": execution_result.confirmation_number,
                    "details": execution_result.details,
                }
                new_status = TaskStatus.COMPLETED if execution_result.success else TaskStatus.FAILED
                task["execution_result"] = exec_result_data
                task["status"] = new_status
                logger.info(f"Task {task_id} execution result: {execution_result.success}")
                
                # ★ Smart Fallback: Generate alternatives for any failed task
                if not execution_result.success:
                    failed_action = task.get("proposed_actions", ["Unknown action"])[0] if task.get("proposed_actions") else "Unknown action"
                    alternatives = await self._generate_fallback_proposals(
                        wish=original_wish,
                        task_type=task_type,
                        failed_action=failed_action,
                        error_message=execution_result.message
                    )
                    if alternatives:
                        task["execution_result"]["alternatives"] = alternatives
                        task["execution_result"]["message"] += f"\n\n📋 **代替案**:\n{alternatives}"
                        exec_result_data = task["execution_result"]
                        logger.info(f"Task {task_id}: Generated fallback proposals")
                
                # Save to DB
                await self._update_task(task_id, status=new_status, execution_result=exec_result_data)
            else:
                # Executorが対応していないタスクタイプ
                task["execution_result"] = {
                    "success": False,
                    "message": f"Automatic execution for task type '{task_type}' is not yet supported",
                }
                task["status"] = TaskStatus.COMPLETED
            
            return {
                "status": task["status"].value,
                "task_id": task_id,
                "result": task["execution_result"],
            }
            
        except Exception as e:
            import traceback
            error_trace = traceback.format_exc()
            print(f"[AGENT ERROR] Task {task_id} failed:\n{error_trace}")
            logger.error(f"Task execution failed: {task_id}, error: {e}", exc_info=True)
            task["status"] = TaskStatus.FAILED
            task["execution_result"] = {
                "success": False,
                "message": f"Execution error: {str(e)}",
                "traceback": error_trace,
            }
            return {
                "status": "failed",
                "task_id": task_id,
                "error": str(e),
                "traceback": error_trace,
            }
    
    async def revise_task(self, task_id: str, revision: str) -> dict[str, Any]:
        """
        Revise an existing task based on user feedback.
        
        This method:
        1. Merges original wish with revision to create a new wish
        2. Re-analyzes task type
        3. Re-searches with new parameters
        4. Generates new proposal based on fresh search results
        
        Args:
            task_id: The ID of the task to revise
            revision: The revision request (e.g., "鳥取市までで良いからバスか電車で探して")
        
        Returns:
            Updated task with new proposal based on real search results
        """
        task = await self._get_task(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        original_wish = task["original_wish"]
        previous_proposal = task.get("execution_result", {}).get("full_proposal", "")
        
        # Step 1: Generate a merged wish that incorporates the revision
        merge_prompt = f"""Combine the original request with the user's correction to create a single, clear request.

Original request: {original_wish}
User's correction: {revision}

Output ONLY the merged request as a single sentence. No explanation needed.
Example: "Book a bus from Osaka to Tottori City on December 30th"
"""
        merge_response = await self.llm.ainvoke([
            HumanMessage(content=merge_prompt)
        ])
        merged_wish = merge_response.content.strip()
        logger.info(f"Merged wish: {merged_wish}")
        
        # Step 2: Re-analyze task type
        task_type = await self._analyze_wish(merged_wish)
        task["type"] = task_type
        task["original_wish"] = merged_wish  # Update with merged wish
        logger.info(f"Re-analyzed task type: {task_type}")
        
        # Step 3: Re-search with new parameters
        search_results = await self._search_for_proposal(merged_wish, task_type)
        search_results_text = self._format_search_results_for_prompt(search_results)
        task["search_results"] = search_results
        logger.info(f"Re-search completed: {len(search_results)} results")
        
        # Step 4: Generate new proposal based on fresh search results
        proposal_prompt = f"""Propose a specific action for the revised user request using Action First principle.

## Revised Request (after user correction)
{merged_wish}

## Original Request
{original_wish}

## User's Correction
{revision}

## Real Search Results (use these for your proposal)
{search_results_text}

Important rules:
- **Use the search results above** to make specific proposals with real data
- If search results are available, reference actual products/services/prices
- The user corrected their request, so prioritize their new requirements
- Never respond with questions
- List assumptions in [NOTES]

Respond in this format:

[ACTION]
(What you will do specifically)

[DETAILS]
(Specific content based on search results: actual options, real prices)

[NOTES]
(Assumptions made, points that can be corrected)"""
        
        messages = [
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=proposal_prompt),
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
        task["search_results"] = search_results
        
        # Save to DB
        await self._update_task(
            task_id,
            proposed_actions=actions,
            execution_result={"full_proposal": content},
            status=TaskStatus.PROPOSED,
            original_wish=merged_wish,
            type=task_type,
        )
        
        logger.info(f"Task revised with re-search: {task_id}")
        
        return {
            "task_id": task_id,
            "message": "Proposal revised based on your feedback with fresh search results. Please confirm to execute, or request further revisions.",
            "proposed_actions": actions,
            "proposal_detail": content,
            "requires_confirmation": True,
            "search_results": search_results,
        }
    
    async def get_task(self, task_id: str) -> Optional[TaskResponse]:
        """Get task from cache or DB"""
        task = await self._get_task(task_id)
        if not task:
            return None
        
        task_type = task["type"]
        if isinstance(task_type, str):
            task_type = TaskType(task_type) if task_type else TaskType.OTHER
        
        task_status = task["status"]
        if isinstance(task_status, str):
            task_status = TaskStatus(task_status) if task_status else TaskStatus.PENDING
        
        return TaskResponse(
            id=task["id"],
            user_id=task["user_id"],
            type=task_type or TaskType.OTHER,
            status=task_status,
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
        """Get task list from DB"""
        try:
            db = get_supabase_client()
            tasks = await db.list_tasks(user_id=user_id, limit=limit)
        except Exception as e:
            logger.error(f"Failed to list tasks from DB: {e}")
            # Fallback to cache
            tasks = list(AISecretaryAgent._tasks_cache.values())
            if user_id:
                tasks = [t for t in tasks if t.get("user_id") == user_id]
            tasks = sorted(tasks, key=lambda t: t.get("created_at", datetime.min), reverse=True)[:limit]
        
        result = []
        for t in tasks:
            task_type = t.get("type", "other")
            if isinstance(task_type, str):
                task_type = TaskType(task_type) if task_type else TaskType.OTHER
            
            task_status = t.get("status", "pending")
            if isinstance(task_status, str):
                task_status = TaskStatus(task_status) if task_status else TaskStatus.PENDING
            
            result.append(TaskResponse(
                id=t["id"],
                user_id=t.get("user_id"),
                type=task_type or TaskType.OTHER,
                status=task_status,
                original_wish=t.get("original_wish", ""),
                proposed_actions=t.get("proposed_actions", []),
                execution_result=t.get("execution_result"),
                created_at=t.get("created_at"),
            ))
        
        return result
