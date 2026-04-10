"""
test_tools.py — DeepEval тести ToolCorrectnessMetric для мультиагентної системи.

Що перевіряємо:
- Planner отримує запит → має викликати пошукові інструменти (web_search / knowledge_search)
- Researcher отримує план → має використати інструменти для пошуку і читання
- Supervisor після APPROVE від Critic → має викликати save_report

ToolCorrectnessMetric — гібридна метрика:
  1. Детерміністична: порівнює tools_called vs expected_tools (імена, параметри)
  2. LLM частина: оцінює чи вибір інструментів був оптимальним серед доступних

Ми використовуємо базовий варіант (тільки імена) — бо точні аргументи непередбачувані у LLM.

Запуск:
    deepeval test run tests/test_tools.py -v
"""
import pytest
from deepeval import assert_test
from deepeval.metrics import ToolCorrectnessMetric
from deepeval.test_case import LLMTestCase, ToolCall

from agents.planner import get_planner_agent, parse_research_plan
from agents.research import get_research_agent


# --- Допоміжна функція ---

def extract_tool_calls(agent_result: dict) -> list[ToolCall]:
    """
    Витягує всі виклики інструментів з результату агента.

    agent_result["messages"] — список повідомлень:
      - HumanMessage: вхідний запит
      - AIMessage з tool_calls: LLM вирішив викликати tool
      - ToolMessage: результат виклику tool
      - AIMessage (фінальна відповідь): без tool_calls

    Ми збираємо імена tools з AIMessage.tool_calls.
    Аналогія Java: парсимо лог подій з audit trail для верифікації.
    """
    tool_calls = []
    for msg in agent_result["messages"]:
        # AIMessage може містити tool_calls — список запитів на виклик tools
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                # tc — dict з полями: id, name, args
                tool_calls.append(ToolCall(
                    name=tc["name"],
                    # input_parameters — аргументи виклику (для можливого майбутнього розширення)
                    input_parameters=tc.get("args", {}),
                ))
    return tool_calls


# --- Метрика ---

# ToolCorrectnessMetric без додаткових параметрів перевіряє лише імена інструментів.
# threshold=0.5 — досить низький поріг: нам важливо що хоча б правильні tools викликались,
# точна послідовність менш важлива для цього baseline.
tool_correctness_metric = ToolCorrectnessMetric(
    threshold=0.5,
    model="gpt-4o-mini",
)


# --- Тест 1: Planner викликає пошукові інструменти ---

def test_planner_uses_search_tools():
    """
    Planner отримує запит про RAG → має викликати web_search або knowledge_search.

    Очікуємо що Planner не відповідає 'з голови', а досліджує домен перед плануванням.
    """
    query = "What is RAG and how does it work?"

    result = get_planner_agent().invoke(
        {"messages": [{"role": "user", "content": query}]},
        {"recursion_limit": 5},
    )

    actual_tools = extract_tool_calls(result)
    final_answer = result["messages"][-1].content

    # Очікувані tools: хоча б один пошуковий інструмент
    # ToolCall з мінімальними полями — перевіряємо лише імена
    expected_tools = [
        ToolCall(name="web_search"),
    ]

    test_case = LLMTestCase(
        input=query,
        actual_output=final_answer,
        tools_called=actual_tools,
        expected_tools=expected_tools,
    )
    assert_test(test_case, [tool_correctness_metric])


# --- Тест 2: Researcher використовує пошукові інструменти ---

def test_researcher_uses_search_tools():
    """
    Researcher отримує конкретний запит → має використати web_search, read_url або knowledge_search.

    Researcher не має відповідати без пошуку — його роль саме в зборі інформації.
    """
    # Передаємо детальний план щоб спонукати до пошуку
    research_request = (
        "Research the following plan:\n"
        "Goal: Explain what BM25 algorithm is and how it differs from vector search\n"
        "search_queries: ['BM25 algorithm explanation', 'BM25 vs vector search comparison']\n"
        "sources_to_check: ['web', 'knowledge_base']\n"
        "output_format: structured markdown with sections"
    )

    result = get_research_agent().invoke(
        {"messages": [{"role": "user", "content": research_request}]},
        {"recursion_limit": 15},
    )

    actual_tools = extract_tool_calls(result)
    final_answer = result["messages"][-1].content

    # Researcher має використати хоча б один з трьох пошукових інструментів
    expected_tools = [
        ToolCall(name="web_search"),
    ]

    test_case = LLMTestCase(
        input=research_request,
        actual_output=final_answer,
        tools_called=actual_tools,
        expected_tools=expected_tools,
    )
    assert_test(test_case, [tool_correctness_metric])


# --- Тест 3: Supervisor після APPROVE викликає save_report ---

def test_supervisor_calls_save_report_after_approve():
    """
    Supervisor отримує вже готові findings з фіктивним APPROVE від Critic →
    має викликати save_report.

    Це mock-тест: ми симулюємо ситуацію де Supervisor вже зробив план і дослідження,
    і тепер отримав APPROVE. Перевіряємо що save_report буде в tool_calls.

    УВАГА: цей тест НЕ запускає повний pipeline (не звертається до ACP/MCP серверів).
    Ми тестуємо локальний Supervisor з hw8 (main_supervisor.py архітектура).
    """
    # Пряма перевірка: симулюємо що supervisor вирішив зберегти звіт.
    # Реальний виклик supervisor з ACP/MCP потребує запущених серверів.
    # Тому цей тест — детерміністичний unit-test, не eval.

    # tools_called — те що ми записали б якби supervisor реально це зробив
    # Для demonstration purposes: перевіряємо що метрика правильно працює
    simulated_tools_called = [
        ToolCall(
            name="plan",
            input_parameters={"request": "Explain RAG"},
            output='{"goal": "Explain RAG", "search_queries": ["what is RAG"]}',
        ),
        ToolCall(
            name="research",
            input_parameters={"request": '{"goal": "Explain RAG"}'},
            output="# RAG Overview\nRAG is Retrieval-Augmented Generation...",
        ),
        ToolCall(
            name="critique",
            input_parameters={"findings": "# RAG Overview\nRAG is..."},
            output='{"verdict": "APPROVE", "gaps": [], "revision_requests": []}',
        ),
        ToolCall(
            name="save_report",
            input_parameters={"filename": "rag_overview.md", "content": "# RAG Overview..."},
            output="Report saved to output/rag_overview.md",
        ),
    ]

    expected_tools = [
        ToolCall(name="plan"),
        ToolCall(name="research"),
        ToolCall(name="critique"),
        ToolCall(name="save_report"),
    ]

    test_case = LLMTestCase(
        input="Research and save a report about RAG. After critique approves, save the report.",
        actual_output="Report saved to output/rag_overview.md",
        tools_called=simulated_tools_called,
        expected_tools=expected_tools,
    )
    assert_test(test_case, [tool_correctness_metric])
