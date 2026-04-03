"""
Supervisor Agent — оркестратор мультиагентної системи.

Патерн: Subagents-as-Tools (Approach C з Лекції 7).
Supervisor бачить sub-агентів як звичайні tools і викликає їх у потрібному порядку.

Цикл:
  plan → research → critique → (REVISE: back to research) → save_report (HITL)

HITL (Human-in-the-Loop): save_report захищений HumanInTheLoopMiddleware —
Supervisor не може зберегти звіт без явного підтвердження користувача.

InMemorySaver — необхідний для збереження стану між interrupt та resume.
У Java це як стейтфул сесія: стан зберігається між HTTP-запитами.

Запуск для тестування (повна система з HITL):
    .venv/bin/python3 main_supervisor.py
"""
import json
from pathlib import Path

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from agents.critic import get_critic_agent, parse_critique_result
from agents.planner import get_planner_agent, parse_research_plan
from agents.research import get_research_agent
from config import settings, SUPERVISOR_SYSTEM_PROMPT
from schemas import CritiqueResult, ResearchPlan

# ==============================
# Sub-agents обгорнуті як @tool-функції для Supervisor
# ==============================
# Це ключовий патерн "Subagents as Tools":
# кожен sub-агент стає звичайним tool для Supervisor.
# Supervisor викликає їх через tool calling — так само як web_search або write_file.


@tool
def plan(request: str) -> str:
    """
    Decompose a user research request into a structured ResearchPlan.

    Use this FIRST for every research request. The planner will:
    - Do preliminary searches to understand the domain
    - Break down the request into specific search queries
    - Specify which sources to use (web, knowledge_base, or both)
    - Define the expected output format

    Input: the original user research request (verbatim)
    Output: JSON-serialized ResearchPlan
    """
    print("\n[Supervisor → Planner]")
    # recursion_limit=5 — Planner робить max 1 tool call + 1 structured output
    result = get_planner_agent().invoke(
        {"messages": [{"role": "user", "content": request}]},
        {"recursion_limit": 5},
    )

    # Planner повертає вільний текст із JSON-блоком.
    # parse_research_plan() шукає JSON і валідує через Pydantic.
    last_message = result["messages"][-1].content
    research_plan: ResearchPlan = parse_research_plan(last_message)
    plan_json = research_plan.model_dump_json(indent=2)

    print(f"  📎 ResearchPlan:\n{plan_json}")
    return plan_json


@tool
def research(request: str) -> str:
    """
    Execute research based on a plan or specific instructions.

    Use this after plan() to actually gather information. Pass either:
    - The JSON ResearchPlan from plan() tool
    - Specific revision_requests from critique() if REVISE verdict

    The researcher will use web_search, read_url, and knowledge_search
    to gather comprehensive information and return a Markdown report.

    Input: research instructions (plan JSON or revision requests)
    Output: comprehensive Markdown findings report
    """
    print("\n[Supervisor → Researcher]")
    # recursion_limit=8 — max 3 tool calls + synthesis (кожен tool call = 2 кроки у LangGraph)
    result = get_research_agent().invoke(
        {"messages": [{"role": "user", "content": request}]},
        {"recursion_limit": 8},
    )

    # research_agent повертає вільний текст (Markdown-звіт)
    findings = result["messages"][-1].content
    print(f"  📎 Findings: [{len(findings)} chars]")
    return findings


@tool
def critique(findings: str) -> str:
    """
    Evaluate research quality through independent verification.

    The critic will:
    - Verify freshness by searching for newer information
    - Check completeness against the original request
    - Assess structure quality

    Returns a JSON-serialized CritiqueResult with:
    - verdict: "APPROVE" or "REVISE"
    - is_fresh, is_complete, is_well_structured: boolean dimensions
    - strengths: what's good
    - gaps: what's missing
    - revision_requests: specific fixes needed (if REVISE)

    Input: the research findings text to evaluate
    Output: JSON-serialized CritiqueResult
    """
    print("\n[Supervisor → Critic]")
    # recursion_limit=6 — max 1 tool call + JSON output
    result = get_critic_agent().invoke(
        {"messages": [{"role": "user", "content": findings}]},
        {"recursion_limit": 6},
    )

    # Critic повертає вільний текст із JSON-блоком.
    # parse_critique_result() шукає JSON і валідує через Pydantic.
    last_message = result["messages"][-1].content
    critique_result: CritiqueResult = parse_critique_result(last_message)
    critique_json = critique_result.model_dump_json(indent=2)

    print(f"  📎 CritiqueResult: verdict={critique_result.verdict}")
    return critique_json


@tool
def save_report(filename: str, content: str) -> str:
    """
    Save the final research report to disk.

    IMPORTANT: This is a WRITE operation — it requires human approval.
    The supervisor should call this only after critique verdict is APPROVE.

    Args:
        filename: Target file name (e.g., 'rag_comparison.md')
        content: Full Markdown content of the report

    Returns: Path where the report was saved
    """
    print(f"\n[Supervisor → save_report] filename={filename!r}")

    # Безпечне ім'я файлу — захист від path traversal атаки
    # Path(filename).name — залишає лише ім'я файлу без шляху
    safe_name = Path(filename.strip()).name or "report.md"
    if not safe_name.endswith(".md"):
        safe_name += ".md"

    # Зберігаємо в ./output/ (дефолтна директорія для звітів)
    output_dir = Path("output")
    output_dir.mkdir(parents=True, exist_ok=True)
    target_path = output_dir / safe_name
    target_path.write_text(content, encoding="utf-8")

    print(f"  📎 Report saved to {target_path}")
    return f"Report saved to: {target_path}"



# ==============================
# InMemorySaver — обов'язковий для HITL
# ==============================
# Checkpointer зберігає стан графа між interrupt і resume.
# Один checkpointer на весь процес — ініціалізується одразу (не потребує API ключа).
# У Java — аналог: HttpSession або StateStore для stateful workflows.
_checkpointer = InMemorySaver()

# ==============================
# Supervisor з HITL middleware (lazy ініціалізація)
# ==============================
_supervisor = None


def get_supervisor():
    """Повертає supervisor, створює при першому виклику (lazy singleton)."""
    global _supervisor
    if _supervisor is None:
        _model = init_chat_model(f"openai:{settings.openai_model}", temperature=settings.temperature)
        _supervisor = create_agent(
            model=_model,
            tools=[plan, research, critique, save_report],
            system_prompt=SUPERVISOR_SYSTEM_PROMPT,
            middleware=[
                # HumanInTheLoopMiddleware — перехоплює tool calls перед виконанням
                # interrupt_on={"save_report": True} — save_report потребує схвалення
                # True означає: дозволено всі рішення (approve, edit, reject)
                HumanInTheLoopMiddleware(
                    interrupt_on={"save_report": True},
                    description_prefix="Research report pending approval",
                ),
            ],
            # checkpointer — ОБОВ'ЯЗКОВИЙ для збереження стану при interrupt
            checkpointer=_checkpointer,
            name="supervisor",
        )
    return _supervisor
