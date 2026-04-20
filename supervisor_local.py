"""
Supervisor Local — hw8 архітектура без ACP/MCP серверів (homework-lesson-12).

Відрізняється від supervisor.py (hw9) тим що:
- Sub-агенти (planner, researcher, critic) викликаються напряму як Python функції
- save_report записує файл локально (без ReportMCP)
- Немає залежності від зовнішніх серверів (ACP порт 8903, MCP порт 8902)

Langfuse tracing: промпти завантажуються з Langfuse Prompt Management.
"""
import json as _json
import os

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from config import settings, SUPERVISOR_SYSTEM_PROMPT
from langfuse_utils import get_prompt_text


# ==============================
# @tool обгортки над локальними агентами
# ==============================

@tool
def plan(request: str) -> str:
    """
    Decompose a user research request into a structured ResearchPlan.

    Use this FIRST for every research request. The planner will break down
    the request into specific search queries and specify which sources to use.

    Input: the original user research request (verbatim)
    Output: JSON-serialized ResearchPlan
    """
    # Lazy import — уникаємо circular imports і важкого старту
    from agents.planner import get_planner_agent, parse_research_plan
    print("\n[Supervisor → Planner]")
    result = get_planner_agent().invoke(
        {"messages": [{"role": "user", "content": request}]},
        {"recursion_limit": 5},
    )
    text = result["messages"][-1].content
    plan_obj = parse_research_plan(text)
    output = _json.dumps(plan_obj.model_dump(), ensure_ascii=False)
    print(f"  📎 ResearchPlan received [{len(output)} chars]")
    return output


@tool
def research(request: str) -> str:
    """
    Execute research based on a plan or specific instructions.

    Use this after plan() to gather information. The researcher uses
    web_search, read_url, and knowledge_search tools.

    Input: research instructions (plan JSON or revision requests)
    Output: comprehensive Markdown findings report
    """
    from agents.research import get_research_agent
    print("\n[Supervisor → Researcher]")
    result = get_research_agent().invoke(
        {"messages": [{"role": "user", "content": request}]},
        {"recursion_limit": 15},
    )
    text = result["messages"][-1].content
    print(f"  📎 Findings received [{len(text)} chars]")
    return text


@tool
def critique(findings: str) -> str:
    """
    Evaluate research quality through independent verification.

    Returns a JSON-serialized CritiqueResult with:
    - verdict: "APPROVE" or "REVISE"
    - is_fresh, is_complete, is_well_structured: boolean dimensions
    - strengths, gaps, revision_requests

    Input: the research findings text to evaluate
    Output: JSON-serialized CritiqueResult
    """
    from agents.critic import get_critic_agent, parse_critique_result
    print("\n[Supervisor → Critic]")
    result = get_critic_agent().invoke(
        {"messages": [{"role": "user", "content": findings}]},
        {"recursion_limit": 6},
    )
    text = result["messages"][-1].content
    critique_obj = parse_critique_result(text)
    output = _json.dumps(critique_obj.model_dump(), ensure_ascii=False)
    print(f"  📎 CritiqueResult received: verdict={critique_obj.verdict}")
    return output


@tool
def save_report(filename: str, content: str) -> str:
    """
    Save the final research report to disk.

    IMPORTANT: This is a WRITE operation — it requires human approval.
    Call this only after critique verdict is APPROVE.

    Args:
        filename: Target file name (e.g., 'rag_comparison.md')
        content: Full Markdown content of the report

    Returns: Path where the report was saved
    """
    output_dir = settings.output_dir
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"\n[Supervisor → save_report] Saved to {filepath}")
    return filepath


# ==============================
# InMemorySaver + lazy Supervisor singleton
# ==============================

# Checkpointer — зберігає стан між interrupt і resume для HITL
# Аналогія Java: HttpSession або StatefulBean
_checkpointer = InMemorySaver()
_supervisor = None


def get_supervisor():
    """Повертає supervisor, створює при першому виклику (lazy singleton)."""
    global _supervisor
    if _supervisor is None:
        # Промпт з Langfuse Prompt Management, fallback на локальний
        system_prompt = get_prompt_text("supervisor_system") or SUPERVISOR_SYSTEM_PROMPT
        _model = init_chat_model(f"openai:{settings.openai_model}", temperature=settings.temperature)
        _supervisor = create_agent(
            model=_model,
            tools=[plan, research, critique, save_report],
            system_prompt=system_prompt,
            middleware=[
                HumanInTheLoopMiddleware(
                    interrupt_on={"save_report": True},
                    description_prefix="Research report pending approval",
                ),
            ],
            checkpointer=_checkpointer,
            name="supervisor",
        )
    return _supervisor
