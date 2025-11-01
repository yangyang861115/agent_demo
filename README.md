# Agent Demo - LangGraph with Azure OpenAI

This repository contains demos for building AI agents using **LangChain**, **LangGraph**, and **Azure OpenAI API**.

## 📋 Prerequisites

- Python 3.8+
- Azure OpenAI account with:
  - An endpoint URL
  - An API key
  - A deployed chat model (e.g., GPT-4, GPT-3.5-turbo, GPT-5-mini)

## 🚀 Environment Setup

### 1. Clone the Repository

```bash
git clone https://github.com/changsi/agent_demo.git
cd agent_demo
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure Azure OpenAI Credentials

Copy the example environment file:
```bash
cp env.example .env
```

Edit `.env` and fill in your Azure OpenAI credentials:
```env
AZURE_OPENAI_ENDPOINT=https://your-resource-name.openai.azure.com/
AZURE_OPENAI_API_KEY=your-api-key-here
OPENAI_API_VERSION=2024-02-01
AZURE_OPENAI_CHAT_DEPLOYMENT_NAME=your-deployment-name
```

**Note:** The `.env` file is automatically excluded from git via `.gitignore` to protect your credentials.

## 📦 Project Structure

```
agent_demo/
├── chat_agent/              # Chat agent with tool calling demo
│   ├── chat_agent_demo.py   # Main demo script
│   └── README.md            # Chat agent documentation
├── requirements.txt         # Python dependencies
├── env.example             # Template for environment variables
├── .env                    # Your credentials (not in git)
├── .gitignore              # Git ignore rules
└── venv/                   # Virtual environment
```

## 🎯 Available Demos

### Chat Agent with Tool Calling
A conversational agent that can use tools (like weather lookup) to answer questions.

📖 See [chat_agent/README.md](chat_agent/README.md) for details and usage instructions.

## 🛠️ Dependencies

- `langchain` - Core LangChain library
- `langchain-core` - Core abstractions
- `langchain-openai` - Azure OpenAI integration
- `langgraph` - Graph-based agent framework
- `python-dotenv` - Environment variable management
- `typing-extensions` - Enhanced type hints

## 🐛 Troubleshooting

### Import Errors
- Ensure you've activated the virtual environment: `source venv/bin/activate`
- Reinstall dependencies: `pip install -r requirements.txt`

### Azure API Errors
- Verify your `.env` file has correct credentials
- Check that your Azure deployment is active
- Ensure your API version matches your deployment
- **Temperature errors**: Some models (like gpt-5-mini) only support default temperature values

## 📚 Additional Resources

- [LangChain Documentation](https://python.langchain.com/)
- [LangGraph Documentation](https://langchain-ai.github.io/langgraph/)
- [Azure OpenAI Documentation](https://learn.microsoft.com/en-us/azure/ai-services/openai/)

## 📄 License

This is a demo project for educational purposes.
