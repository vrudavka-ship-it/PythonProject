"""
test_critic.py — DeepEval тести для Critic Agent.

Що перевіряємо:
- GEval Critique Quality: критика конкретна, actionable, verdict відповідає наповненню
- Сценарій APPROVE: хороше дослідження → вердикт APPROVE, gaps порожні/мінімальні
- Сценарій REVISE: неповне дослідження → вердикт REVISE, є конкретні revision_requests

Запуск:
    deepeval test run tests/test_critic.py -v
"""
import pytest
from deepeval import assert_test
from deepeval.metrics import GEval
from deepeval.test_case import LLMTestCase, LLMTestCaseParams

from agents.critic import get_critic_agent, parse_critique_result


# --- Тестові дані: приклади досліджень для критики ---

# Якісне дослідження — очікуємо APPROVE
GOOD_RESEARCH = """# RAG: Retrieval-Augmented Generation

## Overview
RAG (Retrieval-Augmented Generation) is an architectural approach that augments a language
model with external knowledge retrieved at inference time.

## How It Works
1. **Ingestion**: Documents are split into chunks (typically 500 tokens with overlap),
   converted to embeddings using models like text-embedding-3-small, and stored in a
   vector database (FAISS, Pinecone, Milvus).
2. **Retrieval**: For each user query, the system finds the most relevant chunks using
   cosine similarity between query embedding and stored embeddings.
3. **Generation**: The retrieved chunks are injected into the LLM prompt as context,
   allowing the model to answer grounded in the provided documents.

## Advantages over fine-tuning
- No retraining required when knowledge base updates
- Transparent sourcing of information
- Works with proprietary documents

## Key metrics
- Context Recall: are all necessary documents retrieved?
- Faithfulness: does the answer contradict the context?
- Answer Relevancy: is the answer relevant to the question?

## Sources
- LangChain documentation (2024)
- Pinecone RAG guide (2024)
- Lewis et al., "Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks" (2020)
"""

# Погане дослідження — очікуємо REVISE
BAD_RESEARCH = """# RAG

RAG is a thing in AI. It uses documents somehow.
It is very popular.

## Summary
RAG is good.
"""


# --- Допоміжна функція ---

def run_critic(research_text: str) -> tuple[str, object]:
    """
    Запускає Critic Agent і повертає (raw_text, CritiqueResult).

    Повертаємо обидва: raw_text для LLMTestCase, CritiqueResult для додаткових перевірок.
    """
    result = get_critic_agent().invoke(
        {"messages": [{"role": "user", "content": research_text}]},
        {"recursion_limit": 6},
    )
    raw_text = result["messages"][-1].content
    critique = parse_critique_result(raw_text)
    return raw_text, critique


# --- Метрика ---

# GEval Critique Quality — наша кастомна бізнес-метрика для критики.
# Це приклад "кастомної метрики під бізнес-логіку" з вимог домашки.
critique_quality_metric = GEval(
    name="Critique Quality",
    evaluation_steps=[
        "Check that the critique identifies specific issues, not vague complaints like 'could be better'",
        "Check that revision_requests (if present) are actionable — a researcher can act on them",
        "If verdict is APPROVE, gaps list should be empty or contain only minor stylistic items",
        "If verdict is REVISE, there must be at least one specific revision_request",
        "Check that the critique is consistent: verdict matches the severity of identified gaps",
    ],
    evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
    model="gpt-4o-mini",
    threshold=0.7,
)


# --- Тести ---

def test_critique_approves_good_research():
    """Critic дає APPROVE для якісного дослідження з конкретними джерелами."""
    raw_text, critique = run_critic(GOOD_RESEARCH)

    test_case = LLMTestCase(
        input=GOOD_RESEARCH,
        actual_output=raw_text,
    )
    assert_test(test_case, [critique_quality_metric])

    # Додаткова детерміністична перевірка: вердикт має бути APPROVE
    # Це класичний assert — без LLM, просто перевірка значення
    assert critique.verdict == "APPROVE", (
        f"Expected APPROVE for good research, got {critique.verdict}. "
        f"Gaps: {critique.gaps}"
    )


def test_critique_revises_bad_research():
    """Critic дає REVISE для поверхневого дослідження без джерел."""
    raw_text, critique = run_critic(BAD_RESEARCH)

    test_case = LLMTestCase(
        input=BAD_RESEARCH,
        actual_output=raw_text,
    )
    assert_test(test_case, [critique_quality_metric])

    # Детерміністична перевірка: вердикт має бути REVISE
    assert critique.verdict == "REVISE", (
        f"Expected REVISE for bad research, got {critique.verdict}. "
        f"Strengths: {critique.strengths}"
    )

    # Перевіряємо що є конкретні запити на виправлення
    assert len(critique.revision_requests) > 0, (
        "REVISE verdict must include at least one revision_request"
    )
