"""
SearchMCP — MCP сервер для search tools (порт 8901).

Виставляє через FastMCP три інструменти:
  - web_search(query)       → пошук в інтернеті через Tavily
  - read_url(url)           → читання вмісту сторінки через Tavily
  - knowledge_search(query) → гібридний пошук по локальній базі знань (FAISS + BM25)

Resources:
  - resource://knowledge-base-stats → кількість документів і дата оновлення

SearchMCP використовується ТРЬОМА агентами (planner, researcher, critic) одночасно.
Кожен підключається до одного й того ж HTTP endpoint незалежно.

FastMCP — Python фреймворк для побудови MCP серверів.
Аналогія з Java: Spring Boot REST controller, де @RestController = FastMCP,
а @GetMapping/@PostMapping = @mcp_server.tool / @mcp_server.resource.

Запуск:
    .venv/bin/python3 mcp_servers/search_mcp.py   # порт 8901
"""
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# sys.path fix — щоб знаходити config, tools, retriever при запуску напряму
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastmcp import FastMCP

# Встановлюємо API ключі в os.environ до імпорту інших модулів
# (pydantic-settings не встановлює os.environ автоматично)
from config import settings, MCP_SEARCH_PORT
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key)

# Імпортуємо бізнес-логіку з hw5/hw8 (перевикористання)
from tools import web_search as _web_search, read_url as _read_url, knowledge_search as _knowledge_search

# FastMCP("SearchMCP") — створює MCP сервер з назвою "SearchMCP"
# Аналогія Java: @SpringBootApplication + ApplicationContext
mcp_server = FastMCP(name="SearchMCP")


# ==============================
# MCP Tools — дії з побічними ефектами (IO: мережа, диск)
# ==============================
# @mcp_server.tool — декоратор, що реєструє функцію як MCP tool
# Аналогія Java: @PostMapping — метод стає HTTP endpoint

@mcp_server.tool
def web_search(query: str) -> str:
    """
    Search the web for current information using Tavily API.

    Args:
        query: Search query in natural language
    """
    # Делегуємо до бізнес-логіки з tools.py
    # _web_search повертає list[dict] — конвертуємо у str для MCP протоколу
    results = _web_search(query)
    # "\n".join(...) — об'єднуємо результати через newline
    # f-string form: "- Title: snippet\n  URL: url"
    return "\n".join(
        f"- {r['title']}: {r['snippet']}\n  URL: {r['url']}"
        for r in results
    )


@mcp_server.tool
def read_url(url: str) -> str:
    """
    Download and extract readable text from a web page using Tavily Extract.

    Args:
        url: Full page URL starting with http:// or https://
    """
    # Пряме делегування — _read_url вже повертає str
    return _read_url(url)


@mcp_server.tool
def knowledge_search(query: str) -> str:
    """
    Search the local knowledge base of ingested PDF documents.
    Use for questions about RAG, LangChain, LLMs, retrieval, embeddings.

    Args:
        query: Search query in natural language or as keywords
    """
    # Пряме делегування — _knowledge_search вже повертає str
    return _knowledge_search(query)


# ==============================
# MCP Resources — read-only дані (метадані системи)
# ==============================
# @mcp_server.resource("uri") — реєструє read-only ресурс
# Аналогія Java: @GetMapping — отримання даних без побічних ефектів

@mcp_server.resource("resource://knowledge-base-stats")
def get_knowledge_base_stats() -> str:
    """
    Statistics about the local knowledge base: document count and last update time.

    Returns JSON with:
        - document_count: кількість проіндексованих документів
        - last_updated: дата останнього оновлення індексу
        - faiss_index_exists: чи є FAISS індекс на диску
    """
    faiss_dir = Path(_project_root) / "faiss_index"
    ingested_file = faiss_dir / "ingested_files.json"

    # Рахуємо кількість проіндексованих файлів
    # Файл ingested_files.json зберігає список файлів що були проіндексовані
    doc_count = 0
    last_updated = None

    if ingested_file.exists():
        try:
            ingested = json.loads(ingested_file.read_text(encoding="utf-8"))
            # ingested може бути list або dict — перевіряємо обидва варіанти
            if isinstance(ingested, list):
                doc_count = len(ingested)
            elif isinstance(ingested, dict):
                doc_count = len(ingested)
            # Беремо час модифікації файлу як дату оновлення
            mtime = ingested_file.stat().st_mtime
            last_updated = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    # json.dumps — серіалізуємо dict у JSON рядок (як ObjectMapper.writeValueAsString() у Java)
    return json.dumps({
        "document_count": doc_count,
        "last_updated": last_updated or "unknown",
        "faiss_index_exists": (faiss_dir / "index.faiss").exists(),
    })


# ==============================
# Точка входу
# ==============================

if __name__ == "__main__":
    print(f"Starting SearchMCP server on port {MCP_SEARCH_PORT}...")
    print(f"  Tools:     web_search, read_url, knowledge_search")
    print(f"  Resources: resource://knowledge-base-stats")
    print(f"  URL:       http://127.0.0.1:{MCP_SEARCH_PORT}/mcp")
    # transport="streamable-http" — HTTP транспорт (стандарт для зовнішніх MCP серверів)
    # Альтернатива: transport="stdio" — для локального виклику через stdin/stdout
    mcp_server.run(transport="streamable-http", port=MCP_SEARCH_PORT)
