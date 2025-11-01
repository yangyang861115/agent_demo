"""
Browser Agent - LangGraph-based browser automation with LLM.

Production-ready browser agent using LangGraph for:
- State graph architecture
- Native tool calling
- Automatic state management  
- Shadow DOM support
- Real browser actions via CDP
"""

from .agent import LangGraphBrowserAgent, BrowserAgentState, create_browser_agent_graph
from .tools import create_browser_tools
from .models import AgentState, AgentOutput, ActionResult, BrowserState

__all__ = [
    'LangGraphBrowserAgent',
    'BrowserAgentState',
    'create_browser_agent_graph',
    'create_browser_tools',
    'AgentState', 
    'AgentOutput',
    'ActionResult',
    'BrowserState'
]





