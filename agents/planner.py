"""
Planner Agent — декомпозує запит користувача у структурований план дослідження.

Робить 1 пошук щоб зрозуміти домен, потім повертає ResearchPlan як JSON у тексті.
parse_research_plan() парсить JSON з відповіді (обхід бага gpt-4o-mini з response_format + tools).

Запуск для тестування:
    .venv/bin/python3 agents/planner.py "What is RAG?"
"""
import json
import os
import re
import sys

# sys.path fix — додаємо корінь проєкту щоб знаходити config, tools, schemas
# при запуску агента напряму: .venv/bin/python3 agents/planner.py
# Аналогія Java: додаємо project root у classpath
# os.path.abspath(__file__) → /path/to/project/agents/planner.py
# os.path.dirname(dirname(...)) → /path/to/project  (підіймаємось на 2 рівні вгору)
# insert(0, ...) — ставимо на перше місце, щоб наші модулі мали пріоритет
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool

from config import settings, PLANNER_SYSTEM_PROMPT
from schemas import ResearchPlan
from tools import web_search as _web_search, knowledge_search as _knowledge_search


@tool
def web_search(query: str) -> str:
    """Search the web to understand the domain before planning."""
    results = _web_search(query)
    return "\n".join(f"- {r['title']}: {r['snippet']}" for r in results)


@tool
def knowledge_search(query: str) -> str:
    """Search local knowledge base to check what's already known about the topic."""
    return _knowledge_search(query)



def parse_research_plan(text: str) -> ResearchPlan:
    """
    Парсить ResearchPlan з вільного тексту відповіді Planner Agent.

    Шукає ```json ... ``` блок. Fallback на дефолтний план.
    """
    json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_match = re.search(r'\{[^{}]*"goal"[^{}]*\}', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
        else:
            print("  ⚠️  Planner returned no JSON — using fallback plan")
            return ResearchPlan(
                goal="Research the user's request",
                search_queries=["user request overview", "user request details"],
                sources_to_check=["web"],
                output_format="structured markdown report with headings and summary",
            )

    try:
        data = json.loads(json_str)
        return ResearchPlan.model_validate(data)
    except Exception as exc:
        print(f"  ⚠️  Planner JSON parse error: {exc} — using fallback plan")
        return ResearchPlan(
            goal="Research the user's request",
            search_queries=["user request overview", "user request details"],
            sources_to_check=["web"],
            output_format="structured markdown report with headings and summary",
        )


_planner_agent = None


def get_planner_agent():
    """Повертає planner_agent, створює при першому виклику (lazy singleton)."""
    global _planner_agent
    if _planner_agent is None:
        _model = init_chat_model(f"openai:{settings.openai_model}", temperature=settings.temperature)
        # Без response_format — Planner повертає JSON у тексті.
        # parse_research_plan() розбирає JSON з відповіді.
        _planner_agent = create_agent(
            model=_model,
            tools=[web_search, knowledge_search],
            system_prompt=PLANNER_SYSTEM_PROMPT,
            name="planner",
        )
    return _planner_agent


if __name__ == "__main__":
    # Запуск для ручного тестування: .venv/bin/python3 agents/planner.py
    # if __name__ == "__main__" — блок виконується лише при прямому запуску файлу,
    # НЕ при імпорті. Аналогія з Java: public static void main(String[] args).
    os.environ.setdefault("OPENAI_API_KEY", __import__("config").settings.openai_api_key)

    request = " ".join(sys.argv[1:]) or "What is RAG and how does it work?"
    print(f"Testing Planner Agent with: {request!r}\n")

    result = get_planner_agent().invoke(
        {"messages": [{"role": "user", "content": request}]},
        {"recursion_limit": 5},
    )
    plan = parse_research_plan(result["messages"][-1].content)
    print(f"\nResearchPlan:")
    print(f"  goal:            {plan.goal}")
    print(f"  search_queries:  {plan.search_queries}")
    print(f"  sources_to_check:{plan.sources_to_check}")
    print(f"  output_format:   {plan.output_format}")
