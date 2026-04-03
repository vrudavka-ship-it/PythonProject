"""
Pydantic-моделі для структурованого виводу між агентами.

Навіщо Pydantic?
- У Java ти описував би ці структури через POJO-класи з анотаціями (@NotNull, @Valid і т.д.)
- Pydantic — це Python-аналог: клас + Field-анотації → автоматична валідація + JSON серіалізація
- Тут моделі використовуються як "контракти" між агентами (agent-to-agent communication)

BaseModel — базовий клас Pydantic, як якщо б ти імплементував Serializable + Builder у Java.
"""
from typing import Literal

from pydantic import BaseModel, Field


class ResearchPlan(BaseModel):
    """
    Структурований план дослідження від Planner Agent.

    Planner декомпозує запит користувача на конкретні кроки дослідження.
    Supervisor читає цей план і передає його Researcher Agent.

    Аналогія з Java: це як DTO (Data Transfer Object) між шарами застосунку.
    """

    # Мета дослідження — що саме ми намагаємось з'ясувати
    goal: str = Field(description="What we are trying to answer")

    # Конкретні пошукові запити для виконання
    # list[str] — як List<String> у Java
    search_queries: list[str] = Field(description="Specific queries to execute")

    # Джерела для перевірки: 'knowledge_base', 'web', або обидва
    sources_to_check: list[str] = Field(description="'knowledge_base', 'web', or both")

    # Опис очікуваного формату фінального звіту
    output_format: str = Field(description="What the final report should look like")


class CritiqueResult(BaseModel):
    """
    Структурований результат оцінки від Critic Agent.

    Critic не просто рецензує текст — він незалежно верифікує знахідки
    через ті самі джерела (web_search, knowledge_search).

    verdict: Literal["APPROVE", "REVISE"] — це як enum з двома значеннями.
    Literal у Python — аналог enum у Java, але простіший.
    """

    # Фінальний вердикт: APPROVE (дослідження якісне) або REVISE (потрібне доопрацювання)
    # Field з description — підказка для LLM яке значення очікується
    verdict: Literal["APPROVE", "REVISE"] = Field(
        description="Final verdict: APPROVE if research is good, REVISE if it needs more work"
    )

    # Чи актуальні дані? Чи є новіші джерела?
    is_fresh: bool = Field(description="Is the data up-to-date and based on recent sources?")

    # Чи повністю покриває дослідження оригінальний запит?
    is_complete: bool = Field(description="Does the research fully cover the user's original request?")

    # Чи добре організовані знахідки для звіту?
    is_well_structured: bool = Field(description="Are findings logically organized and ready for a report?")

    # Сильні сторони дослідження
    strengths: list[str] = Field(description="What is good about the research")

    # Що відсутнє, застаріле або погано структуроване
    gaps: list[str] = Field(description="What is missing, outdated, or poorly structured")

    # Конкретні запити на доопрацювання (якщо verdict == "REVISE")
    revision_requests: list[str] = Field(description="Specific things to fix if verdict is REVISE")
