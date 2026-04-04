"""
Research Agent — виконує фактичне дослідження за планом від Planner.

Перевикористовує tools з hw5: web_search, read_url, knowledge_search.

Запуск для тестування:
    .venv/bin/python3 agents/research.py "What is RAG and how does it work?"
"""
import os
import sys

# sys.path fix — додаємо корінь проєкту щоб знаходити config, tools, schemas
# при запуску агента напряму: .venv/bin/python3 agents/research.py
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool

from config import settings, RESEARCH_SYSTEM_PROMPT
from tools import (
    web_search as _web_search,
    read_url as _read_url,
    knowledge_search as _knowledge_search,
)


@tool
def web_search(query: str) -> str:
    """Search the web for relevant information. Returns titles, URLs, and snippets."""
    results = _web_search(query)
    return "\n".join(f"- {r['title']}: {r['snippet']} ({r['url']})" for r in results)


@tool
def read_url(url: str) -> str:
    """Download a web page and extract its main readable text content."""
    return _read_url(url)


@tool
def knowledge_search(query: str) -> str:
    """Search the local knowledge base (RAG, LLMs, LangChain documents)."""
    return _knowledge_search(query)



_research_agent = None


def get_research_agent():
    """Повертає research_agent, створює при першому виклику (lazy singleton)."""
    global _research_agent
    if _research_agent is None:
        _model = init_chat_model(f"openai:{settings.openai_model}", temperature=settings.temperature)
        _research_agent = create_agent(
            model=_model,
            tools=[web_search, read_url, knowledge_search],
            system_prompt=RESEARCH_SYSTEM_PROMPT,
            name="researcher",
        )
    return _research_agent


if __name__ == "__main__":
    # Запуск для ручного тестування: .venv/bin/python3 agents/research.py
    _cfg = __import__("config").settings
    os.environ.setdefault("OPENAI_API_KEY", _cfg.openai_api_key)
    os.environ.setdefault("TAVILY_API_KEY", _cfg.tavily_api_key)

    request = " ".join(sys.argv[1:]) or "What is Python? Give a brief overview."
    print(f"Testing Research Agent with: {request!r}\n")

    result = get_research_agent().invoke(
        {"messages": [{"role": "user", "content": request}]},
        {"recursion_limit": 8},
    )
    print(f"\nFindings:\n{result['messages'][-1].content}")
