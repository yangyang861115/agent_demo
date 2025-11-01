"""
LangGraph-based Browser Agent

This module implements the browser agent using LangGraph's state graph architecture.
"""
import json
import logging
from typing import Optional, Annotated, Literal
from typing_extensions import TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, ToolMessage, SystemMessage
from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from browser import SimpleBrowserSession
from tools import create_browser_tools
from prompts import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


# ==============================================================
# STATE DEFINITION
# ==============================================================

class BrowserAgentState(TypedDict):
    """
    State for the LangGraph browser agent.
    
    This TypedDict defines all the state variables that flow through the graph.
    """
    # Core LangGraph messages (for tool calling)
    messages: Annotated[list[BaseMessage], add_messages]
    
    # Browser context (current state)
    current_url: str
    current_title: str
    elements: str  # Interactive elements as formatted string
    screenshot: Optional[str]  # Base64 screenshot
    
    # Agent memory and task
    task: str  # Original task description
    memory: str  # Agent's working memory
    step_number: int
    max_steps: int
    
    # History tracking (for context)
    history_items: list  # List of history item dicts
    
    # Control flags
    is_done: bool
    error: Optional[str]


def add_history_items(existing: list, new: list) -> list:
    """Reducer for history_items - append new items"""
    return existing + new


# ==============================================================
# GRAPH NODE: OBSERVE BROWSER
# ==============================================================

def create_observe_browser_node(browser: SimpleBrowserSession):
    """
    Create the observe_browser node with browser context injected.
    
    This node captures the current browser state (URL, title, elements, screenshot)
    and updates the graph state.
    """
    async def observe_browser(state: BrowserAgentState) -> dict:
        """
        Observe current browser state and update state.
        
        Returns dict with updated state fields.
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"Step {state['step_number'] + 1}/{state['max_steps']}")
        logger.info(f"{'='*60}")
        logger.info("🔍 Observing browser state...")
        
        # Get browser state using CDP
        browser_state = await browser.observe_browser_state()
        
        # Log what we see
        element_lines = browser_state.get('elements', '').split('\n')
        logger.info(f"📋 URL: {browser_state['url']}")
        logger.info(f"📋 Title: {browser_state['title']}")
        logger.info(f"📋 Elements found: {len(element_lines)} interactive elements")
        
        # Build context message for the agent
        context = f"""Step: {state['step_number'] + 1}/{state['max_steps']}
Memory: {state['memory'] if state['memory'] else "Just started"}

Agent History (what you did and what happened):
{format_history(state['history_items'])}

Current Browser State:
- URL: {browser_state['url']}
- Title: {browser_state['title']}
- Interactive Elements:
{browser_state['elements']}

What should you do next to complete this task: {state['task']}"""
        
        # Create message with screenshot if available
        if browser_state.get('screenshot'):
            logger.info(f"📸 Screenshot available (size: {len(browser_state['screenshot'])} chars)")
            message = HumanMessage(content=[
                {
                    "type": "text",
                    "text": context
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{browser_state['screenshot']}",
                        "detail": "high"
                    }
                }
            ])
        else:
            logger.info("📝 Text-only mode (no screenshot)")
            message = HumanMessage(content=context)
        
        return {
            "current_url": browser_state["url"],
            "current_title": browser_state["title"],
            "elements": browser_state["elements"],
            "screenshot": browser_state.get("screenshot"),
            "step_number": state["step_number"] + 1,
            "messages": [message]
        }
    
    return observe_browser


# ==============================================================
# GRAPH NODE: PLANNING
# ==============================================================

def create_planning_node(llm_with_tools):
    """
    Create the planning node with LLM injected.
    
    This node calls the LLM to plan what action to take next.
    """
    async def planning(state: BrowserAgentState) -> dict:
        """
        Call LLM to plan next action using tool calling.
        
        Returns dict with LLM's response message.
        """
        logger.info("🤔 Agent deciding next action...")
        
        # Prepare messages (system prompt + conversation history)
        messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
        
        # Call LLM with tools
        response = await llm_with_tools.ainvoke(messages)
        
        # Log decision
        if response.tool_calls:
            tool_call = response.tool_calls[0]
            logger.info(f"📌 Decision: {tool_call['name']}({tool_call['args']})")
        else:
            logger.info(f"📌 Decision: {response.content}")
        
        return {"messages": [response]}
    
    return planning


# ==============================================================
# GRAPH NODE: UPDATE HISTORY
# ==============================================================

async def update_history(state: BrowserAgentState) -> dict:
    """
    Update history with the latest action and result.
    
    Extracts information from messages and creates a history item.
    """
    logger.info("📝 Updating history...")
    
    # Find last AI message (the decision)
    ai_messages = [m for m in state["messages"] if isinstance(m, AIMessage)]
    if not ai_messages:
        return {}
    
    last_ai = ai_messages[-1]
    
    # Find last tool message (the result)
    tool_messages = [m for m in state["messages"] if isinstance(m, ToolMessage)]
    if not tool_messages:
        return {}
    
    last_tool = tool_messages[-1]
    
    # Extract action details
    if last_ai.tool_calls:
        tool_call = last_ai.tool_calls[0]
        action = tool_call["name"]
        action_params = tool_call["args"]
    else:
        action = "unknown"
        action_params = {}
    
    # Build history item
    history_item = {
        "step_number": state["step_number"],
        "memory": state["memory"],
        "next_goal": f"Execute {action}",  # We don't have explicit goal anymore
        "action": action,
        "action_params": action_params,
        "result_summary": last_tool.content
    }
    
    # Check if task is done
    is_done = action == "done" or state["step_number"] >= state["max_steps"]
    
    # Update memory with result
    new_memory = f"Completed {action}. Result: {last_tool.content[:100]}"
    
    logger.info(f"✅ History updated: {action} → {last_tool.content[:80]}...")
    
    return {
        "history_items": [history_item],
        "memory": new_memory,
        "is_done": is_done
    }


# ==============================================================
# ROUTING FUNCTIONS
# ==============================================================

def should_continue(state: BrowserAgentState) -> Literal["action", "done"]:
    """
    Determine whether to continue with action or end.
    
    Routes to:
    - "action" if LLM made a tool call and not done
    - "done" if task complete or max steps reached
    """
    # Check if max steps reached
    if state["step_number"] >= state["max_steps"]:
        logger.info(f"⚠️ Max steps ({state['max_steps']}) reached")
        return "done"
    
    # Check if explicitly done
    if state.get("is_done"):
        logger.info("✅ Task marked as done")
        return "done"
    
    # Check if last message has tool calls
    if state["messages"]:
        last_message = state["messages"][-1]
        if isinstance(last_message, AIMessage) and last_message.tool_calls:
            tool_name = last_message.tool_calls[0]["name"]
            if tool_name == "done":
                logger.info("✅ Done tool called")
                return "done"
            return "action"
    
    # Default to done if no tool calls
    return "done"


# ==============================================================
# HELPER FUNCTIONS
# ==============================================================

def format_history(history_items: list) -> str:
    """Format history items for display to LLM"""
    if not history_items:
        return "No previous actions yet"
    
    # Show last 5 steps
    recent_items = history_items[-5:]
    
    lines = []
    for item in recent_items:
        params_str = str(item.get("action_params", {}))
        lines.append(f"""<step_{item['step_number']}>
Goal: {item.get('next_goal', 'Unknown')}
Action: {item['action']}({params_str})
Result: {item['result_summary']}
</step_{item['step_number']}>""")
    
    return "\n".join(lines)


# ==============================================================
# GRAPH BUILDER
# ==============================================================

def create_browser_agent_graph(
    browser: SimpleBrowserSession,
    model: str = "gpt-4o-mini",
    api_version: str = "2024-12-01-preview",
    azure_endpoint: str = None,
    api_key: str = None
):
    """
    Create the complete LangGraph browser agent.
    
    Args:
        browser: SimpleBrowserSession instance
        model: Model/deployment name
        api_version: Azure API version
        azure_endpoint: Azure endpoint URL
        api_key: Azure OpenAI API key
        
    Returns:
        Compiled LangGraph
    """
    logger.info("🏗️ Building LangGraph browser agent...")
    
    # Create single LLM client for both vision and planning
    llm = AzureChatOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_deployment=model,
        azure_endpoint=azure_endpoint
    )
    logger.info(f"✅ LLM client configured: {model}")
    
    # Create browser tools (using the same LLM)
    browser_tools = create_browser_tools(browser, llm, model)
    logger.info(f"✅ Created {len(browser_tools)} browser tools")
    
    # Bind tools to LLM for planning
    llm_with_tools = llm.bind_tools(browser_tools)
    logger.info("✅ LLM configured with tools")
    
    # Create ToolNode for action execution
    action_node = ToolNode(browser_tools)
    
    # Create graph nodes
    observe_browser = create_observe_browser_node(browser)
    planning = create_planning_node(llm_with_tools)
    
    # Build the graph
    graph_builder = StateGraph(BrowserAgentState)
    
    # Add nodes
    graph_builder.add_node("observe_browser", observe_browser)
    graph_builder.add_node("planning", planning)
    graph_builder.add_node("action", action_node)
    graph_builder.add_node("update_history", update_history)
    
    # Set entry point
    graph_builder.set_entry_point("observe_browser")
    
    # Add edges
    graph_builder.add_edge("observe_browser", "planning")
    
    # Conditional edge after planning
    graph_builder.add_conditional_edges(
        "planning",
        should_continue,
        {
            "action": "action",
            "done": END
        }
    )
    
    # After action, update history
    graph_builder.add_edge("action", "update_history")
    
    # After history update, observe browser again (loop)
    graph_builder.add_edge("update_history", "observe_browser")
    
    # Compile graph
    graph = graph_builder.compile()
    logger.info("✅ Graph compiled successfully!")
    
    return graph


# ==============================================================
# CONVENIENCE WRAPPER CLASS
# ==============================================================

class LangGraphBrowserAgent:
    """
    Convenience wrapper for the LangGraph browser agent.
    
    Provides a simple interface for running browser automation tasks.
    Automatically loads Azure OpenAI credentials from environment variables.
    """
    
    def __init__(
        self,
        task: str,
        headless: bool = False,
        max_steps: int = 30
    ):
        """
        Initialize the browser agent.
        
        Args:
            task: The task description for the agent to complete
            headless: Whether to run browser in headless mode
            max_steps: Maximum number of steps before stopping
            
        Environment Variables Required:
            AZURE_OPENAI_ENDPOINT: Azure OpenAI endpoint URL
            AZURE_OPENAI_API_KEY: Azure OpenAI API key
            OPENAI_API_VERSION: API version (default: 2024-12-01-preview)
            AZURE_OPENAI_CHAT_DEPLOYMENT_NAME: Deployment name (default: gpt-4o-mini)
        """
        import os
        
        self.task = task
        self.max_steps = max_steps
        
        # Load credentials from environment
        self.azure_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        self.api_key = os.getenv("AZURE_OPENAI_API_KEY")
        self.api_version = os.getenv(
            "OPENAI_API_VERSION", "2024-12-01-preview"
        )
        self.model = os.getenv(
            "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME", "gpt-4o-mini"
        )
        
        # Validate required credentials
        if not self.azure_endpoint or not self.api_key:
            raise ValueError(
                "Missing required environment variables!\n"
                "Please set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY\n"
                "in your .env file or environment."
            )
        
        # Initialize browser
        self.browser = SimpleBrowserSession(headless=headless)
        
        # Graph will be created when run() is called
        self.graph = None
    
    async def run(self) -> str:
        """
        Run the browser agent to complete the task.
        
        Returns:
            Final result string
        """
        # Start browser
        await self.browser.start()
        
        try:
            # Create graph (LLM is created internally)
            self.graph = create_browser_agent_graph(
                self.browser,
                self.model,
                self.api_version,
                self.azure_endpoint,
                self.api_key
            )
            
            # Initial state
            initial_state = {
                "messages": [],
                "task": self.task,
                "memory": "",
                "step_number": 0,
                "max_steps": self.max_steps,
                "history_items": [],
                "is_done": False,
                "current_url": "",
                "current_title": "",
                "elements": "",
                "screenshot": None,
                "error": None
            }
            
            logger.info(f"\n{'='*70}")
            logger.info("🚀 Starting LangGraph Browser Agent")
            logger.info(f"{'='*70}")
            logger.info(f"Task: {self.task}")
            logger.info(f"Model: {self.model}")
            logger.info(f"Max Steps: {self.max_steps}")
            logger.info(f"{'='*70}\n")
            
            # Run graph with recursion limit
            # Each step involves ~4 nodes: observe_browser → planning → action → update_history
            # So recursion_limit needs to be at least (max_steps * 4) + buffer
            config = {"recursion_limit": self.max_steps * 5}  # 5x for safety margin
            final_state = None
            async for event in self.graph.astream(initial_state, config=config, stream_mode="values"):
                final_state = event
                # Log progress
                if "messages" in event and event["messages"]:
                    last_msg = event["messages"][-1]
                    if isinstance(last_msg, ToolMessage):
                        logger.info(f"🔧 Tool result: {last_msg.content[:100]}...")
            
            # Extract final result
            if final_state:
                # Look for done tool result
                tool_messages = [m for m in final_state["messages"] if isinstance(m, ToolMessage)]
                if tool_messages:
                    last_result = tool_messages[-1].content
                    
                    logger.info(f"\n{'='*70}")
                    logger.info("✅ TASK COMPLETE")
                    logger.info(f"{'='*70}")
                    logger.info(f"Result: {last_result}")
                    logger.info(f"Steps taken: {final_state['step_number']}")
                    logger.info(f"{'='*70}\n")
                    
                    return last_result
            
            # Fallback
            return f"Reached max steps ({self.max_steps}). Progress: {final_state.get('memory', 'Unknown')}"
            
        finally:
            await self.browser.close()

