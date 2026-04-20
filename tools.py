from pathlib import Path
from typing import Any
from collections.abc import Callable

from tavily import TavilyClient

from config import BASE_DIR, settings
from retriever import hybrid_search


# ==============================
# Tavily клієнт (lazy singleton)
# ==============================
# TavilyClient — офіційний Python SDK для Tavily Search API.
# Tavily спеціально оптимізований для LLM-агентів:
#   - повертає чистий текст без HTML-сміття
#   - може повертати повний контент сторінки (include_raw_content=True)
#   - стабільніший за DuckDuckGo (немає rate limits і CAPTCHA)
# Аналогія з Java: це як singleton Spring @Bean для HTTP-клієнта.
_tavily_client: TavilyClient | None = None


def _get_tavily() -> TavilyClient:
    """Повертає TavilyClient, створює при першому виклику."""
    global _tavily_client
    if _tavily_client is None:
        # api_key береться з settings (pydantic-settings читає з .env)
        _tavily_client = TavilyClient(api_key=settings.tavily_api_key)
    return _tavily_client


# ==============================
# Допоміжні функції (private)
# ==============================

def _sanitize(text: str) -> str:
    """
    Прибирає surrogate символи та інші некоректні Unicode-послідовності.

    Surrogate символи (\\udcXX) можуть прийти з веб-сторінок через Tavily.
    Якщо вони потраплять у messages → OpenAI API падає з UnicodeEncodeError.
    encode("utf-8", errors="ignore") — тихо видаляє некоректні байти.
    У Java — аналог: CharsetEncoder з CodingErrorAction.IGNORE.
    """
    # re.sub видаляє surrogate символи (U+D800–U+DFFF) напряму з рядка.
    # Це надійніше ніж encode/decode бо ловить всі surrogate незалежно від codec.
    import re
    return re.sub(r"[\ud800-\udfff]", "", text)


def _trim_text(text: str, max_chars: int) -> str:
    """
    Очищає і обрізає текст до max_chars символів.

    Результати tools потрапляють у messages → LLM.
    Занадто довгий або некоректний текст — повільніше і дорожче.
    У Java — аналог: StringUtils.abbreviate(text, maxWidth).
    """
    cleaned = _sanitize(text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "\n\n[truncated]"


# ==============================
# Реалізація tools (бізнес-логіка)
# ==============================

def web_search(query: str) -> list[dict[str, str]]:
    """
    Шукає у вебі через Tavily і повертає список результатів.

    Tavily — пошукове API оптимізоване для LLM-агентів:
    повертає чистий текст, стабільний, без CAPTCHA.

    Повертає list[dict] — кожен елемент має ключі: title, url, snippet.
    У Java — як List<SearchResult> де SearchResult — POJO з трьома полями.
    """
    print(f"\n🔧 Tool call: web_search(query={query!r})")

    try:
        # search() — основний метод Tavily API
        # max_results — скільки результатів повернути
        response = _get_tavily().search(
            query=query,
            max_results=settings.search_results_limit,
        )

        # response["results"] — list[dict] з ключами: title, url, content, score
        # list comprehension — стислий спосіб побудувати список з перетворенням
        # у Java: results.stream().map(...).collect(Collectors.toList())
        formatted_results: list[dict[str, str]] = [
            {
                "title": _sanitize(item.get("title", "Untitled result")),
                "url": _sanitize(item.get("url", "")),
                "snippet": _trim_text(item.get("content", ""), settings.search_snippet_max_chars),
            }
            for item in response.get("results", [])
        ]

        print(f"📎 Result: Found {len(formatted_results)} results")

        if not formatted_results:
            return [{"title": "No results", "url": "", "snippet": "Search returned no results."}]

        return formatted_results

    except Exception as exc:
        print(f"📎 Result: web_search error: {type(exc).__name__}: {exc}")
        return [
            {
                "title": "Search error",
                "url": "",
                "snippet": f"web_search failed: {type(exc).__name__}: {exc}",
            }
        ]


def read_url(url: str) -> str:
    """
    Завантажує сторінку за URL через Tavily Extract і повертає її текст.

    Tavily Extract — більш надійний ніж trafilatura:
    обробляє JS-сайти, повертає структурований контент.
    """
    print(f"\n🔧 Tool call: read_url(url={url!r})")

    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    try:
        # extract() — Tavily API для витягування контенту з конкретної сторінки
        response = _get_tavily().extract(urls=[url])

        # response["results"] — list результатів, перший містить raw_content
        results = response.get("results", [])
        if not results:
            return f"Error: could not extract content from {url}"

        raw_content = results[0].get("raw_content", "") or results[0].get("content", "")
        if not raw_content:
            return f"Error: page was empty or unreadable: {url}"

        trimmed = _trim_text(raw_content, settings.page_text_max_chars)
        print(f"📎 Result: [{len(trimmed)} chars] extracted from page")
        return trimmed

    except Exception as exc:
        print(f"📎 Result: read_url error: {type(exc).__name__}: {exc}")
        return f"Error: read_url failed for {url}: {type(exc).__name__}: {exc}"


def knowledge_search(query: str) -> str:
    """
    Шукає у локальній базі знань (проіндексовані PDF документи).

    Використовує гібридний пошук: Semantic Search + BM25 + CrossEncoder Reranking.
    Агент викликає цей tool коли запитання стосується локальних документів,
    а не актуальних подій в інтернеті.

    Повертає str — відформатований список знайдених фрагментів з джерелами.
    """
    print(f"\n🔧 Tool call: knowledge_search(query={query!r})")

    try:
        result = hybrid_search(query)
        # _trim_text включає _sanitize — прибирає surrogates і обрізає довгий текст
        trimmed = _trim_text(result, settings.page_text_max_chars)
        # Рахуємо кількість знайдених фрагментів (розділені "---")
        count = trimmed.count("[Source ")
        print(f"📎 Result: [{count} document(s) found]")
        return trimmed
    except FileNotFoundError as exc:
        msg = str(exc)
        print(f"📎 Result: knowledge_search error — {msg}")
        return f"Error: {msg}"
    except Exception as exc:
        print(f"📎 Result: knowledge_search error: {type(exc).__name__}: {exc}")
        return f"Error: knowledge_search failed: {type(exc).__name__}: {exc}"


def write_report(filename: str, content: str) -> str:
    """
    Зберігає Markdown-звіт у файл.
    """
    print(f"\n🔧 Tool call: write_report(filename={filename!r}, content_len={len(content)})")

    try:
        output_dir = BASE_DIR / settings.output_dir
        # mkdir(parents=True, exist_ok=True) — як Files.createDirectories() у Java
        output_dir.mkdir(parents=True, exist_ok=True)

        # Path(filename).name — відрізає будь-який шлях і залишає лише ім'я файлу.
        # Захист від path traversal атаки: якщо LLM передасть "../../../etc/passwd"
        # — Path(...).name поверне просто "passwd", і файл збережеться в output_dir.
        # У Java аналог: Paths.get(filename).getFileName().toString()
        safe_name = Path(filename.strip()).name or "report.md"
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        target_path = output_dir / safe_name
        # write_text — записує рядок у файл, аналог Files.writeString() у Java
        target_path.write_text(content, encoding="utf-8")

        print(f"📎 Result: Report saved to {target_path}")
        return f"Report saved to: {target_path}"

    except Exception as exc:
        print(f"📎 Result: write_report error: {type(exc).__name__}: {exc}")
        return f"Error: could not save report: {type(exc).__name__}: {exc}"


# ==============================
# JSON Schema визначення tools для OpenAI API
# ==============================

# TOOLS_SCHEMA — це список описів інструментів у форматі, який розуміє OpenAI API.
# У LangChain це робив @tool декоратор автоматично.
# Тепер ми описуємо це вручну — так LLM знає, які tools є і як їх викликати.
#
# Структура кожного елемента:
# {
#   "type": "function",         — завжди "function" для tool calling
#   "function": {
#     "name": "...",            — назва функції (має збігатись із реальною функцією)
#     "description": "...",     — що робить tool (LLM читає це щоб вирішити коли викликати)
#     "parameters": {           — JSON Schema опис параметрів (як @RequestBody у Spring)
#       "type": "object",
#       "properties": { ... },
#       "required": [ ... ]
#     }
#   }
# }
TOOLS_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for relevant pages. "
                "Use this when you need current information or need to research a topic. "
                "Returns a list of results with title, url, and snippet."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query in natural language.",
                    }
                },
                # required — список обов'язкових параметрів (як @NotNull у Java)
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_url",
            "description": (
                "Download a web page and extract its main readable text. "
                "Use this to read the full content of a specific page found via web_search."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full page URL starting with http:// or https://",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": (
                "Search the local knowledge base of ingested PDF documents. "
                "Use this for questions about topics covered in the local documents "
                "(RAG, LangChain, Large Language Models). "
                "Prefer this over web_search when the question is about a concept "
                "that is likely covered in the knowledge base. "
                "Returns relevant text excerpts with source references."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query in natural language or as keywords.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_report",
            "description": (
                "Save a Markdown report to disk. "
                "Use this when you have gathered enough information and are ready to produce the final report."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filename": {
                        "type": "string",
                        "description": "Target file name, for example 'report.md'",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full Markdown content to save.",
                    },
                },
                "required": ["filename", "content"],
            },
        },
    },
]

# TOOLS_MAP — словник для швидкого пошуку функції за її назвою.
# dict — це як HashMap<String, Function> у Java.
# Коли LLM повертає tool_call з name="web_search",
# ми робимо TOOLS_MAP["web_search"] і отримуємо функцію для виклику.
TOOLS_MAP: dict[str, Callable[..., Any]] = {
    "web_search": web_search,
    "read_url": read_url,
    "write_report": write_report,
    "knowledge_search": knowledge_search,
}
