"""
test_e2e.py — End-to-end evaluation на golden dataset.

Що робимо:
- Завантажуємо golden_dataset.json
- Для кожного happy_path прикладу запускаємо повний pipeline:
  Planner → Researcher (без Supervisor щоб не потребувати ACP/MCP серверів)
- Оцінюємо двома метриками: AnswerRelevancyMetric + GEval Correctness

Чому Planner → Researcher, а не повний Supervisor pipeline?
- Supervisor (hw9) потребує запущених ACP і MCP серверів (acp_server.py, report_mcp.py)
- E2E тести мають запускатись автономно (CI/CD, без зовнішніх залежностей)
- Тестуємо core логіку: чи якісна відповідь на запит

Запуск:
    deepeval test run tests/test_e2e.py -v
"""
import json
import os
import pytest
from deepeval import assert_test
from deepeval.metrics import AnswerRelevancyMetric, GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from agents.planner import get_planner_agent, parse_research_plan
from agents.research import get_research_agent


# --- Завантаження golden dataset ---

# os.path.dirname(__file__) → директорія де знаходиться цей файл (tests/)
_DATASET_PATH = os.path.join(os.path.dirname(__file__), "golden_dataset.json")

with open(_DATASET_PATH, encoding="utf-8") as f:
    # json.load() — читає JSON файл у Python dict/list.
    # Аналогія Java: ObjectMapper.readValue(file, List.class)
    _ALL_EXAMPLES = json.load(f)

# Фільтруємо лише happy_path — для e2e тестів з реальним pipeline
# list comprehension — як Stream.filter().collect() у Java
_HAPPY_PATH = [ex for ex in _ALL_EXAMPLES if ex["category"] == "happy_path"]


# --- Допоміжна функція: повний pipeline ---

def run_pipeline(query: str) -> str:
    """
    Запускає Planner → Researcher pipeline і повертає фінальну відповідь.

    Кроки:
    1. Planner — декомпозує запит у ResearchPlan
    2. Researcher — виконує дослідження за планом

    Researcher отримує серіалізований план як вхідний запит.
    Це відтворює реальний flow Supervisor → plan() → research().
    """
    # Крок 1: Planner
    planner_result = get_planner_agent().invoke(
        {"messages": [{"role": "user", "content": query}]},
        {"recursion_limit": 5},
    )
    planner_text = planner_result["messages"][-1].content
    plan = parse_research_plan(planner_text)

    # Крок 2: Researcher — передаємо серіалізований план
    # plan.model_dump_json() — серіалізує Pydantic модель у JSON рядок
    # Аналогія Java: objectMapper.writeValueAsString(plan)
    research_request = (
        f"Execute research based on this plan:\n"
        f"Goal: {plan.goal}\n"
        f"Search queries: {plan.search_queries}\n"
        f"Sources: {plan.sources_to_check}\n"
        f"Output format: {plan.output_format}"
    )

    research_result = get_research_agent().invoke(
        {"messages": [{"role": "user", "content": research_request}]},
        {"recursion_limit": 15},
    )
    return research_result["messages"][-1].content


# --- Метрики ---

# AnswerRelevancyMetric — referenceless: не потребує expected_output.
# Перевіряє чи відповідь адресує запитання (без "води" і нерелевантних деталей).
answer_relevancy_metric = AnswerRelevancyMetric(
    threshold=0.7,
    model="gpt-4o-mini",
)

# GEval Correctness — reference-based: порівнює з expected_output.
# Перевіряє чи факти у відповіді не суперечать еталону.
# threshold=0.6 — нижче ніж relevancy, бо точне формулювання може відрізнятись.
correctness_metric = GEval(
    name="Correctness",
    evaluation_steps=[
        "Check whether the facts in 'actual output' contradict any facts in 'expected output'",
        "Penalize omission of critical details mentioned in 'expected output'",
        "Different wording of the same concept is acceptable — do not penalize paraphrasing",
        "If 'actual output' contains additional correct information not in 'expected output', do not penalize",
    ],
    evaluation_params=[
        LLMTestCaseParams.INPUT,
        LLMTestCaseParams.ACTUAL_OUTPUT,
        LLMTestCaseParams.EXPECTED_OUTPUT,
    ],
    model="gpt-4o-mini",
    threshold=0.6,
)


# --- Параметризовані тести на happy_path прикладах ---

# pytest.mark.parametrize з list comprehension — запускає тест для кожного happy_path прикладу.
# ids= — читабельні назви тест-кейсів у виводі pytest (замість "0", "1", "2"...).
# Аналогія Java: @MethodSource з Stream<Arguments> у JUnit 5.
@pytest.mark.parametrize(
    "example",
    _HAPPY_PATH,
    ids=[ex["input"][:50] for ex in _HAPPY_PATH],
)
def test_e2e_happy_path(example):
    """
    End-to-end тест: Planner → Researcher pipeline на happy_path прикладах.

    Запускається окремо для кожного рядка з golden_dataset.json де category=happy_path.
    """
    actual_output = run_pipeline(example["input"])

    test_case = LLMTestCase(
        input=example["input"],
        actual_output=actual_output,
        expected_output=example["expected_output"],
    )
    assert_test(test_case, [answer_relevancy_metric, correctness_metric])


# --- Тест на failure_cases: агент не галюцинує відповідь поза доменом ---

_FAILURE_CASES = [ex for ex in _ALL_EXAMPLES if ex["category"] == "failure_case"]

# GEval для перевірки що агент коректно обробляє запити поза доменом
out_of_domain_metric = GEval(
    name="Out-of-domain Handling",
    evaluation_steps=[
        "Check if the input is clearly outside the AI/ML research domain (cooking, illegal activities, real-time data)",
        "If out-of-domain: check that 'actual output' does NOT provide a detailed answer to the out-of-domain question",
        "If out-of-domain: check that 'actual output' acknowledges the limitation or redirects",
        "If the agent provides a full detailed answer to an out-of-domain request — score 0.0",
        "If the agent correctly declines or redirects — score 1.0",
    ],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    model="gpt-4o-mini",
    threshold=0.5,
)


@pytest.mark.parametrize(
    "example",
    _FAILURE_CASES,
    ids=[ex["input"][:50] for ex in _FAILURE_CASES],
)
def test_e2e_failure_cases(example):
    """
    Перевіряємо що агент адекватно реагує на запити поза доменом.

    Очікуємо: агент або відмовляє, або звужує до релевантного аспекту,
    але не надає детальну відповідь на нерелевантне питання.
    """
    # Запускаємо лише Researcher для швидкості (Planner може все одно спробувати)
    result = get_research_agent().invoke(
        {"messages": [{"role": "user", "content": example["input"]}]},
        {"recursion_limit": 5},
    )
    actual_output = result["messages"][-1].content

    test_case = LLMTestCase(
        input=example["input"],
        actual_output=actual_output,
    )
    assert_test(test_case, [out_of_domain_metric])
