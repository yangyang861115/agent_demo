"""
Data models for the simple browser agent.
"""
from typing import Literal, Optional, List
from pydantic import BaseModel


class HistoryItem(BaseModel):
    """One step in agent history - what was done and what happened"""
    step_number: int
    memory: str
    next_goal: str
    action: str
    action_params: dict
    result_summary: str  # What happened after the action


class AgentState(BaseModel):
    """Agent's internal state"""
    step_number: int = 0
    memory: str = ""  # What the agent remembers across steps
    is_done: bool = False
    history_items: List[HistoryItem] = []  # Track what agent did and results


class ActionResult(BaseModel):
    """Result of executing an action"""
    success: bool = True
    content: str = ""  # Short immediate feedback
    error: Optional[str] = None
    is_done: bool = False
    
    # Memory management (like browser-use)
    long_term_memory: Optional[str] = None  # Persistent feedback in history
    extracted_content: Optional[str] = None  # Detailed output
    
    # Metadata
    metadata: Optional[dict] = None


class AgentOutput(BaseModel):
    """LLM's structured output"""
    thinking: str  # Chain of thought reasoning
    memory: str  # What to remember for next steps
    next_goal: str  # Immediate next objective
    action: str  # Action name: navigate, click, input, extract, done
    action_params: dict  # Parameters for the action


class BrowserState(BaseModel):
    """Current browser state"""
    url: str
    title: str
    elements: str  # Interactive elements as indexed list
    screenshot_available: bool = False
    screenshot: Optional[str] = None  # Base64 encoded screenshot


