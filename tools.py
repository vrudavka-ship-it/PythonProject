from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any
from collections.abc import Callable

from ddgs import DDGS
import trafilatura

from config import BASE_DIR, settings
from retriever import hybrid_search


# ==============================
# Допоміжні функції (private)
# ==============================

def _trim_text(text: str, max_chars: int) -> str:
    """
    Обрізає текст до max_chars символів.

    Навіщо?
    Результати tools потрапляють у список messages, який іде в LLM.
    Якщо передавати занадто багато тексту — модель повільніша і дорожча.
    Це context engineering.

    У Java — аналог: StringUtils.abbreviate(text, maxWidth)
    """
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "\n\n[truncated]"


def _run_with_timeout(func, *args, timeout_seconds: int):
    """
    Запускає функцію в окремому потоці з обмеженням часу виконання.

    У Java — аналог: Future.get(timeout, TimeUnit.SECONDS)
    Тут використовується ThreadPoolExecutor — пул потоків.

    *args — це varargs, як у Java: void method(Object... args)
    """
    # ThreadPoolExecutor — менеджер пула потоків
    # max_workers=1 — нам потрібен лише один потік для однієї задачі
    with ThreadPoolExecutor(max_workers=1) as executor:
        # submit — відправляємо задачу у потік, отримуємо Future-об'єкт
        future = executor.submit(func, *args)
        # result(timeout=...) — чекаємо результату не довше ніж timeout_seconds
        return future.result(timeout=timeout_seconds)


def _search_web(query: str) -> list[dict[str, Any]]:
    """
    Виконує пошук у DuckDuckGo і повертає список результатів.

    list[dict[str, Any]] — це як List<Map<String, Object>> у Java.
    """
    return list(DDGS().text(query, max_results=settings.search_results_limit))


def _download_and_extract(url: str) -> str | None:
    """
    Завантажує сторінку і витягує з неї основний текст.

    str | None — Union type, як Optional<String> у Java.
    Повертає текст або None, якщо не вдалося завантажити.
    """
    downloaded = trafilatura.fetch_url(url)

    if not downloaded:
        return None

    return trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
    )


# ==============================
# Реалізація tools (бізнес-логіка)
# ==============================

def web_search(query: str) -> list[dict[str, str]]:
    """
    Шукає у вебі та повертає список результатів.

    Повертає list[dict] — кожен елемент має ключі: title, url, snippet.
    У Java — як List<SearchResult> де SearchResult — POJO з трьома полями.
    """
    print(f"\n🔧 Tool call: web_search(query={query!r})")

    try:
        raw_results = _run_with_timeout(
            _search_web,
            query,
            timeout_seconds=settings.request_timeout_seconds,
        )

        # list comprehension — стислий спосіб побудувати список з перетворенням
        # у Java: results.stream().map(...).collect(Collectors.toList())
        formatted_results: list[dict[str, str]] = []
        for item in raw_results:
            title = str(item.get("title", "")).strip()
            url = str(item.get("href", "")).strip()
            snippet = str(item.get("body", "")).strip()

            formatted_results.append(
                {
                    "title": title or "Untitled result",
                    "url": url,
                    "snippet": _trim_text(snippet, settings.search_snippet_max_chars),
                }
            )

        print(f"📎 Result: Found {len(formatted_results)} results")

        if not formatted_results:
            return [{"title": "No results", "url": "", "snippet": "Search returned no results."}]

        return formatted_results

    except FutureTimeoutError:
        print("📎 Result: web_search timeout")
        return [
            {
                "title": "Search timeout",
                "url": "",
                "snippet": f"web_search timed out after {settings.request_timeout_seconds} seconds",
            }
        ]
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
    Завантажує сторінку за URL і повертає її текст.
    """
    print(f"\n🔧 Tool call: read_url(url={url!r})")

    if not url.startswith(("http://", "https://")):
        return "Error: URL must start with http:// or https://"

    try:
        extracted = _run_with_timeout(
            _download_and_extract,
            url,
            timeout_seconds=settings.request_timeout_seconds,
        )

        if not extracted:
            return f"Error: page was not downloaded or readable text could not be extracted from {url}"

        trimmed = _trim_text(extracted, settings.page_text_max_chars)
        print(f"📎 Result: [{len(trimmed)} chars] extracted from page")
        return trimmed

    except FutureTimeoutError:
        print("📎 Result: read_url timeout")
        return f"Error: read_url timed out after {settings.request_timeout_seconds} seconds for {url}"
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
        # Обрізаємо якщо результат дуже довгий — щоб не переповнити контекст LLM
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
