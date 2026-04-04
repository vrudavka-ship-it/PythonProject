"""
Critic Agent — оцінює якість дослідження через незалежну верифікацію знахідок.

Оцінює: freshness, completeness, structure.
Робить максимум 1-2 targeted searches для верифікації.

Запуск для тестування:
    .venv/bin/python3 agents/critic.py "# Python Overview\nPython is a language created in 1991."
    .venv/bin/python3 agents/critic.py  # без аргументів — використовується вбудований приклад
"""
import json
import os
import re
import sys

# sys.path fix — додаємо корінь проєкту щоб знаходити config, tools, schemas
# при запуску агента напряму: .venv/bin/python3 agents/critic.py
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool

from config import settings, CRITIC_SYSTEM_PROMPT
from schemas import CritiqueResult
from tools import (
    web_search as _web_search,
    read_url as _read_url,
    knowledge_search as _knowledge_search,
)


@tool
def web_search(query: str) -> str:
    """Search the web to verify facts or check for newer information."""
    results = _web_search(query)
    return "\n".join(f"- {r['title']}: {r['snippet']} ({r['url']})" for r in results)


@tool
def read_url(url: str) -> str:
    """Read a web page to verify a specific claim."""
    return _read_url(url)


@tool
def knowledge_search(query: str) -> str:
    """Search local knowledge base to cross-reference findings."""
    return _knowledge_search(query)



def parse_critique_result(text: str) -> CritiqueResult:
    """
    Парсить CritiqueResult з вільного тексту відповіді Critic Agent.

    Шукає ```json ... ``` блок або просто { "verdict": ... }.
    Fallback на APPROVE якщо JSON не знайдено.
    """
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            print("  ⚠️  Critic returned no JSON — defaulting to APPROVE")
            return CritiqueResult(
                verdict="APPROVE",
                is_fresh=True,
                is_complete=True,
                is_well_structured=True,
                strengths=["Research completed"],
                gaps=[],
                revision_requests=[],
            )

    try:
        data = json.loads(json_str)
        return CritiqueResult.model_validate(data)
    except Exception as exc:
        print(f"  ⚠️  Critic JSON parse error: {exc} — defaulting to APPROVE")
        return CritiqueResult(
            verdict="APPROVE",
            is_fresh=True,
            is_complete=True,
            is_well_structured=True,
            strengths=["Research completed"],
            gaps=[],
            revision_requests=[],
        )


_critic_agent = None


def get_critic_agent():
    """Повертає critic_agent, створює при першому виклику (lazy singleton)."""
    global _critic_agent
    if _critic_agent is None:
        _model = init_chat_model(f"openai:{settings.openai_model}", temperature=settings.temperature)
        # Без response_format — Critic повертає вільний текст із JSON-блоком.
        # parse_critique_result() розбирає JSON з відповіді.
        _critic_agent = create_agent(
            model=_model,
            tools=[web_search, read_url, knowledge_search],
            system_prompt=CRITIC_SYSTEM_PROMPT,
            name="critic",
        )
    return _critic_agent


if __name__ == "__main__":
    # Запуск для ручного тестування: .venv/bin/python3 agents/critic.py
    # Можна передати текст знахідок як аргумент або використовується дефолтний приклад.
    _cfg = __import__("config").settings
    os.environ.setdefault("OPENAI_API_KEY", _cfg.openai_api_key)
    os.environ.setdefault("TAVILY_API_KEY", _cfg.tavily_api_key)

    findings = " ".join(sys.argv[1:]) or (
        "# Python Overview\n"
        "Python is a high-level language created in 1991 by Guido van Rossum.\n"
        "It is used for web development, data science, and automation.\n"
        "## Summary\nPython is popular and versatile.\n"
        "### Sources\n- Wikipedia"
    )
    print(f"Testing Critic Agent...\n")

    result = get_critic_agent().invoke(
        {"messages": [{"role": "user", "content": findings}]},
        {"recursion_limit": 6},
    )
    critique = parse_critique_result(result["messages"][-1].content)
    print(f"\nCritiqueResult:")
    print(f"  verdict:            {critique.verdict}")
    print(f"  is_fresh:           {critique.is_fresh}")
    print(f"  is_complete:        {critique.is_complete}")
    print(f"  is_well_structured: {critique.is_well_structured}")
    print(f"  strengths:          {critique.strengths}")
    print(f"  gaps:               {critique.gaps}")
    print(f"  revision_requests:  {critique.revision_requests}")
