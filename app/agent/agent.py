"""
AI Secretary Agent - LangGraph Implementation

Step 6: StateMachine統合
- process_with_state_machine(): 新しい状態機械ベースの処理
- 既存のprocess_wish()は後方互換性のため維持
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
- make_phone_call: Make phone calls (AI will have the conversation on behalf of the user)

## Phone Call Capability
You can make phone calls on behalf of the user. When a user requests something that requires a phone call (e.g., "call the restaurant to make a reservation"), you can execute it. The AI will:
1. Call the specified number
2. Have the conversation (reservation, inquiry, etc.)
3. Report the results back to the user

Use phone calls when:
- User explicitly requests it ("電話して", "call them", etc.)
- Web booking is not available and phone is the only option
- User preference is for phone contact

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

Always respond in the same language as the user's message.
Keep [ACTION], [DETAILS], [NOTES] tags in English for parsing."""

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
- phone: Phone call related (call someone, make reservation by phone, etc.)
- travel: Travel/transportation related (train, bus, flight reservations)
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
        
        # PHONE must be checked first (user explicitly wants phone call)
        phone_keywords = ["電話して", "電話で", "電話をかけて", "架電", "コールして", 
                         "call ", "phone ", "call the", "phone the", "電話予約"]
        if any(kw in wish_lower for kw in phone_keywords) or "phone" in content:
            task_type = TaskType.PHONE
        # TRAVEL must be checked before LINE because "Bus Lines" contains "line"
        # 日本語キーワードも含む
        travel_keywords_ja = ["新幹線", "電車", "特急", "飛行機", "航空", "バス", "高速バス", 
                              "予約", "チケット", "乗車券", "切符", "行きたい", "移動"]
        travel_keywords_en = ["travel", "train", "shinkansen", "bus", "highway", 
                              "flight", "book", "reservation", "willer"]
        if any(kw in wish_lower for kw in travel_keywords_ja) or \
           any(kw in content for kw in travel_keywords_en):
            task_type = TaskType.TRAVEL
        elif "email" in content or "メール" in wish_lower:
            task_type = TaskType.EMAIL
        elif "line message" in content or "send line" in content or "line送" in wish_lower:
            task_type = TaskType.LINE
        elif "purchase" in content or "buy" in content or "買" in wish_lower or "購入" in wish_lower:
            task_type = TaskType.PURCHASE
        elif "payment" in content or "pay" in content or "bill" in content or "支払" in wish_lower:
            task_type = TaskType.PAYMENT
        elif "research" in content or "search" in content or "find" in content or \
             "調べ" in wish_lower or "検索" in wish_lower:
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
            if task_type == TaskType.PHONE:
                # 電話関連: 電話番号と目的を抽出
                from app.executors.voice_executor import extract_phone_number
                
                phone_number = extract_phone_number(wish)
                
                # AIで電話の目的と相手を抽出
                phone_context = await self._extract_phone_context(wish)
                
                search_results = [{
                    "id": str(uuid.uuid4()),
                    "category": "phone",
                    "title": phone_context.get("target", "電話をかける"),
                    "description": wish,
                    "details": {
                        "phone_number": phone_number,
                        "purpose": phone_context.get("purpose", "inquiry"),
                        "target_name": phone_context.get("target", ""),
                        "context": phone_context,
                    }
                }]
                
            elif task_type == TaskType.TRAVEL:
                # 交通関連: LLMで駅名や日時を抽出して検索
                travel_params = await self._extract_travel_params(wish)
                logger.info(f"Extracted travel params: {travel_params}")
                
                departure = travel_params.get("departure", "")
                arrival = travel_params.get("arrival", "")
                
                if departure and arrival:
                    transport_type = travel_params.get("transport_type", "shinkansen")
                    
                    if transport_type in ["shinkansen", "train"]:
                        search_results = await search_train.ainvoke({
                            "departure": departure,
                            "arrival": arrival,
                        })
                    elif transport_type == "bus":
                        search_results = await search_bus.ainvoke({
                            "departure": departure,
                            "arrival": arrival,
                        })
                    elif transport_type == "flight":
                        search_results = await search_flight.ainvoke({
                            "departure": departure,
                            "arrival": arrival,
                        })
                    else:
                        search_results = await search_train.ainvoke({
                            "departure": departure,
                            "arrival": arrival,
                        })
                    
                    logger.info(f"Raw search results: {search_results}")
                    
                    # 抽出したパラメータを検索結果に追加
                    if search_results:
                        for r in search_results:
                            if isinstance(r, dict):
                                r["extracted_params"] = travel_params
                else:
                    logger.warning(f"Could not extract departure/arrival from: {wish}")
                
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
{task_type.value if hasattr(task_type, 'value') else (task_type or "unknown")}

## What Failed
{failed_action}

## Error
{error_message}

## Your Task
Suggest 2-3 alternative solutions, ranked by recommendation.
Consider:
- For travel: distance, time, cost, convenience (e.g., short distance → taxi/train, long distance → shinkansen/flight)
- For purchases: alternative stores, similar products, different delivery options
- For reservations: phone call as an alternative (user can say "電話で予約して" to have AI call)
- For other tasks: creative alternatives to achieve the same goal
- Phone calls are available: AI can make calls on behalf of user for reservations/inquiries

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
🥈 **次点**: 電話で直接予約（「電話で予約して」と言ってください）
🥉 **その他**: 日程を変更して再検索"""
            elif task_type == TaskType.PURCHASE:
                return """🥇 **おすすめ**: 別のECサイト（楽天、Yahoo!ショッピング）で検索
🥈 **次点**: 類似商品を検索
🥉 **その他**: 実店舗での購入を検討"""
            elif task_type == TaskType.PHONE:
                return """🥇 **おすすめ**: 電話番号を確認して再度お試しください
🥈 **次点**: Webサイトから予約・問い合わせ
🥉 **その他**: メールでお問い合わせ"""
            else:
                return """🥇 **おすすめ**: 別のアプローチを試す
🥈 **次点**: 電話でお問い合わせ（「電話して」と言ってください）
🥉 **その他**: 目的を見直して再検討"""
    
    async def _extract_travel_params(self, wish: str) -> dict:
        """
        旅行タスクのパラメータを抽出
        
        Args:
            wish: ユーザーの願望
            
        Returns:
            出発地、到着地、日時などの情報
        """
        try:
            from datetime import datetime, timedelta
            today = datetime.now().strftime("%Y-%m-%d")
            tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
            
            extract_prompt = f"""Analyze the following travel request and extract booking parameters.

Request: {wish}

Today's date: {today}

Extract:
1. departure: Departure station/location (in Japanese, e.g., "新大阪", "東京")
2. arrival: Arrival station/location (in Japanese, e.g., "広島", "博多")
3. date: Travel date in YYYY-MM-DD format (use {today} for "今日", {tomorrow} for "明日")
4. time: Preferred departure time (e.g., "10:00", "morning" -> "09:00", "evening" -> "17:00")
5. seat_class: Seat class ("ordinary" for 普通車/指定席, "green" for グリーン車)
6. transport_type: Type of transport ("shinkansen", "train", "bus", "flight")

Respond in JSON format only:
{{"departure": "...", "arrival": "...", "date": "YYYY-MM-DD", "time": "HH:MM", "seat_class": "ordinary|green", "transport_type": "shinkansen|train|bus|flight"}}"""

            response = await self.llm.ainvoke([
                SystemMessage(content="You are an assistant that extracts travel booking parameters. Respond only in valid JSON."),
                HumanMessage(content=extract_prompt)
            ])
            
            import json
            content = response.content.strip()
            # JSON部分を抽出
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            return json.loads(content)
            
        except Exception as e:
            logger.warning(f"Failed to extract travel params: {e}")
            return {
                "departure": "",
                "arrival": "",
                "date": "",
                "time": "",
                "seat_class": "ordinary",
                "transport_type": "shinkansen"
            }
    
    async def _extract_phone_context(self, wish: str) -> dict:
        """
        電話タスクのコンテキストを抽出
        
        Args:
            wish: ユーザーの願望
            
        Returns:
            電話の目的、相手、詳細情報
        """
        try:
            extract_prompt = f"""Analyze the following request and extract phone call information.

Request: {wish}

Extract:
1. target: Who to call (restaurant name, company, clinic, etc.)
2. purpose: Purpose of call (reservation, inquiry, cancellation, confirmation, other)
3. details: Any specific details (date, time, number of people, etc.)

Respond in JSON format only:
{{"target": "...", "purpose": "reservation|inquiry|cancellation|confirmation|other", "details": {{...}}}}"""

            response = await self.llm.ainvoke([
                SystemMessage(content="You are an assistant that extracts phone call information. Respond only in valid JSON."),
                HumanMessage(content=extract_prompt)
            ])
            
            import json
            content = response.content.strip()
            # JSON部分を抽出
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            return json.loads(content)
            
        except Exception as e:
            logger.warning(f"Failed to extract phone context: {e}")
            return {
                "target": "",
                "purpose": "inquiry",
                "details": {}
            }
    
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
            original_wish = task.get("original_wish", "")
            
            if task_type == TaskType.PHONE:
                # 電話関連: VoiceExecutorを使用
                executor = ExecutorFactory.get_executor("phone")
                
                # 検索結果から電話情報を取得
                phone_details = {}
                if search_results:
                    first_result = search_results[0]
                    phone_details = first_result.get("details", {})
                
                search_result_obj = SearchResult(
                    id=task_id,
                    category="phone",
                    title=phone_details.get("target_name") or original_wish,
                    details={
                        **phone_details,
                        "user_id": task.get("user_id") or "default-user",
                        "raw_wish": original_wish,
                    },
                )
                
                execution_result = await executor.execute(
                    task_id=task_id,
                    user_id=task.get("user_id") or "default-user",
                    search_result=search_result_obj,
                    credentials=None,
                )
                
            elif task_type == TaskType.TRAVEL:
                # 交通関連: バス/電車のExecutorを使用
                # 願望からカテゴリを判定（検索結果よりも優先）
                original_wish_lower = original_wish.lower()
                
                if "bus" in original_wish_lower or "バス" in original_wish_lower:
                    category = "bus"
                    service_name = "willer"
                elif "train" in original_wish_lower or "新幹線" in original_wish_lower or "電車" in original_wish_lower:
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
    
    # ========================================
    # Architecture v2: 推論ファースト・Executor実行フロー
    # ========================================
    
    async def process_wish_v2(
        self,
        wish: str,
        user_id: str,
        request_id: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> dict:
        """
        Architecture v2: 推論ファースト・Executor実行フロー
        
        1. 推論 + Web検索で最適解を導出
        2. ExecutorRegistryで最適解を実現できるExecutorを探す
        3. Executor.search() で予約可能かを確認
        4. 予約可能なら提案を生成
        
        Args:
            wish: ユーザーの願望
            user_id: ユーザーID
            request_id: プログレス通知用ID
            conversation_history: 同一セッション内の会話履歴（直近のメッセージリスト）
            
        Returns:
            処理結果
        """
        from app.executors.registry import ExecutorRegistry, register_all_executors
        from app.services.progress_callback import notify_progress
        
        # Executorを登録
        register_all_executors()
        
        # 会話履歴がない場合は空リスト
        if conversation_history is None:
            conversation_history = []
        
        logger.info(f"[PROCESS_V2] Starting process_wish_v2 for: {wish}, history_count: {len(conversation_history)}")
        
        result = {
            "success": False,
            "phase": "research",
            "research_result": None,
            "executor_found": False,
            "search_result": None,
            "proposal": None,
            "message": "",
        }
        
        try:
            # ========================================
            # Step 1: 推論 + Web検索で最適解を導出
            # ========================================
            if request_id:
                await notify_progress(
                    request_id, "thinking", "考え中...", "running"
                )
            
            research = await self._research_optimal_solution(wish, conversation_history)
            result["research_result"] = research
            
            # 根拠を含んだプログレスメッセージを生成
            params = research.get("params", {})
            service_name = research.get("service_display_name", "")
            
            if research.get("task_type") == "travel":
                departure = params.get("departure", "")
                arrival = params.get("arrival", "")
                transport_type = params.get("transport_type", "")
                date = params.get("date", "")
                time = params.get("time", "")
                seat_class = params.get("seat_class", "ordinary")
                
                # 交通手段の日本語
                transport_ja = {
                    "shinkansen": "新幹線",
                    "train": "電車",
                    "bus": "高速バス",
                    "flight": "飛行機"
                }.get(transport_type, "交通機関")
                
                # 根拠付きメッセージ（ユーザーの意図を読み取った表現）
                reasoning_msg = f"{transport_ja}で{departure}から{arrival}まで行きたいようなので、{service_name}で予約します"
                if request_id:
                    await notify_progress(request_id, "reasoning", reasoning_msg, "completed")
                
                # 時間の仮定を表示（理由付き）
                if not time:
                    time_msg = "時間の指定が無いのでとりあえず17時台で探します"
                    if request_id:
                        await notify_progress(request_id, "assumption_time", time_msg, "completed")
                else:
                    time_msg = f"{time}頃の便を探します"
                    if request_id:
                        await notify_progress(request_id, "assumption_time", time_msg, "completed")
                
                # 座席の仮定を表示（理由付き）
                if seat_class == "green":
                    seat_msg = "グリーン車を希望されているのでグリーン車で探します"
                else:
                    seat_msg = "座席の指定が無いですが、普通車の指定席を使われることが多いので今回も指定席で探します"
                if request_id:
                    await notify_progress(request_id, "assumption_seat", seat_msg, "completed")
            
            elif research.get("task_type") == "purchase":
                query = params.get("query", "")
                reasoning_msg = f"「{query}」を購入したいようなので、{service_name}で検索します"
                if request_id:
                    await notify_progress(request_id, "reasoning", reasoning_msg, "completed")
            
            elif research.get("task_type") == "research":
                # 調査・検索タイプの場合
                goal = params.get("goal", wish)
                steps = params.get("steps", [])
                
                if request_id:
                    await notify_progress(
                        request_id, "reasoning",
                        f"「{goal}」を実現するために情報を調査します",
                        "completed"
                    )
                
                # 計画したステップを表示
                if steps and request_id:
                    step_summary = "、".join([s.get("action", "") for s in steps[:3]])
                    await notify_progress(
                        request_id, "plan",
                        f"計画: {step_summary}",
                        "completed"
                    )
            
            else:
                if request_id:
                    await notify_progress(
                        request_id, "reasoning",
                        f"{service_name}で対応します",
                        "completed"
                    )
            
            # ========================================
            # Step 2: Executorを探す
            # ========================================
            logger.info(f"[PROCESS_V2] Research result: {research}")
            logger.info(f"[PROCESS_V2] Looking for executor with service_type={research.get('service_type')}, service_name={research.get('service_name')}")
            
            executor = ExecutorRegistry.get_executor_for_solution(research)
            logger.info(f"[PROCESS_V2] Found executor: {executor}")
            
            if not executor:
                # Executorが見つからない場合 → ツールベースのアクションを試みる
                logger.info(f"[PROCESS_V2] No executor found, checking for tool-based action")

                # イシューを記録
                try:
                    from app.services.issue_tracker import IssueTracker, Issue, IssueType
                    issue_tracker = IssueTracker()
                    await issue_tracker.record_issue(Issue(
                        issue_type=IssueType.EXECUTOR_MISSING,
                        original_wish=wish,
                        service_type=research.get("service_type"),
                        service_name=research.get("service_name"),
                        research_result=research,
                        error_message=f"Executor not found for {research.get('service_name') or research.get('service_type')}",
                        error_details={
                            "research_result": research,
                        },
                        user_id=user_id,
                    ))
                    logger.info(f"[ISSUE] Recorded EXECUTOR_MISSING issue for {research.get('service_name')}")
                except Exception as e:
                    logger.error(f"[ISSUE] Failed to record issue: {e}")

                # ツールを使ったアクションが可能か確認
                if research.get("requires_tools", False) or research.get("params", {}).get("actionable", False):
                    # ツールベースのアクション提案を生成
                    result["phase"] = "tool_based_action"

                    if request_id:
                        await notify_progress(
                            request_id, "tool_action",
                            "利用可能なツールでアクションを提案します",
                            "running"
                        )

                    # ツールを使ったアクション提案を生成
                    proposal = await self._generate_tool_based_proposal(wish, research, request_id, conversation_history)
                    result["proposal"] = proposal
                    result["success"] = True

                    if request_id:
                        await notify_progress(
                            request_id, "proposal_ready",
                            "アクションを提案しました",
                            "completed"
                        )

                    return result
                else:
                    # フィジカルな作業が必要、または対応不可
                    result["phase"] = "no_executor"
                    result["message"] = f"自動実行機能はまだ対応していません。手動で対応をお願いします。"

                    if request_id:
                        await notify_progress(
                            request_id, "no_executor",
                            f"{service_name}の自動実行は未対応です。手順をお伝えします",
                            "completed"
                        )

                    # 手動対応の提案を生成
                    proposal = await self._generate_manual_proposal(wish, research)
                    result["proposal"] = proposal
                    result["success"] = True
                    return result
            
            result["executor_found"] = True
            
            # ========================================
            # Step 3: Executor.search() で予約可能かを確認
            # ========================================
            logger.info(f"[PROCESS_V2] Calling executor.search() with params: {params}")
            
            if request_id:
                executor.set_request_id(request_id)
            
            search_result = await executor.search(params)
            logger.info(f"[PROCESS_V2] Search result: success={search_result.success}, options={len(search_result.options)}")
            result["search_result"] = search_result.to_dict()
            
            if not search_result.success or not search_result.options:
                # 検索失敗または結果なし
                result["phase"] = "search_failed"
                result["message"] = search_result.message or "該当する便が見つかりませんでした"

                # イシューを記録（セレクタが古い可能性）
                try:
                    from app.services.issue_tracker import IssueTracker, Issue, IssueType
                    issue_tracker = IssueTracker()
                    await issue_tracker.record_issue(Issue(
                        issue_type=IssueType.SEARCH_FAILED,
                        original_wish=wish,
                        service_type=research.get("service_type"),
                        service_name=research.get("service_name"),
                        research_result=research,
                        error_message=f"Search failed: {search_result.message}",
                        error_details={
                            "search_params": params,
                            "search_result": search_result.to_dict(),
                        },
                        user_id=user_id,
                    ))
                    logger.info(f"[ISSUE] Recorded SEARCH_FAILED issue for {research.get('service_name')}")
                except Exception as e:
                    logger.error(f"[ISSUE] Failed to record issue: {e}")

                if request_id:
                    await notify_progress(
                        request_id, "search_failed",
                        result["message"],
                        "error"
                    )

                return result
            
            # ========================================
            # Step 4: 検索結果から最良を選択（根拠付き）
            # ========================================
            best_option = search_result.options[0]
            option_count = len(search_result.options)
            
            if request_id:
                # 検索結果の表示（根拠付き）
                if research.get("task_type") == "travel":
                    time_range = params.get("time", "17時")
                    if not time_range:
                        time_range = "17時"
                    await notify_progress(
                        request_id, "search_result",
                        f"{time_range}台で予約可能な便が{option_count}件見つかりました",
                        "completed"
                    )
                else:
                    await notify_progress(
                        request_id, "search_result",
                        f"候補が{option_count}件見つかりました",
                        "completed"
                    )
                
                # 選択理由を表示（なぜこれを選んだかの根拠）
                if research.get("task_type") == "travel":
                    selection_reason = f"特に指定が無いので最初の候補「{best_option.title}」を予約します"
                    if best_option.price:
                        selection_reason = f"特に指定が無いのでひとまず「{best_option.title}」（¥{best_option.price:,}）を予約します"
                else:
                    selection_reason = f"「{best_option.title}」を選択します"
                    if best_option.price:
                        selection_reason += f"（¥{best_option.price:,}）"
                
                await notify_progress(
                    request_id, "selection",
                    selection_reason,
                    "completed"
                )
            
            # ========================================
            # Step 5: 提案を生成
            # ========================================
            proposal = await self._generate_proposal_from_search(
                wish=wish,
                research=research,
                search_result=search_result,
                executor=executor,
            )
            result["proposal"] = proposal
            result["phase"] = "proposed"
            result["success"] = True
            
            return result
            
        except Exception as e:
            logger.error(f"process_wish_v2 error: {e}")
            result["message"] = f"エラーが発生しました: {str(e)}"
            
            if request_id:
                await notify_progress(
                    request_id, "error", result["message"], "error"
                )
            
            return result
    
    async def _research_optimal_solution(self, wish: str, conversation_history: list[dict] = None) -> dict:
        """
        推論 + Web検索で最適解を導出
        
        Args:
            wish: ユーザーの願望
            conversation_history: 同一セッション内の会話履歴
            
        Returns:
            最適解の情報
        """
        if conversation_history is None:
            conversation_history = []
        
        # まずタスクタイプを分析
        task_type = await self._determine_task_type(wish, conversation_history)
        
        # タスクタイプに応じてパラメータを抽出
        if task_type == TaskType.TRAVEL:
            params = await self._extract_travel_params(wish)
            transport_type = params.get("transport_type", "train")
            
            # サービスタイプとサービス名を決定
            if transport_type == "flight":
                service_type = "airline"
                service_name = None  # まだ特定のサービスは決めない
                service_display_name = "航空券検索"
            elif transport_type == "bus":
                service_type = "bus"
                service_name = "willer"
                service_display_name = "WILLER TRAVEL"
            else:  # train, shinkansen
                service_type = "train"
                service_name = "ex_reservation"
                service_display_name = "EX予約"
            
            return {
                "task_type": task_type.value,
                "service_type": service_type,
                "service_name": service_name,
                "service_display_name": service_display_name,
                "params": params,
                "original_wish": wish,
            }
        
        elif task_type == TaskType.PURCHASE:
            # 商品購入の場合
            keywords = wish.replace("買いたい", "").replace("欲しい", "").replace("購入", "").strip()
            
            return {
                "task_type": task_type.value,
                "service_type": "product",
                "service_name": "amazon",
                "service_display_name": "Amazon",
                "params": {
                    "query": keywords,
                },
                "original_wish": wish,
            }
        
        elif task_type == TaskType.PHONE:
            # 電話の場合
            phone_context = await self._extract_phone_context(wish)
            
            return {
                "task_type": task_type.value,
                "service_type": "voice",
                "service_name": "phone",
                "service_display_name": "電話発信",
                "params": phone_context,
                "original_wish": wish,
            }
        
        elif task_type == TaskType.RESEARCH:
            # 調査・検索が必要な場合（サービス探し、比較、雇用など）
            # LLMで必要なアクションを分析
            action_plan = await self._analyze_required_actions(wish, conversation_history)
            
            return {
                "task_type": task_type.value,
                "service_type": "research",
                "service_name": "web_research",
                "service_display_name": "Web調査",
                "params": action_plan,
                "original_wish": wish,
                "requires_tools": True,  # ツールを使用したアクションが必要
            }
        
        else:
            # その他の場合もLLMで分析してアクション可能か判断
            action_plan = await self._analyze_required_actions(wish, conversation_history)
            
            return {
                "task_type": task_type.value,
                "service_type": "generic",
                "service_name": None,
                "service_display_name": "汎用対応",
                "params": action_plan,
                "original_wish": wish,
                "requires_tools": action_plan.get("actionable", False),
            }
    
    def _format_conversation_history(self, conversation_history: list[dict], max_messages: int = 10) -> str:
        """
        会話履歴をLLMプロンプト用にフォーマット
        
        Args:
            conversation_history: 会話履歴のリスト（各要素は sender_type, content を含む）
            max_messages: 最大メッセージ数
            
        Returns:
            フォーマットされた会話履歴文字列
        """
        if not conversation_history:
            return "（会話履歴なし - 新しい会話の開始）"
        
        # 直近のメッセージのみを使用
        recent_history = conversation_history[-max_messages:] if len(conversation_history) > max_messages else conversation_history
        
        lines = []
        for msg in recent_history:
            sender_type = msg.get("sender_type", "unknown")
            content = msg.get("content", "")
            sender_name = msg.get("sender_name", "")
            
            if sender_type == "human" or sender_type == "user":
                prefix = "ユーザー"
            elif sender_type == "ai" or sender_type == "assistant":
                prefix = "ダン"
            else:
                prefix = sender_name or sender_type
            
            # 長すぎるメッセージは省略
            if len(content) > 500:
                content = content[:500] + "..."
            
            lines.append(f"{prefix}: {content}")
        
        return "\n".join(lines)
    
    async def _analyze_required_actions(self, wish: str, conversation_history: list[dict] = None) -> dict:
        """
        LLMで要望を実現するために必要なアクションを分析
        
        Args:
            wish: ユーザーの願望
            conversation_history: 同一セッション内の会話履歴
        
        Returns:
            {
                "actionable": bool,  # Webツールで対応可能か
                "steps": [...],  # 必要なステップ
                "tools_needed": [...],  # 必要なツール
                "search_query": str,  # 最初の検索クエリ
                "goal": str,  # 最終目標
            }
        """
        if conversation_history is None:
            conversation_history = []
        
        # 会話履歴をフォーマット
        history_text = self._format_conversation_history(conversation_history)
        
        analysis_prompt = f"""ユーザーのリクエストを分析し、Web上で実行可能なアクションプランを作成してください。

## 直近の会話履歴（このセッション内のみ）
{history_text}

## 現在のリクエスト
{wish}

## 利用可能なツール
1. search_web: Web検索（情報収集、サービス探し）
2. send_email: メール送信（問い合わせ、申し込み）
3. browse_website: Webサイト閲覧（詳細確認、フォーム入力）
4. make_phone_call: 電話発信（AI音声での問い合わせ）

## 分析基準
- フィジカルな作業（実際に会う、物を運ぶなど）が必要 → actionable: false
- Web上で完結できる（調査、問い合わせ、予約など） → actionable: true
- 情報収集が必要 → search_webを使用
- 問い合わせが必要 → send_emailまたはmake_phone_callを使用

## 重要な注意事項
- **与えられた会話履歴のみに基づいて判断してください**
- **会話履歴にない情報を推測・捏造しないでください**
- **別のセッションや過去の会話を想像しないでください**
- 会話履歴がない場合は、現在のリクエストのみで判断してください

回答はJSON形式で:
{{
  "actionable": true/false,
  "goal": "最終的に達成したいこと",
  "steps": [
    {{"step": 1, "action": "アクション内容", "tool": "使用ツール"}},
    ...
  ],
  "tools_needed": ["必要なツール1", "必要なツール2"],
  "search_query": "最初に検索するキーワード",
  "reasoning": "このアクションプランの理由"
}}"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=analysis_prompt)])
            content = response.content
            
            import json
            import re
            # JSONを抽出（複数行対応）
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                parsed = json.loads(json_match.group())
                return parsed
        except Exception as e:
            logger.warning(f"Action analysis failed: {e}")
        
        # フォールバック: Web検索可能と仮定
        return {
            "actionable": True,
            "goal": wish,
            "steps": [{"step": 1, "action": "Web検索で情報収集", "tool": "search_web"}],
            "tools_needed": ["search_web"],
            "search_query": wish,
            "reasoning": "詳細分析に失敗したため、まずWeb検索で情報収集します",
        }
    
    async def _determine_task_type(self, wish: str, conversation_history: list[dict] = None) -> TaskType:
        """
        タスクタイプをLLMで判定（キーワードベースではなく意味理解）
        会話履歴がある場合は文脈を考慮する
        """
        if conversation_history is None:
            conversation_history = []
        
        # 会話履歴をフォーマット
        history_text = self._format_conversation_history(conversation_history)
        
        analysis_prompt = f"""ユーザーのリクエストを分析し、最も適切なタスクタイプを判定してください。

## 直近の会話履歴（このセッション内のみ）
{history_text}

## 現在のリクエスト
{wish}

## タスクタイプ
- phone: 電話を使った対応が必要（予約電話、問い合わせ電話など）
- travel: 交通機関の予約（新幹線、電車、バス、飛行機など）
- purchase: 商品の購入
- email: メールの送信・検索・読み取り
- research: 情報収集・調査（サービス探し、比較、調査など）
- other: 上記に該当しない

## 判定基準
- 「〇〇したい」「〇〇を探して」「〇〇を雇いたい」などはresearchに分類
- Web検索で情報を集めて何かを見つける必要があるものはresearch
- 具体的なサービス予約（電車、バス、飛行機）はtravel
- 電話をかけることが明示されていればphone
- 商品を買うことが明示されていればpurchase

## 重要な注意事項
- **与えられた会話履歴のみに基づいて判断してください**
- **会話履歴にない情報を推測・捏造しないでください**
- **別のセッションや過去の会話を想像しないでください**
- 会話履歴がない場合は、現在のリクエストのみで判断してください

回答は以下のJSONフォーマットで:
{{"task_type": "タイプ名", "reasoning": "判定理由"}}"""

        try:
            response = await self.llm.ainvoke([HumanMessage(content=analysis_prompt)])
            content = response.content
            
            # JSONをパース
            import json
            import re
            json_match = re.search(r'\{[^{}]*\}', content)
            if json_match:
                parsed = json.loads(json_match.group())
                task_type_str = parsed.get("task_type", "other").lower()
                
                type_map = {
                    "phone": TaskType.PHONE,
                    "travel": TaskType.TRAVEL,
                    "purchase": TaskType.PURCHASE,
                    "email": TaskType.EMAIL,
                    "research": TaskType.RESEARCH,
                    "other": TaskType.OTHER,
                }
                return type_map.get(task_type_str, TaskType.OTHER)
        except Exception as e:
            logger.warning(f"LLM task type detection failed: {e}")
        
        # フォールバック: キーワードベース
        return self._determine_task_type_fallback(wish)
    
    def _determine_task_type_fallback(self, wish: str) -> TaskType:
        """フォールバック: キーワードベースのタスクタイプ判定"""
        wish_lower = wish.lower()
        
        # 電話
        phone_keywords = ["電話して", "電話で", "電話をかけて", "架電", "コールして", 
                         "call ", "phone ", "call the", "phone the", "電話予約"]
        if any(kw in wish_lower for kw in phone_keywords):
            return TaskType.PHONE
        
        # 旅行
        travel_keywords_ja = ["新幹線", "電車", "特急", "飛行機", "航空", "バス", "高速バス", 
                              "予約", "チケット", "乗車券", "切符", "移動", "便"]
        travel_keywords_en = ["travel", "train", "shinkansen", "bus", "highway", 
                              "flight", "book", "reservation", "willer"]
        if any(kw in wish_lower for kw in travel_keywords_ja) or \
           any(kw in wish_lower for kw in travel_keywords_en):
            return TaskType.TRAVEL
        
        # 購入
        if "買" in wish_lower or "購入" in wish_lower or "欲しい" in wish_lower:
            return TaskType.PURCHASE
        
        # メール
        if "メール" in wish_lower or "email" in wish_lower:
            return TaskType.EMAIL
        
        # 調査系（雇いたい、探して、調べて、見つけてなど）
        research_keywords = ["探して", "調べて", "見つけて", "雇いたい", "頼みたい", 
                            "依頼したい", "知りたい", "教えて", "比較", "おすすめ",
                            "search", "find", "look for", "hire", "recommend"]
        if any(kw in wish_lower for kw in research_keywords):
            return TaskType.RESEARCH
        
        return TaskType.OTHER
    
    async def _generate_proposal_from_search(
        self,
        wish: str,
        research: dict,
        search_result,  # ExecutorSearchResult
        executor,  # BaseExecutor
    ) -> dict:
        """
        検索結果から提案を生成
        
        Args:
            wish: ユーザーの願望
            research: 推論結果
            search_result: Executor検索結果
            executor: 使用したExecutor
            
        Returns:
            提案情報
        """
        # 最良の選択肢を選択
        best_option = search_result.options[0] if search_result.options else None
        
        if not best_option:
            return {
                "action": "検索しましたが、該当する結果が見つかりませんでした",
                "details": "",
                "notes": "条件を変更してお試しください",
                "options": [],
                "executor_name": executor.service_name,
                "can_execute": False,
            }
        
        # LLMで提案文を生成
        proposal_prompt = f"""以下の情報を元に、ユーザーへの提案を作成してください。

ユーザーのリクエスト: {wish}

検索結果:
- サービス: {search_result.service_display_name}
- 見つかった選択肢: {len(search_result.options)}件
- 最良の選択肢: {best_option.title}
- 説明: {best_option.description}
- 価格: {best_option.price}円 (確認済み)

以下の形式で回答してください:

[ACTION]
（何をするか - 具体的に）

[DETAILS]
（詳細情報）

[NOTES]
（仮定した点、変更可能な点）"""

        response = await self.llm.ainvoke([
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=proposal_prompt)
        ])
        
        # レスポンスをパース
        content = response.content
        action = ""
        details = ""
        notes = ""
        
        if "[ACTION]" in content:
            parts = content.split("[ACTION]")[1]
            if "[DETAILS]" in parts:
                action = parts.split("[DETAILS]")[0].strip()
                parts = parts.split("[DETAILS]")[1]
            if "[NOTES]" in parts:
                details = parts.split("[NOTES]")[0].strip()
                notes = parts.split("[NOTES]")[1].strip()
            else:
                details = parts.strip()
        
        return {
            "action": action or f"{search_result.service_display_name}で予約します",
            "details": details or best_option.description,
            "notes": notes or "実際のサイトで空席を確認済みです",
            "options": [opt.to_dict() for opt in search_result.options],
            "selected_option": best_option.to_dict(),
            "executor_name": executor.service_name,
            "executor_display_name": executor.service_display_name,
            "can_execute": True,
            "full_proposal": content,
        }
    
    async def _generate_tool_based_proposal(
        self,
        wish: str,
        research: dict,
        request_id: Optional[str] = None,
        conversation_history: list[dict] = None,
    ) -> dict:
        """
        利用可能なツールを使ったアクション提案を生成
        
        Executorがなくても、search_web, send_email, browse_website などの
        ツールを組み合わせてアクションを提案する。
        """
        from app.services.progress_callback import notify_progress
        
        if conversation_history is None:
            conversation_history = []
        
        params = research.get("params", {})
        steps = params.get("steps", [])
        tools_needed = params.get("tools_needed", ["search_web"])
        search_query = params.get("search_query", wish)
        goal = params.get("goal", wish)
        
        # 会話履歴をフォーマット
        history_text = self._format_conversation_history(conversation_history)
        
        # Step 1: まずWeb検索を実行
        if request_id:
            await notify_progress(request_id, "web_search", "Web検索で情報を収集しています...", "running")
        
        search_results = []
        try:
            search_results = await tavily_search.ainvoke({
                "query": search_query,
                "max_results": 5
            })
            logger.info(f"[TOOL_PROPOSAL] Web search completed: {len(search_results)} results")
        except Exception as e:
            logger.warning(f"Web search failed: {e}")
        
        if request_id:
            await notify_progress(
                request_id, "web_search", 
                f"関連情報を{len(search_results)}件見つけました", 
                "completed"
            )
        
        # Step 2: 検索結果を元にアクション提案を生成
        search_summary = ""
        if search_results:
            for i, r in enumerate(search_results[:5], 1):
                title = r.get("title", "不明")
                url = r.get("url", "")
                snippet = r.get("snippet", r.get("content", ""))[:200]
                search_summary += f"{i}. {title}\n   URL: {url}\n   概要: {snippet}\n\n"
        
        proposal_prompt = f"""以下のリクエストに対して、具体的なアクションを提案してください。

## 直近の会話履歴（このセッション内のみ）
{history_text}

## 現在のリクエスト
{wish}

## 最終目標
{goal}

## Web検索結果
{search_summary if search_summary else "検索結果なし"}

## 利用可能なツール
- search_web: さらに詳細な検索
- send_email: 問い合わせメールの送信
- browse_website: Webサイトの詳細確認
- make_phone_call: 電話での問い合わせ（AI音声）

## 重要ルール
- **質問は絶対にしない**。情報が不足していても仮定して具体的なアクションを提案する
- 検索結果から最も適切なサービス/会社を選んで、具体的な問い合わせ内容まで提案する
- 「〇〇してもよろしいですか？」ではなく「〇〇します」と断定する
- 問い合わせ先が見つかった場合は、問い合わせメールの文面まで具体的に書く

## 重要な注意事項
- **与えられた会話履歴のみに基づいて判断してください**
- **会話履歴にない情報を推測・捏造しないでください**
- **別のセッションや過去の会話を想像しないでください**

以下の形式で回答してください:

[ACTION]
（具体的に何をするか - サービス名、連絡先、アクション内容を明記）

[DETAILS]
（問い合わせメールの文面、または次のステップの詳細）

[NOTES]
（仮定した点、変更可能な点）"""

        response = await self.llm.ainvoke([
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=proposal_prompt)
        ])
        
        content = response.content
        
        # アクション部分を抽出
        action = ""
        details = ""
        notes = ""
        
        if "[ACTION]" in content:
            parts = content.split("[ACTION]")[1]
            if "[DETAILS]" in parts:
                action = parts.split("[DETAILS]")[0].strip()
                parts = parts.split("[DETAILS]")[1]
            if "[NOTES]" in parts:
                details = parts.split("[NOTES]")[0].strip()
                notes = parts.split("[NOTES]")[1].strip()
            else:
                details = parts.strip()
        
        return {
            "action": action or "情報を調査し、問い合わせを行います",
            "details": details,
            "notes": notes,
            "search_results": search_results,
            "tools_used": ["search_web"],
            "tools_available": tools_needed,
            "can_execute": True,  # ツールベースの実行が可能
            "full_proposal": content,
        }
    
    async def _generate_manual_proposal(
        self,
        wish: str,
        research: dict,
    ) -> dict:
        """
        フィジカルな作業が必要な場合の手動提案を生成
        """
        proposal_prompt = f"""以下のリクエストに対して、手動での対応方法を提案してください。

ユーザーのリクエスト: {wish}

調査結果:
- 推奨サービス: {research.get('service_display_name', '不明')}
- サービスタイプ: {research.get('service_type', '不明')}

このリクエストは物理的な作業が必要なため、自動実行はできません。
代わりに、ユーザーが手動で行う手順を具体的に説明してください。

重要: 質問はせず、手順を断定的に説明してください。

以下の形式で回答してください:

[ACTION]
（手動で行う操作を説明）

[DETAILS]
（詳細な手順、参考URL、連絡先など）

[NOTES]
（注意点）"""

        response = await self.llm.ainvoke([
            SystemMessage(content=self.SYSTEM_PROMPT),
            HumanMessage(content=proposal_prompt)
        ])
        
        return {
            "action": "手動での対応をお願いします",
            "details": "",
            "notes": "",
            "options": [],
            "can_execute": False,
            "full_proposal": response.content,
        }
    
    # ========================================
    # Step 6: StateMachine統合
    # ========================================
    
    # セッションごとのStateMachineインスタンスを保持
    _state_machines: dict[str, "StateMachine"] = {}
    
    async def process_with_state_machine(
        self,
        message: str,
        session_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        StateMachineを使ってメッセージを処理
        
        新しいアーキテクチャ:
        1. 状態機械で固定の遷移
        2. 各状態でLLMを呼び出し
        3. Executorで実行
        4. Criticで評価
        
        Args:
            message: ユーザーからのメッセージ
            session_id: セッションID（省略時は自動生成）
            user_id: ユーザーID
            
        Returns:
            {
                "session_id": セッションID,
                "state": 現在の状態,
                "response": ユーザーへの応答,
                "reasoning_steps": 推論過程（プロセス表示用）,
                "needs_confirmation": 承認が必要か,
                "proposal": 提案内容（提案フェーズの場合）,
                "error": エラーがあれば,
            }
        """
        from app.agent.state_machine import StateMachine
        
        # セッションIDがなければ生成
        if not session_id:
            session_id = str(uuid.uuid4())
        
        # ユーザーIDのデフォルト
        if not user_id:
            user_id = "default-user"
        
        # StateMachineを取得または作成
        if session_id not in AISecretaryAgent._state_machines:
            AISecretaryAgent._state_machines[session_id] = StateMachine(
                session_id=session_id,
                user_id=user_id,
            )
        
        sm = AISecretaryAgent._state_machines[session_id]
        
        # メッセージを処理
        result = await sm.process_message(message)
        
        # session_idを結果に追加
        result["session_id"] = session_id
        
        # 状態がREPORTまたはCHATなら終了済み
        from app.agent.states import State
        is_complete = result.get("state") in [State.REPORT.value, "CHAT", "REPORT"]
        
        # 完了したらStateMachineを削除（メモリリーク防止）
        if is_complete:
            if session_id in AISecretaryAgent._state_machines:
                del AISecretaryAgent._state_machines[session_id]
        
        return result
    
    async def confirm_state_machine(
        self,
        session_id: str,
    ) -> dict[str, Any]:
        """
        StateMachineで提案を承認
        
        Args:
            session_id: セッションID
            
        Returns:
            実行結果
        """
        if session_id not in AISecretaryAgent._state_machines:
            return {
                "error": f"Session not found: {session_id}",
                "session_id": session_id,
            }
        
        sm = AISecretaryAgent._state_machines[session_id]
        user_id = sm.state.user_id
        
        # "OK"を送信して承認
        result = await sm.process_message("OK")
        result["session_id"] = session_id
        result["user_id"] = user_id  # DB保存用にuser_idを含める
        
        # 完了したらStateMachineを削除
        from app.agent.states import State
        is_complete = result.get("state") in [State.REPORT.value, "REPORT"]
        if is_complete:
            if session_id in AISecretaryAgent._state_machines:
                del AISecretaryAgent._state_machines[session_id]
        
        return result
    
    async def revise_state_machine(
        self,
        session_id: str,
        revision: str,
    ) -> dict[str, Any]:
        """
        StateMachineで提案を修正
        
        Args:
            session_id: セッションID
            revision: 修正内容
            
        Returns:
            修正後の提案
        """
        if session_id not in AISecretaryAgent._state_machines:
            return {
                "error": f"Session not found: {session_id}",
                "session_id": session_id,
            }
        
        sm = AISecretaryAgent._state_machines[session_id]
        
        # 修正内容を送信
        result = await sm.process_message(revision)
        result["session_id"] = session_id
        
        return result
    
    def get_state_machine_state(self, session_id: str) -> Optional[dict]:
        """
        StateMachineの現在の状態を取得
        
        Args:
            session_id: セッションID
            
        Returns:
            状態情報（なければNone）
        """
        if session_id not in AISecretaryAgent._state_machines:
            return None
        
        sm = AISecretaryAgent._state_machines[session_id]
        return sm.state.to_dict()
    
    def get_state_machine_user_id(self, session_id: str) -> Optional[str]:
        """
        StateMachineセッションのuser_idを取得
        
        Args:
            session_id: セッションID
            
        Returns:
            user_id（なければNone）
        """
        if session_id not in AISecretaryAgent._state_machines:
            return None
        
        sm = AISecretaryAgent._state_machines[session_id]
        return sm.state.user_id if sm.state.user_id else None