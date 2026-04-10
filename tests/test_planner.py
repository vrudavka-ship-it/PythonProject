"""
test_planner.py — DeepEval тести для Planner Agent.

Що перевіряємо:
- GEval Plan Quality: чи план містить конкретні пошукові запити, релевантні джерела,
  відповідний output_format
- Тест з нормальним запитом (happy path)
- Тест з edge case (надто широкий запит)

Запуск:
    deepeval test run tests/test_planner.py -v
    # або через pytest напряму:
    .venv/bin/python3 -m pytest tests/test_planner.py -v
"""
import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

# Імпортуємо агента — conftest.py вже налаштував sys.path і os.environ
from agents.planner import get_planner_agent, parse_research_plan


# --- Допоміжна функція ---

def run_planner(query: str) -> str:
    """
    Запускає Planner Agent і повертає текст відповіді.

    Публічна функція для використання у тестах — виклик агента і витяг тексту.
    Аналогія Java: це як test helper method, що готує дані для assertions.
    """
    result = get_planner_agent().invoke(
        {"messages": [{"role": "user", "content": query}]},
        {"recursion_limit": 5},
    )
    return result["messages"][-1].content


# --- Метрика ---

# GEval — кастомна LLM-as-a-Judge метрика.
# evaluation_steps описують критерії оцінки природною мовою.
# LLM-суддя (gpt-4o-mini) проходить ці кроки і виставляє score 0–1.
# Аналогія Java: це як custom Comparator, але для семантичної якості.
plan_quality_metric = GEval(
    name="Plan Quality",
    evaluation_steps=[
        "Check that 'actual output' contains specific search queries (not vague phrases like 'research the topic')",
        "Check that 'actual output' includes sources_to_check with at least one of: 'web', 'knowledge_base'",
        "Check that 'actual output' specifies an output_format describing the expected report structure",
        "Check that the goal in 'actual output' is specific and relevant to the user's 'input'",
    ],
    # evaluation_params — які поля LLMTestCase передаємо судді
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    model="gpt-4o-mini",
    threshold=0.7,
)


# --- Тести ---

# @pytest.mark.parametrize — запускає один тест з кількома наборами параметрів.
# Аналогія Java: це як @ParameterizedTest з @ValueSource у JUnit 5.
@pytest.mark.parametrize("query", [
    "What is RAG and how does it work?",
    "Compare naive RAG vs sentence-window retrieval",
])
def test_plan_quality_happy_path(query):
    """Planner повертає якісний структурований план для типових запитів."""
    actual_output = run_planner(query)

    test_case = LLMTestCase(
        input=query,
        actual_output=actual_output,
    )
    assert_test(test_case, [plan_quality_metric])


def test_plan_quality_broad_query():
    """Planner обробляє широкий запит — план має бути конкретнішим за сам запит."""
    query = "Tell me everything about all AI topics ever"
    actual_output = run_planner(query)

    test_case = LLMTestCase(
        input=query,
        actual_output=actual_output,
    )
    # Для edge case знижуємо поріг: очікуємо гірший результат, але не провал
    # threshold=0.5 — це наш baseline для складних запитів
    edge_metric = GEval(
        name="Plan Quality (edge case)",
        evaluation_steps=[
            "Check that 'actual output' contains at least 2 specific search queries",
            "Check that 'actual output' includes some sources_to_check",
            "If the query is very broad, check that the plan narrows it down to manageable subtopics",
        ],
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        model="gpt-4o-mini",
        threshold=0.5,
    )
    assert_test(test_case, [edge_metric])
