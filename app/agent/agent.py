"""
AI Secretary Agent - LangGraph Implementation
"""
from typing import TypedDict, Annotated, Sequence, Optional, Any
from datetime import datetime
import uuid
import operator

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from app.config import settings
from app.models.schemas import TaskStatus, TaskType, TaskResponse
from app.tools import get_tools, get_available_tool_names


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
    
    SYSTEM_PROMPT = """You are an excellent AI secretary. You understand user requests 
and propose specific actions to help execute them.

Your main roles:
1. Communication assistance via email and LINE
2. Shopping support
3. Bill and payment support
4. Information research

Guidelines:
- Accurately understand user intent
- Ask for clarification if information is missing
- Always confirm with user for important decisions (large payments, etc.)
- Propose concrete, executable actions
- Prioritize privacy and security

Available tools:
- send_email: Send emails
- search_email: Search emails
- send_line_message: Send LINE messages
- browse_website: Browse websites and retrieve information
- fill_form: Fill in forms
- click_element: Click web elements
- search_web: Web search

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
        
        # Task storage (use Supabase in production)
        self._tasks: dict[str, dict] = {}
    
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
- line: LINE related (send messages, etc.)
- purchase: Product purchase related
- payment: Payment related
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
        if "email" in content:
            task_type = TaskType.EMAIL
        elif "line" in content:
            task_type = TaskType.LINE
        elif "purchase" in content:
            task_type = TaskType.PURCHASE
        elif "payment" in content:
            task_type = TaskType.PAYMENT
        elif "research" in content:
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
        
        proposal_prompt = f"""Propose specific actions for the following request.

Request: {wish}
Task type: {task_type}

Respond with a list of proposed actions.
Also determine if user confirmation is required.

Confirmation is required for large payments or important decisions."""
        
        messages = state["messages"] + [HumanMessage(content=proposal_prompt)]
        response = await self.llm.ainvoke(messages)
        
        # Extract actions (simple implementation)
        content = response.content
        actions = []
        for line in content.split("\n"):
            line = line.strip()
            if line.startswith(("-", "*", "1", "2", "3", "4", "5")):
                actions.append(line.lstrip("-*0123456789. "))
        
        # Determine if confirmation is required
        requires_confirmation = any(
            keyword in state["original_wish"].lower()
            for keyword in ["purchase", "pay", "transfer", "contract", "apply", "buy", "order"]
        )
        
        return {
            **state,
            "proposed_actions": actions if actions else [content],
            "requires_confirmation": requires_confirmation,
            "status": TaskStatus.PROPOSED,
            "messages": state["messages"] + [response],
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
        
        # Save task
        self._tasks[task_id] = {
            "id": task_id,
            "user_id": user_id,
            "type": final_state["task_type"],
            "status": final_state["status"],
            "original_wish": wish,
            "proposed_actions": final_state["proposed_actions"],
            "execution_result": final_state["execution_result"],
            "created_at": datetime.utcnow(),
        }
        
        # Generate response message
        if final_state["requires_confirmation"]:
            message = "Proposed actions below. Do you want to execute?"
        else:
            message = "Request processed successfully."
        
        return {
            "task_id": task_id,
            "message": message,
            "proposed_actions": final_state["proposed_actions"],
            "requires_confirmation": final_state["requires_confirmation"],
        }
    
    async def execute_task(self, task_id: str) -> dict[str, Any]:
        """Execute confirmed task"""
        task = self._tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")
        
        # Execute task (resume graph in actual implementation)
        task["status"] = TaskStatus.EXECUTING
        
        # TODO: Actual execution logic
        
        task["status"] = TaskStatus.COMPLETED
        return {"status": "completed", "task_id": task_id}
    
    async def get_task(self, task_id: str) -> Optional[TaskResponse]:
        """Get task"""
        task = self._tasks.get(task_id)
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
        tasks = list(self._tasks.values())
        
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
