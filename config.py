from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


# BASE_DIR — це "корінь" нашого проєкту.
# У Java ти часто мислиш через resources / project root.
# У Python Pathlib — дуже зручний і читабельний спосіб працювати з шляхами.
BASE_DIR = Path(__file__).resolve().parent


class Settings(BaseSettings):
    """
    Клас для всіх налаштувань застосунку.

    Чому так?
    - Ми НЕ хардкодимо ключі та змінні в коді.
    - Налаштування читаються з .env файлу.
    - Це безпечніше і зручніше для різних середовищ (dev / prod).

    Аналогія з Java:
    це щось на кшталт strongly-typed application.properties / config object.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openai_api_key: str = Field(..., alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")
    temperature: float = Field(default=0.2, alias="TEMPERATURE")
    search_results_limit: int = Field(default=5, alias="SEARCH_RESULTS_LIMIT")
    search_snippet_max_chars: int = Field(default=500, alias="SEARCH_SNIPPET_MAX_CHARS")
    page_text_max_chars: int = Field(default=8000, alias="PAGE_TEXT_MAX_CHARS")
    output_dir: str = Field(default="example_output", alias="OUTPUT_DIR")
    default_report_filename: str = Field(default="report.md", alias="DEFAULT_REPORT_FILENAME")
    max_iterations: int = Field(default=12, alias="MAX_ITERATIONS")
    request_timeout_seconds: int = Field(default=20, alias="REQUEST_TIMEOUT_SECONDS")


settings = Settings()


SYSTEM_PROMPT = """
You are a research agent that answers in Markdown.

Decision policy:
1. If the user asks a simple conversational or general knowledge question, you may answer directly without tools.
2. If the user asks for comparison, research, trade-offs, recent information, or asks about multiple technical approaches, you MUST use tools before answering.
3. For research-style questions, do not answer only from prior knowledge.

Required research behavior for comparison questions:
- Run multiple web_search calls for the main compared items.
- Read 1-2 relevant URLs with read_url before writing the final answer.
- Synthesize findings into a structured Markdown report.
- If enough information is collected, stop and conclude.

Tool strategy:
- Start with web_search.
- Prefer 3 or more targeted searches for comparison tasks.
- Use read_url on the most relevant result pages.
- Avoid repetitive looping on the same query.
- If a tool fails, continue with the remaining evidence.

Output style:
- Always produce Markdown.
- For comparisons, use headings and preferably a comparison table.
- Be concrete about strengths, weaknesses, and trade-offs.
""".strip()