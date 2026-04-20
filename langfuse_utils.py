"""
Langfuse utilities — централізована ініціалізація observability (homework-lesson-12).

Цей модуль відповідає за:
1. Langfuse клієнт (singleton) — для create_score, get_prompt, flush
2. CallbackHandler — передається у RunnableConfig для авто-трейсингу LangGraph
3. get_prompt_text() — завантажує system prompt з Langfuse Prompt Management

Аналогія Java: це як static singleton для DB connection pool —
ініціалізується один раз при import, використовується скрізь.

CallbackHandler читає LANGFUSE_* змінні з os.environ автоматично.
"""
from langfuse import get_client
from langfuse.langchain import CallbackHandler

# ==============================
# Singleton клієнт і handler
# ==============================

# get_client() читає LANGFUSE_PUBLIC_KEY / SECRET_KEY / BASE_URL з os.environ
langfuse_client = get_client()

# CallbackHandler передається у callbacks=[...] при invoke/stream LangGraph
# Автоматично трейсить: LLM calls, tool calls, chain steps
langfuse_handler = CallbackHandler()


# ==============================
# Prompt Management
# ==============================

def get_prompt_text(prompt_name: str, label: str = "production", **variables) -> str | None:
    """
    Завантажує system prompt з Langfuse Prompt Management.

    Замість захардкодженого тексту в коді — динамічне завантаження з Langfuse UI.
    Це дозволяє змінювати промпти без редеплою коду.

    Аналогія Java: ResourceBundle або @Value("${prompt.name}") з Spring —
    конфігурація зовні від коду, версіонована і відкатувана.

    Args:
        prompt_name: назва промпту у Langfuse (наприклад "supervisor_system")
        label: версія промпту (production / staging / development)
        **variables: template variables для compile() (наприклад today="2026-04-20")

    Returns:
        Скомпільований текст промпту або None якщо Langfuse недоступний.
        Caller відповідає за fallback на локальний промпт.
    """
    try:
        prompt = langfuse_client.get_prompt(prompt_name, label=label)
        if variables:
            # compile() підставляє {{variable}} у тексті промпту
            return prompt.compile(**variables)
        return prompt.compile()
    except Exception as exc:
        print(f"  ⚠️  Langfuse prompt '{prompt_name}' not found: {exc}")
        return None


def flush() -> None:
    """Примусово надсилає всі буферизовані події в Langfuse."""
    langfuse_client.flush()
