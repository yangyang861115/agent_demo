import os
import json
from dotenv import load_dotenv
from typing import Annotated
from typing_extensions import TypedDict

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    ToolMessage,
    AIMessage,
)
from langchain_core.tools import tool
from langchain_openai import AzureChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

# --- 1. Load Environment Variables ---
# Make sure to create a .env file with your Azure credentials
load_dotenv()

# Check for essential environment variables
if "AZURE_OPENAI_ENDPOINT" not in os.environ:
    raise EnvironmentError(
        "AZURE_OPENAI_ENDPOINT not found in .env file."
        "Please add: AZURE_OPENAI_ENDPOINT='https://your-endpoint.openai.azure.com/'"
    )
if "AZURE_OPENAI_API_KEY" not in os.environ:
    raise EnvironmentError(
        "AZURE_OPENAI_API_KEY not found in .env file. Please add: AZURE_OPENAI_API_KEY='your-api-key'"
    )
if "OPENAI_API_VERSION" not in os.environ:
    raise EnvironmentError(
        "OPENAI_API_VERSION not found in .env file."
        "Please add: OPENAI_API_VERSION='2024-02-01' (or your API version)"
    )
if "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME" not in os.environ:
    raise EnvironmentError(
        "AZURE_OPENAI_CHAT_DEPLOYMENT_NAME not found in .env file."
        "Please add: AZURE_OPENAI_CHAT_DEPLOYMENT_NAME='your-deployment-name'"
    )


# --- 2. Define a Mock Tool ---
# We'll create a simple "get_weather" tool for the agent to call.
@tool
def get_weather(city: str) -> str:
    """
    Get the current weather for a specific city.
    
    Args:
        city: The name of the city.
    """
    print(f"--- Calling get_weather tool for {city} ---")
    # In a real app, you'd call a weather API here.
    # For this demo, we'll return a mock response.
    if "san francisco" in city.lower():
        return json.dumps(
            {"city": "San Francisco", "temperature": "15°C", "conditions": "Foggy"}
        )
    elif "new york" in city.lower():
        return json.dumps(
            {"city": "New York", "temperature": "22°C", "conditions": "Sunny"}
        )
    else:
        return json.dumps(
            {"city": city, "temperature": "20°C", "conditions": "Clear skies"}
        )


# --- 3. Define the Agent State ---
# This TypedDict defines the structure of our agent's state.
# The `add_messages` function ensures new messages are appended to the list
# instead of replacing it.
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]


# --- 4. Initialize LLM and Tools ---

# Initialize the AzureChatOpenAI model
# It will automatically read the AZURE_OPENAI_API_KEY from the environment
llm = AzureChatOpenAI(
    api_version=os.environ["OPENAI_API_VERSION"],
    azure_deployment=os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"],
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
)

# Create a list of tools our agent can use
tools = [get_weather]

# Bind the tools to the LLM. This tells the LLM it can call these tools.
llm_with_tools = llm.bind_tools(tools)

# The ToolNode is a prebuilt LangGraph node that executes tools.
# We wrap it as action_node to represent action execution.
action_node = ToolNode(tools)


# --- 5. Define Graph Nodes ---

# This node handles observation and planning. It calls the LLM to analyze
# the current state (messages) and plan the next action.
def observe_and_plan(state: AgentState) -> dict:
    """
    Observe the current conversation state and plan the next action.
    
    The model analyzes the messages and decides to either:
    - Respond directly with an answer, or
    - Issue a tool call to gather more information
    """
    print("--- Observing & Planning (Calling LLM) ---")
    messages = state["messages"]
    response = llm_with_tools.invoke(messages)
    # The response (an AIMessage) is added to the state
    return {"messages": [response]}


# --- 6. Construct the Graph ---
print("Constructing LangGraph agent...")
graph_builder = StateGraph(AgentState)

# Add the two nodes to the graph
graph_builder.add_node("observe_and_planning", observe_and_plan)
graph_builder.add_node("action", action_node)  # Execute actions (tool calls)

# The entry point is the "observe_and_planning" node
graph_builder.set_entry_point("observe_and_planning")

# This conditional edge routes the flow *after* the "observe_and_planning" node runs.
# It checks the last message (the AIMessage from `observe_and_plan`):
# - If it contains tool calls, it routes to the "action" node.
# - Otherwise, it routes to END, finishing the graph execution.
graph_builder.add_conditional_edges(
    "observe_and_planning",
    tools_condition,  # This is a prebuilt function
    {
        "tools": "action",  # Route to "action" node if tool calls are present
        END: END,  # Otherwise, end the flow
    },
)

# This edge routes the flow *after* the "action" node runs.
# The output of the actions (ToolMessages) is sent back to the "observe_and_planning" node
# so the LLM can process the tool results and generate a final answer.
graph_builder.add_edge("action", "observe_and_planning")

# Compile the state graph into a runnable graph
graph = graph_builder.compile()
print("✅ Graph compiled successfully!")


# --- 7. Run the Demo ---

print("\n" + "=" * 50)
print("🚀 DEMO 1: Query that requires a tool call")
print("=" * 50)

# We use .stream() to see all the steps in the graph
# The input is a dictionary matching the AgentState
inputs_tool = {
    "messages": [HumanMessage(content="What is the weather in San Francisco?")]
}

for event in graph.stream(inputs_tool, stream_mode="values"):
    # `stream_mode="values"` yields the full state at each step
    latest_message = event["messages"][-1]
    print(f"\nNode: '{event.get('__key__', 'entry')}'")
    print("---")
    latest_message.pretty_print()
    if isinstance(latest_message, AIMessage) and latest_message.tool_calls:
        print(f"Tool Call: {latest_message.tool_calls[0]['name']}")
    elif isinstance(latest_message, ToolMessage):
        print(f"Tool Result: {latest_message.content}")

print("\n" + "=" * 50)
print("🚀 DEMO 2: Query that does NOT require a tool call")
print("=" * 50)

inputs_no_tool = {"messages": [HumanMessage(content="Hi, my name is Bob.")]}

for event in graph.stream(inputs_no_tool, stream_mode="values"):
    latest_message = event["messages"][-1]
    print(f"\nNode: '{event.get('__key__', 'entry')}'")
    print("---")
    latest_message.pretty_print()

