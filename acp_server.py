"""
acp_server.py — ACP сервер з трьома агентами (порт 8903).

ACP (Agent Communication Protocol) — стандартний протокол для agent-to-agent комунікації.
Кожен агент доступний як HTTP endpoint: POST /agents/{name}/runs

Агенти:
  - planner   → декомпозує запит у ResearchPlan (підключається до SearchMCP)
  - researcher → збирає інформацію і пише Markdown-звіт (SearchMCP)
  - critic     → перевіряє якість дослідження (SearchMCP)

Кожен агент:
  1. Підключається до SearchMCP через fastmcp.Client
  2. Конвертує MCP tools у LangChain format через mcp_tools_to_langchain()
  3. Створюється через create_agent() з system prompt з config.py
  4. Повертає результат як Message(role="agent", ...)

Аналогія з Java:
  ACP Server ≈ Spring Boot REST controller з @PostMapping("/agents/{name}/runs")
  Кожен @acp_server.agent ≈ @RestController метод що делегує до сервісу

Запуск:
    .venv/bin/python3 acp_server.py   # порт 8903
"""
import os
import sys

# sys.path fix — щоб знаходити config, tools, schemas при запуску напряму
_project_root = os.path.dirname(os.path.abspath(__file__))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Встановлюємо API ключі до будь-яких LangChain імпортів
from config import settings, ACP_PORT, MCP_SEARCH_URL
from config import PLANNER_SYSTEM_PROMPT, RESEARCH_SYSTEM_PROMPT, CRITIC_SYSTEM_PROMPT
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key)

from acp_sdk.models import Message, MessagePart
from acp_sdk.server import Server
from fastmcp import Client as MCPClient
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model

from mcp_utils import mcp_tools_to_langchain
from agents.planner import parse_research_plan
from agents.critic import parse_critique_result

# ACP Server — оркестратор реєстрації агентів
# Аналогія Java: ApplicationContext що керує @Component bean-ами
acp_server = Server()


# ==============================
# Допоміжна функція: створення агента з MCP tools
# ==============================

async def _create_agent_with_mcp(system_prompt: str, recursion_limit: int = 10):
    """
    Контекстний менеджер, що підключається до SearchMCP і повертає (agent, mcp_client).

    Використовується у кожному ACP handler для lazy створення агента.
    Async бо fastmcp.Client — async context manager.

    Аналогія Java: factory method що відкриває DB connection і повертає Service
    """
    # MCPClient — async підключення до SearchMCP HTTP endpoint
    # Аналогія Java: try-with-resources HttpClient
    mcp_client = MCPClient(MCP_SEARCH_URL)
    await mcp_client.__aenter__()

    # list_tools() — отримуємо список доступних MCP tools
    mcp_tools = await mcp_client.list_tools()

    # mcp_tools_to_langchain() — конвертуємо MCP tools у LangChain StructuredTool
    lc_tools = mcp_tools_to_langchain(mcp_tools, mcp_client)

    # init_chat_model — lazy ініціалізація LLM
    model = init_chat_model(
        f"openai:{settings.openai_model}",
        temperature=settings.temperature,
    )

    # create_agent() — LangGraph агент з ReAct loop
    # tools — список LangChain tools (в нашому випадку — конвертовані MCP tools)
    agent = create_agent(
        model=model,
        tools=lc_tools,
        system_prompt=system_prompt,
    )

    return agent, mcp_client


# ==============================
# ACP Agent: planner
# ==============================
# @acp_server.agent — реєструє async функцію як ACP агент
# name= — ім'я для discovery і виклику: POST /agents/planner/runs
# description= — метадані для discovery

@acp_server.agent(
    name="planner",
    description="Decomposes a research request into a structured ResearchPlan using SearchMCP tools.",
)
async def planner_handler(input: list[Message]) -> Message:
    """
    Planner ACP agent handler.

    Отримує список Message від клієнта (Supervisor).
    Підключається до SearchMCP, створює Planner агента, запускає.
    Повертає ResearchPlan як JSON у Message.

    input: list[Message] — ACP формат вхідних даних (як List<Message> у Java)
    returns: Message — ACP формат відповіді
    """
    # Витягуємо текст запиту з останнього повідомлення
    # input[-1] — останнє повідомлення, parts[0] — перша частина
    user_text = input[-1].parts[0].content
    print(f"\n[ACP Planner] request: {user_text[:100]!r}...")

    agent, mcp_client = await _create_agent_with_mcp(
        system_prompt=PLANNER_SYSTEM_PROMPT,
        recursion_limit=5,  # Planner: 1 tool call + structured output
    )

    try:
        # ainvoke() — async варіант invoke() (LangGraph підтримує async)
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_text}]},
            {"recursion_limit": 5},
        )

        last_message = result["messages"][-1].content
        # parse_research_plan() — парсить JSON із відповіді (без response_format)
        research_plan = parse_research_plan(last_message)
        plan_json = research_plan.model_dump_json(indent=2)

        print(f"[ACP Planner] → ResearchPlan: goal={research_plan.goal!r}")

        # Message(role="agent", ...) — стандартний ACP формат відповіді
        # MessagePart(content=...) — частина повідомлення з текстовим контентом
        return Message(role="agent", parts=[MessagePart(content=plan_json)])

    finally:
        # Закриваємо MCP клієнт після використання
        # Аналогія Java: connection.close() у finally блоці
        await mcp_client.__aexit__(None, None, None)


# ==============================
# ACP Agent: researcher
# ==============================

@acp_server.agent(
    name="researcher",
    description="Gathers information using SearchMCP tools and produces a Markdown research report.",
)
async def researcher_handler(input: list[Message]) -> Message:
    """
    Researcher ACP agent handler.

    Отримує план або інструкції (JSON план або revision_requests від Critic).
    Виконує пошук через SearchMCP і повертає Markdown-звіт.
    """
    user_text = input[-1].parts[0].content
    print(f"\n[ACP Researcher] request: {user_text[:100]!r}...")

    agent, mcp_client = await _create_agent_with_mcp(
        system_prompt=RESEARCH_SYSTEM_PROMPT,
        recursion_limit=8,  # max 3 tool calls + synthesis
    )

    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_text}]},
            {"recursion_limit": 8},
        )

        findings = result["messages"][-1].content
        print(f"[ACP Researcher] → findings: [{len(findings)} chars]")

        return Message(role="agent", parts=[MessagePart(content=findings)])

    finally:
        await mcp_client.__aexit__(None, None, None)


# ==============================
# ACP Agent: critic
# ==============================

@acp_server.agent(
    name="critic",
    description="Evaluates research quality through independent verification using SearchMCP. Returns CritiqueResult.",
)
async def critic_handler(input: list[Message]) -> Message:
    """
    Critic ACP agent handler.

    Отримує текст дослідження.
    Незалежно верифікує через SearchMCP і повертає CritiqueResult як JSON.
    """
    user_text = input[-1].parts[0].content
    print(f"\n[ACP Critic] request: [{len(user_text)} chars]")

    agent, mcp_client = await _create_agent_with_mcp(
        system_prompt=CRITIC_SYSTEM_PROMPT,
        recursion_limit=6,  # max 1 tool call + JSON output
    )

    try:
        result = await agent.ainvoke(
            {"messages": [{"role": "user", "content": user_text}]},
            {"recursion_limit": 6},
        )

        last_message = result["messages"][-1].content
        # parse_critique_result() — парсить CritiqueResult з відповіді
        critique_result = parse_critique_result(last_message)
        critique_json = critique_result.model_dump_json(indent=2)

        print(f"[ACP Critic] → verdict={critique_result.verdict}")

        return Message(role="agent", parts=[MessagePart(content=critique_json)])

    finally:
        await mcp_client.__aexit__(None, None, None)


# ==============================
# Точка входу
# ==============================

if __name__ == "__main__":
    print(f"Starting ACP server on port {ACP_PORT}...")
    print(f"  Agents: planner, researcher, critic")
    print(f"  URL:    http://127.0.0.1:{ACP_PORT}")
    print(f"  SearchMCP: {MCP_SEARCH_URL}")
    # server.run() — запускає uvicorn HTTP сервер
    # Аналогія Java: SpringApplication.run()
    acp_server.run(port=ACP_PORT)
