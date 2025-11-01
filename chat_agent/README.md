# Chat Agent with Tool Calling

A LangGraph-based conversational agent that uses Azure OpenAI and can automatically call tools to answer questions.

## 🎯 What This Demo Does

The chat agent:
1. **Receives user queries** through a conversational interface
2. **Decides automatically** whether to use tools or respond directly
3. **Calls tools** (like getting weather information) when needed
4. **Synthesizes natural language responses** based on tool results
5. **Maintains conversation history** across multiple turns

## 🏗️ Architecture

The agent uses a state graph with two main nodes:
- **Observe & Planning Node**: Analyzes the current state and decides the next action
- **Action Node**: Executes the requested tools/actions

### Flow Diagram:
```
User Input → Observe & Planning (LLM) → Action Needed? 
                                      ├─ Yes → Execute Action → Observe & Planning (LLM) → Response
                                      └─ No → Direct Response
```

## 🚀 How to Run

### Prerequisites
Make sure you've completed the environment setup in the [root README](../README.md):
- ✅ Created virtual environment
- ✅ Installed dependencies
- ✅ Configured `.env` file with Azure credentials

### Run the Demo

From the **root directory** (`agent_demo/`):
```bash
cd chat_agent
python chat_agent_demo.py
```

Or from anywhere:
```bash
python chat_agent/chat_agent_demo.py
```

## 📊 Example Output

### Demo 1: Query with Tool Call
```
🚀 DEMO 1: Query that requires a tool call

User: "What is the weather in San Francisco?"

--- Observing & Planning (Calling LLM) ---
Agent → Decides to call get_weather tool

--- Calling get_weather tool for San Francisco ---
Action → Returns: {"city": "San Francisco", "temperature": "15°C", "conditions": "Foggy"}

--- Observing & Planning (Calling LLM) ---
Agent → "Right now in San Francisco it's 15°C (59°F) and foggy. 
         Expect reduced visibility — a light jacket or layers are recommended."
```

### Demo 2: Query without Tool Call
```
🚀 DEMO 2: Query that does NOT require a tool call

User: "Hi, my name is Bob."

--- Observing & Planning (Calling LLM) ---
Agent → "Hi Bob — nice to meet you! How can I help you today?"
```

## 🔧 Key Components

### 1. Tools
The demo includes a `get_weather` tool that returns mock weather data:

```python
@tool
def get_weather(city: str) -> str:
    """
    Get the current weather for a specific city.
    
    Args:
        city: The name of the city.
    """
    # Returns mock weather data for demo purposes
```

**How it works:**
- The `@tool` decorator automatically generates a schema for the LLM
- The docstring helps the LLM decide when to use the tool
- The LLM extracts the city parameter from user queries

### 2. State Management

```python
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
```

- **State**: A dictionary containing conversation history
- **messages**: A list that grows with each interaction
- **add_messages**: Ensures new messages are appended, not replaced

### 3. Graph Structure

```python
graph_builder = StateGraph(AgentState)
graph_builder.add_node("observe_and_planning", observe_and_plan)
graph_builder.add_node("action", action_node)
graph_builder.add_conditional_edges("observe_and_planning", tools_condition)
graph_builder.add_edge("action", "observe_and_planning")
```

- **Conditional edges**: Routes to action node if LLM decides to call tools
- **Loop back**: Action results go back to observe_and_planning for final response

## 📝 Customizing the Demo

### Adding New Tools

Add new tools by defining functions with the `@tool` decorator:

```python
@tool
def calculate(expression: str) -> str:
    """
    Evaluate a mathematical expression.
    
    Args:
        expression: A math expression to evaluate (e.g., "2 + 2")
    """
    try:
        result = eval(expression)
        return str(result)
    except Exception as e:
        return f"Error: {str(e)}"

# Add to tools list
tools = [get_weather, calculate]
```

### Changing Questions

Modify the demo queries at the bottom of `chat_agent_demo.py`:

```python
# Custom query
inputs = {
    "messages": [HumanMessage(content="Your question here")]
}

for event in graph.stream(inputs, stream_mode="values"):
    # Process results...
```

### Adjusting LLM Settings

```python
llm = AzureChatOpenAI(
    api_version=os.environ["OPENAI_API_VERSION"],
    azure_deployment=os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT_NAME"],
    azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
    # Note: Some models only support default temperature
    # temperature=0.7,  # Uncomment if your model supports it
    # max_tokens=500,   # Limit response length
)
```

## 🎓 What You'll Learn

This demo teaches:
- ✅ Setting up LangGraph with Azure OpenAI
- ✅ Defining tools using the `@tool` decorator
- ✅ Building state graphs for multi-step agents
- ✅ Handling conditional flows (tool vs direct response)
- ✅ Managing conversation state with reducers
- ✅ Real-world API integration patterns

## 🐛 Common Issues

### Tool Not Being Called
- **Check docstring**: Make sure it clearly describes when to use the tool
- **Ensure tool is in list**: Verify it's added to `tools = [get_weather, ...]`
- **Be explicit**: Try a more direct query like "Use get_weather for Tokyo"

### Model Doesn't Support Temperature
Some models (like gpt-5-mini) only support default temperature. Remove the `temperature` parameter if you see this error.

### Import Errors
Make sure you're running from the correct directory and the virtual environment is activated.

## 📚 Next Steps

- Add more sophisticated tools (database queries, API calls)
- Implement error handling for tool failures
- Add conversation memory persistence
- Build a web interface for the agent
- Deploy as a REST API or chatbot

---

**Happy Building! 🚀**
