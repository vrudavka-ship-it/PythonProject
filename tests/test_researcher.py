"""
test_researcher.py — DeepEval тести для Research Agent.

Що перевіряємо:
- GEval Groundedness: кожне фактичне твердження у відповіді має бути підкріплене
  retrieval_context (не просто не суперечити — а саме підкріплене).

ВАЖЛИВО: Ми використовуємо кастомний GEval Groundedness, а НЕ вбудований FaithfulnessMetric.
Причина: FaithfulnessMetric перевіряє лише відсутність суперечностей з контекстом.
Вигадані факти, яких немає в контексті але й не суперечать — вона пропускає.
GEval Groundedness строгіший: score = grounded_claims / total_claims.

Запуск:
    deepeval test run tests/test_researcher.py -v
"""
import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from agents.research import get_research_agent


# --- Допоміжна функція ---

def run_researcher(query: str) -> tuple[str, list[str]]:
    """
    Запускає Research Agent і повертає (відповідь, список контекстних фрагментів).

    tuple[str, list[str]] — як Pair<String, List<String>> у Java.
    Повертаємо контекст зі стану агента для перевірки groundedness.
    """
    result = get_research_agent().invoke(
        {"messages": [{"role": "user", "content": query}]},
        {"recursion_limit": 15},
    )
    final_answer = result["messages"][-1].content

    # Збираємо всі tool-результати як retrieval_context.
    # AIMessage з tool_calls + ToolMessage — це послідовність в messages списку.
    # Аналогія Java: це як читати всі проміжні результати з черги повідомлень.
    retrieval_context = []
    for msg in result["messages"]:
        # ToolMessage містить результат виклику інструменту (web_search, knowledge_search, тощо)
        if hasattr(msg, "content") and hasattr(msg, "name"):
            if msg.content and isinstance(msg.content, str) and len(msg.content) > 20:
                retrieval_context.append(msg.content)

    # Якщо контекст порожній (агент відповів без tool calls) — додаємо заглушку
    if not retrieval_context:
        retrieval_context = ["No retrieval context available — agent answered from training data"]

    return final_answer, retrieval_context


# --- Метрика ---

# GEval Groundedness — строга перевірка: кожне твердження має бути підкріплене контекстом.
# Відрізняється від FaithfulnessMetric: там score=1.0 якщо немає суперечностей,
# тут score = частка тверджень, що ПІДТВЕРДЖЕНІ контекстом.
groundedness_metric = GEval(
    name="Groundedness",
    evaluation_steps=[
        "Extract every factual claim from 'actual output'",
        "For each claim, check if it can be directly supported by information in 'retrieval context'",
        "Claims not present in retrieval context count as ungrounded, even if they are generally true",
        "Score = number of grounded claims / total number of claims",
        "If there are no factual claims, score 0.5 (neutral)",
    ],
    evaluation_params=[
        LLMTestCaseParams.ACTUAL_OUTPUT,
        LLMTestCaseParams.RETRIEVAL_CONTEXT,
    ],
    model="gpt-4o-mini",
    threshold=0.7,
)


# --- Тести ---

def test_research_grounded_rag():
    """Research Agent дає відповідь підкріплену знайденим контекстом (тема RAG)."""
    query = "What is RAG and how does it work?"
    actual_output, retrieval_context = run_researcher(query)

    test_case = LLMTestCase(
        input=query,
        actual_output=actual_output,
        retrieval_context=retrieval_context,
    )
    assert_test(test_case, [groundedness_metric])


def test_research_grounded_multiagent():
    """
    Research Agent дає відповідь підкріплену контекстом (тема multi-agent systems).

    Знижений поріг (0.5) — наша knowledge base не містить спеціалізованих документів
    по multi-agent patterns, тому агент може відповідати частково з training data.
    Це відображає реальний baseline системи — ціль зафіксувати поточний рівень.
    """
    query = "What is a multi-agent system and what are the main interaction patterns?"
    actual_output, retrieval_context = run_researcher(query)

    test_case = LLMTestCase(
        input=query,
        actual_output=actual_output,
        retrieval_context=retrieval_context,
    )
    # threshold=0.5 — знижений baseline: knowledge base не покриває цю тему повністю
    multiagent_groundedness = GEval(
        name="Groundedness (multi-agent)",
        evaluation_steps=[
            "Extract every factual claim from 'actual output'",
            "For each claim, check if it can be directly supported by information in 'retrieval context'",
            "Claims not present in retrieval context count as ungrounded, even if they are generally true",
            "Score = number of grounded claims / total number of claims",
            "If there are no factual claims, score 0.5 (neutral)",
        ],
        evaluation_params=[
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.RETRIEVAL_CONTEXT,
        ],
        model="gpt-4o-mini",
        threshold=0.5,
    )
    assert_test(test_case, [multiagent_groundedness])


def test_research_edge_case_broad():
    """Research Agent обробляє широкий запит — перевіряємо з нижчим порогом."""
    query = "Tell me everything about all AI topics ever"
    actual_output, retrieval_context = run_researcher(query)

    test_case = LLMTestCase(
        input=query,
        actual_output=actual_output,
        retrieval_context=retrieval_context,
    )
    # Нижчий поріг для edge case — очікуємо що агент звузить тему,
    # але не все може бути підкріплено контекстом
    edge_groundedness = GEval(
        name="Groundedness (edge case)",
        evaluation_steps=[
            "Extract every factual claim from 'actual output'",
            "For each claim, check if it can be supported by 'retrieval context'",
            "For very broad queries it is acceptable if agent focuses on a subset of topics",
            "Score = grounded claims / total claims",
        ],
        evaluation_params=[
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.RETRIEVAL_CONTEXT,
        ],
        model="gpt-4o-mini",
        threshold=0.5,
    )
    assert_test(test_case, [edge_groundedness])
