"""
Supervisor Agent — оркестратор мультиагентної системи (homework-lesson-9).

Порівняно з hw8:
- Sub-агенти (planner, researcher, critic) виклика через ACP протокол
  замість прямих Python викликів (acp_sdk.client.Client → run_sync)
- save_report викликається через ReportMCP (fastmcp.Client) замість прямого запису файлу

Патерн: Supervisor як локальний create_agent, tools якого — обгортки над ACP/MCP викликами.
Це дозволяє Supervisor не знати нічого про імплементацію sub-агентів.

HITL залишається: HumanInTheLoopMiddleware(interrupt_on={"save_report": True}).
InMemorySaver — обов'язковий для збереження стану між interrupt і resume.

Async/sync проблема:
- create_agent (LangGraph) — sync інтерфейс для tools (tool function = sync callable)
- ACP client і MCP client — async
- Рішення: asyncio.run() всередині кожного @tool для виклику async коду з sync context

Запуск повної системи:
    # Термінал 1: .venv/bin/python3 mcp_servers/search_mcp.py
    # Термінал 2: .venv/bin/python3 mcp_servers/report_mcp.py
    # Термінал 3: .venv/bin/python3 acp_server.py
    # Термінал 4: .venv/bin/python3 main.py
"""
import asyncio

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver

from config import settings, SUPERVISOR_SYSTEM_PROMPT, ACP_BASE_URL, MCP_REPORT_URL


def _sanitize(text: str) -> str:
    """Видаляє surrogate символи які ламають OpenAI JSON encoder."""
    import re
    return re.sub(r"[\ud800-\udfff]", "", text)
# langfuse_utils імпортуємо тут — щоб LANGFUSE_* вже були в os.environ
# (вони встановлюються в main_supervisor.py до імпорту supervisor)
from langfuse_utils import langfuse_handler, get_prompt_text


# ==============================
# Допоміжна функція: запуск async з sync контексту
# ==============================

def _run_async(coro):
    """
    Запускає async coroutine з синхронного коду.

    Проблема: @tool функції — синхронні, але ACP/MCP клієнти — async.
    asyncio.run() — запускає новий event loop, виконує coroutine, повертає результат.

    Аналогія Java: CompletableFuture.get() — блокує потік до завершення async операції.

    Важливо: asyncio.run() не можна викликати з вже існуючого event loop
    (це б спричинило RuntimeError: "This event loop is already running").
    У нашому випадку supervisor.stream() — sync, тому event loop не активний.
    """
    return asyncio.run(coro)


# ==============================
# Async виклики ACP агентів
# ==============================

async def _call_acp_agent(agent_name: str, message: str) -> str:
    """
    Async виклик ACP агента через acp_sdk.client.Client.

    ACP протокол:
    1. Клієнт підключається до ACP сервера (http://127.0.0.1:8903)
    2. Відправляє Message(role="user", parts=[MessagePart(content=...)])
    3. Очікує відповідь у форматі run.output[-1].parts[0].content

    Аналогія Java: RestTemplate.postForObject() або WebClient.post().retrieve()
    """
    # Імпорт тут — уникаємо circular imports і важких залежностей при старті
    from acp_sdk.client import Client as ACPClient
    from acp_sdk.models import Message, MessagePart

    # async with — автоматично закриває з'єднання після виходу з блоку
    # headers — додаємо Content-Type: application/json (acp-sdk 1.0.3 надсилає bytes без типу)
    # Аналогія Java: try-with-resources HttpClient
    async with ACPClient(
        base_url=ACP_BASE_URL,
        headers={"Content-Type": "application/json"},
    ) as client:
        # run_sync() — запускає агента і чекає на відповідь (synchronous run)
        # agent= — назва агента (planner / researcher / critic)
        # input= — список повідомлень у ACP форматі
        run = await client.run_sync(
            agent=agent_name,
            input=[Message(role="user", parts=[MessagePart(content=message)])],
        )
        # run.output — список відповідних Message від агента
        # Беремо останнє повідомлення, першу частину, текстовий контент
        raw = run.output[-1].parts[0].content
        return _sanitize(raw)


async def _call_report_mcp(filename: str, content: str) -> str:
    """
    Async виклик save_report tool через ReportMCP (fastmcp.Client).

    fastmcp.Client — async HTTP клієнт для MCP серверів.
    call_tool() — викликає конкретний tool на сервері.

    Аналогія Java: WebClient.post().uri("/tools/save_report").retrieve()
    """
    from fastmcp import Client as MCPClient

    async with MCPClient(MCP_REPORT_URL) as client:
        # call_tool() — виклик MCP tool за назвою з параметрами
        # Параметри передаються як dict (як JSON body у REST)
        result = await client.call_tool("save_report", {
            "filename": filename,
            "content": content,
        })
        # result — list TextContent/ImageContent, конвертуємо у str
        return str(result)


# ==============================
# @tool обгортки над ACP/MCP викликами для Supervisor
# ==============================
# Supervisor бачить ці функції як звичайні LangChain tools.
# Всередині — async виклики через asyncio.run().

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
    print("\n[Supervisor → ACP → Planner]")
    # asyncio.run() — sync обгортка над async ACP виклику
    result = _sanitize(_run_async(_call_acp_agent("planner", request)))
    print(f"  📎 ResearchPlan received [{len(result)} chars]")
    return result


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
    print("\n[Supervisor → ACP → Researcher]")
    result = _sanitize(_run_async(_call_acp_agent("researcher", request)))
    print(f"  📎 Findings received [{len(result)} chars]")
    return result


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
    print("\n[Supervisor → ACP → Critic]")
    result = _run_async(_call_acp_agent("critic", findings))
    # Витягуємо verdict для логування (шукаємо у JSON)
    import json as _json
    result = _sanitize(result)
    try:
        data = _json.loads(result)
        verdict = data.get("verdict", "?")
    except Exception:
        verdict = "?"
    print(f"  📎 CritiqueResult received: verdict={verdict}")
    return result


@tool
def save_report(filename: str, content: str) -> str:
    """
    Save the final research report to disk via ReportMCP.

    IMPORTANT: This is a WRITE operation — it requires human approval.
    The supervisor should call this only after critique verdict is APPROVE.

    Args:
        filename: Target file name (e.g., 'rag_comparison.md')
        content: Full Markdown content of the report

    Returns: Path where the report was saved
    """
    print(f"\n[Supervisor → MCP → ReportMCP → save_report] filename={filename!r}")
    result = _run_async(_call_report_mcp(filename, content))
    print(f"  📎 {result}")
    return result


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
        # Завантажуємо system prompt з Langfuse Prompt Management.
        # get_prompt_text() повертає None якщо промпт не знайдено → fallback на локальний.
        system_prompt = get_prompt_text("supervisor_system") or SUPERVISOR_SYSTEM_PROMPT
        _model = init_chat_model(f"openai:{settings.openai_model}", temperature=settings.temperature)
        _supervisor = create_agent(
            model=_model,
            tools=[plan, research, critique, save_report],
            system_prompt=system_prompt,
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
