from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

from ddgs import DDGS
from langchain_core.tools import tool
import trafilatura

from config import BASE_DIR, settings


def _trim_text(text: str, max_chars: int) -> str:
    """
    Допоміжна функція для обрізання довгого тексту.

    Навіщо?
    Бо результати tools потрапляють назад у LLM-контекст.
    Якщо передавати занадто багато тексту, модель:
    - працює повільніше,
    - дорожче коштує,
    - може втратити фокус.

    Це класичний приклад context engineering.
    """
    cleaned = text.strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars].rstrip() + "\n\n[truncated]"


def _run_with_timeout(func, *args, timeout_seconds: int):
    """
    Запускає функцію в окремому потоці і чекає не довше за timeout_seconds.

    Чому так?
    Деякі бібліотеки для мережі не завжди поводяться передбачувано:
    можуть довго чекати, редіректити, ретраїти, або підвисати.
    Нам краще повернути контрольовану помилку, ніж зависнути всім REPL.
    """
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, *args)
        return future.result(timeout=timeout_seconds)


def _search_web(query: str) -> list[dict[str, Any]]:
    """
    Окрема "сира" функція для пошуку без декоратора @tool.

    Це зручно, бо її легше обгорнути timeout-логікою.
    """
    return list(DDGS().text(query, max_results=settings.search_results_limit))


def _download_and_extract(url: str) -> str | None:
    """
    Окрема функція для завантаження та витягування тексту зі сторінки.
    """
    downloaded = trafilatura.fetch_url(url)

    if not downloaded:
        return None

    return trafilatura.extract(
        downloaded,
        include_comments=False,
        include_tables=True,
    )


@tool
def web_search(query: str) -> list[dict[str, str]]:
    """
    Search the web for relevant pages.

    Args:
        query: Search query in natural language.

    Returns:
        A list of dictionaries with:
        - title: page title
        - url: page URL
        - snippet: short preview text
    """
    print(f"[tool] web_search(query={query!r})")

    try:
        raw_results = _run_with_timeout(
            _search_web,
            query,
            timeout_seconds=settings.request_timeout_seconds,
        )

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

        print(f"[tool] web_search -> {len(formatted_results)} results")

        if not formatted_results:
            return [{"title": "No results", "url": "", "snippet": "Search returned no results."}]

        return formatted_results

    except FutureTimeoutError:
        print("[tool] web_search timeout")
        return [
            {
                "title": "Search timeout",
                "url": "",
                "snippet": f"web_search timed out after {settings.request_timeout_seconds} seconds",
            }
        ]
    except Exception as exc:
        print(f"[tool] web_search error: {type(exc).__name__}: {exc}")
        return [
            {
                "title": "Search error",
                "url": "",
                "snippet": f"web_search failed: {type(exc).__name__}: {exc}",
            }
        ]


@tool
def read_url(url: str) -> str:
    """
    Download a web page and extract its main readable text.

    Args:
        url: Full page URL.

    Returns:
        Extracted page text, trimmed to a safe size for the model.
    """
    print(f"[tool] read_url(url={url!r})")

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
        print(f"[tool] read_url -> {len(trimmed)} chars")
        return trimmed

    except FutureTimeoutError:
        print("[tool] read_url timeout")
        return f"Error: read_url timed out after {settings.request_timeout_seconds} seconds for {url}"
    except Exception as exc:
        print(f"[tool] read_url error: {type(exc).__name__}: {exc}")
        return f"Error: read_url failed for {url}: {type(exc).__name__}: {exc}"


@tool
def write_report(filename: str, content: str) -> str:
    """
    Save a Markdown report to disk.

    Args:
        filename: Target file name, for example 'report.md'
        content: Markdown content to save

    Returns:
        Confirmation message with the saved path.
    """
    print(f"[tool] write_report(filename={filename!r}, content_len={len(content)})")

    try:
        output_dir = BASE_DIR / settings.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        safe_name = filename.strip() or "report.md"
        if not safe_name.endswith(".md"):
            safe_name += ".md"

        target_path = output_dir / safe_name
        target_path.write_text(content, encoding="utf-8")

        print(f"[tool] write_report -> saved to {target_path}")
        return f"Report saved to: {target_path}"

    except Exception as exc:
        print(f"[tool] write_report error: {type(exc).__name__}: {exc}")
        return f"Error: could not save report: {type(exc).__name__}: {exc}"


TOOLS = [web_search, read_url, write_report]