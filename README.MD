# Research Agent

Навчальний проєкт на **Python + OpenAI API** — мультиагентна дослідницька система з Supervisor, спеціалізованими sub-агентами і HITL (Human-in-the-Loop).

Проєкт написаний у навчальному стилі: у коді є додаткові коментарі, щоб було простіше розібратись у Python, якщо у вас бекграунд переважно з Java.

---

## Архітектура (lesson-13: Web UI + Docker + Postgres)

```
Browser
  │  EventSource /stream?query=...  (SSE)
  │  POST /approve | /reject        (HITL)
  ▼
FastAPI (app/api.py)  ──► asyncpg ──► Postgres (research_sessions)
  │
  ▼ asyncio.to_thread()
supervisor_local.py (sync)
  │  InMemorySaver (HITL стан)
  ├── plan()      → agents/planner.py
  ├── research()  → agents/research.py
  ├── critique()  → agents/critic.py
  └── save_report() → output/*.md
```

UI — 3 колонки: **History sidebar** | **Chat/Log** (SSE стрімінг) | **Report Preview** (marked.js)

---

## Архітектура (lesson-9: MCP + ACP)

```
User (REPL)
  │
  ▼
Supervisor Agent (локальний, create_agent + HITL)
  │
  ├── plan(request)      ──► ACP (8903) ──► Planner Agent  ──► MCP (8901) ──► web_search
  │                                                                             knowledge_search
  │
  ├── research(plan)     ──► ACP (8903) ──► Research Agent ──► MCP (8901) ──► web_search
  │                                                                             read_url
  │                                                                             knowledge_search
  │
  ├── critique(findings) ──► ACP (8903) ──► Critic Agent   ──► MCP (8901) ──► web_search
  │       │
  │       ├── verdict: APPROVE → save_report
  │       └── verdict: REVISE  → back to research
  │
  └── save_report(...)   ──► MCP (8902) ──► ReportMCP ──► output/
                             ⏸️ HITL: approve / edit / reject
```

Патерн: **Subagents-as-Tools over ACP** — Supervisor викликає sub-агентів через ACP протокол, sub-агенти отримують tools через MCP протокол.

---

## Структура проєкту

```text
PythonProject/
├── app/                     # Web UI (hw13)
│   ├── api.py               # FastAPI: SSE /stream, /approve, /reject, /sessions
│   ├── session_store.py     # asyncpg + Postgres таблиця research_sessions
│   ├── checkpoint.py        # AsyncPostgresSaver (підготовлено, не активовано)
│   └── static/              # index.html + style.css + app.js
├── docker-compose.yml       # postgres + app сервіси (hw13)
├── Dockerfile               # python:3.11-slim + uvicorn (hw13)
├── main.py                  # REPL (hw9: Supervisor + HITL через MCP+ACP)
├── main_supervisor.py       # REPL (hw8: backup, без MCP/ACP)
├── supervisor.py            # Supervisor Agent + ACP delegation tools
├── acp_server.py            # ACP сервер (порт 8903): planner, researcher, critic
├── mcp_servers/
│   ├── search_mcp.py        # SearchMCP (порт 8901): web_search, read_url, knowledge_search
│   └── report_mcp.py        # ReportMCP (порт 8902): save_report
├── mcp_utils.py             # mcp_tools_to_langchain() — bridge MCP → LangChain
├── agents/
│   ├── planner.py           # Planner: parse_research_plan() + тест напряму
│   ├── research.py          # Researcher: тест напряму
│   └── critic.py            # Critic: parse_critique_result() + тест напряму
├── schemas.py               # Pydantic: ResearchPlan, CritiqueResult
├── tools.py                 # Бізнес-логіка: web_search, read_url, knowledge_search, write_report
├── config.py                # Settings + system prompts + порти MCP/ACP
├── retriever.py             # Hybrid RAG: BM25 + FAISS + CrossEncoder Reranking
├── ingest.py                # PDF → chunks → embeddings → FAISS
├── langfuse_utils.py        # Langfuse client singleton, CallbackHandler, get_prompt_text() (hw12)
├── supervisor_local.py      # Supervisor без ACP/MCP — hw8 архітектура, використовується в hw12
├── agent.py                 # Власний ReAct loop (hw5, legacy)
├── requirements.txt
├── data/                    # PDF-документи для RAG (не в git)
├── faiss_index/             # FAISS-індекс (генерується через ingest.py, не в git)
└── output/                  # Збережені Markdown-звіти
```

---

## Технології

- **Python 3.13**
- **OpenAI API** — офіційний `openai` SDK
- **Tavily API** — пошук у вебі і читання сторінок (оптимізовано для LLM-агентів)
- **LangChain / LangGraph** — `create_agent`, `HumanInTheLoopMiddleware`, `InMemorySaver`
- **FastMCP** — MCP сервери і клієнти (`fastmcp==3.2.0`)
- **acp-sdk** — ACP сервер і клієнт (`acp-sdk==1.0.3`)
- **faiss-cpu** — векторний індекс для semantic search
- **rank_bm25** — лексичний пошук за ключовими словами
- **sentence-transformers** — CrossEncoder reranker (`BAAI/bge-reranker-base`)
- **pypdf** — парсинг PDF
- **pydantic-settings** — конфігурація через `.env`
- **langfuse** — observability: tracing, Prompt Management, LLM-as-a-Judge (hw12)
- **deepeval** — LLM-as-a-Judge тести у стилі pytest (hw10)
- **ragas** — оцінка RAG-систем (встановлено, не використовується активно)

---

## Запуск (hw13 — Web UI)

```bash
# Docker — рекомендований спосіб (Postgres + FastAPI в одній команді)
docker compose up --build
# → http://localhost:8000
```

Або локально без Docker (history sidebar не працює — немає Postgres):
```bash
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

---

## Встановлення (CLI / тести)

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Налаштування `.env`

```dotenv
OPENAI_API_KEY=<YOUR_OPENAI_API_KEY>
TAVILY_API_KEY=<YOUR_TAVILY_API_KEY>   # формат: tvly-dev-...
OPENAI_MODEL=gpt-4o-mini
TEMPERATURE=0.2
SEARCH_RESULTS_LIMIT=5
SEARCH_SNIPPET_MAX_CHARS=500
PAGE_TEXT_MAX_CHARS=8000
OUTPUT_DIR=output
DEFAULT_REPORT_FILENAME=report.md
MAX_ITERATIONS=12
REQUEST_TIMEOUT_SECONDS=20
```

> **Увага:** не дублюй `TAVILY_API_KEY` у `.env` — pydantic-settings бере останній, але перший може бути актуальним.

**НІКОЛИ не комітьте `.env` у git.**

---

## Запуск

### Крок 1 — Побудова локальної бази знань (один раз)

```bash
# Додай PDF-файли в директорію data/
.venv/bin/python3 ingest.py
```

### Крок 2 — Запуск усіх серверів (4 термінали)

```bash
# Термінал 1 — SearchMCP: web_search, read_url, knowledge_search
.venv/bin/python3 mcp_servers/search_mcp.py
# → Starting SearchMCP server on port 8901...

# Термінал 2 — ReportMCP: save_report
.venv/bin/python3 mcp_servers/report_mcp.py
# → Starting ReportMCP server on port 8902...

# Термінал 3 — ACP Server: planner, researcher, critic
.venv/bin/python3 acp_server.py
# → Starting ACP server on port 8903...

# Термінал 4 — REPL
.venv/bin/python3 main.py
```

### Крок 3 — Введи запит

```
You: Compare RAG approaches: naive, sentence-window, and parent-child
```

**Очікуваний flow:**

```
[Supervisor → ACP → Planner]
  🔧 web_search via SearchMCP
  → ResearchPlan received

[Supervisor → ACP → Researcher]  (round 1)
  🔧 knowledge_search via SearchMCP
  🔧 web_search via SearchMCP
  → Findings received

[Supervisor → ACP → Critic]
  🔧 web_search via SearchMCP
  → verdict=REVISE (або APPROVE)

[Supervisor → ACP → Researcher]  (round 2, якщо REVISE)
  → Updated findings

[Supervisor → ACP → Critic]
  → verdict=APPROVE

⏸️  ACTION REQUIRES APPROVAL
  Tool:  save_report
  File:  rag_comparison.md
  --- Preview ---
  # Comparison of RAG Approaches...
  ---
👉 approve / edit / reject: approve
✅ Report saved to output/rag_comparison.md
```

---

## Тестування по рівнях

### Рівень 1 — окремі агенти (без серверів)

```bash
.venv/bin/python3 agents/planner.py "What is RAG?"
.venv/bin/python3 agents/research.py "What is RAG and how does it work?"
.venv/bin/python3 agents/critic.py   # без аргументів — вбудований приклад
```

### Рівень 2 — MCP сервери окремо

Запусти `mcp_servers/search_mcp.py`, потім:

```bash
.venv/bin/python3 -c "
import asyncio
from fastmcp import Client

async def test():
    async with Client('http://127.0.0.1:8901/mcp') as c:
        tools = await c.list_tools()
        print('Tools:', [t.name for t in tools])
        result = await c.call_tool('web_search', {'query': 'Python language'})
        print('web_search OK:', str(result)[:100])

asyncio.run(test())
"
```

### Рівень 3 — ACP агент окремо

Запусти SearchMCP + ACP Server, потім:

```bash
.venv/bin/python3 -c "
import asyncio, os
from config import settings
os.environ.setdefault('OPENAI_API_KEY', settings.openai_api_key)
from acp_sdk.client import Client
from acp_sdk.models import Message, MessagePart

async def test():
    async with Client(base_url='http://127.0.0.1:8903', headers={'Content-Type': 'application/json'}) as c:
        run = await c.run_sync(
            agent='planner',
            input=[Message(role='user', parts=[MessagePart(content='What is RAG?')])],
        )
        print(run.output[-1].parts[0].content)

asyncio.run(test())
"
```

### Рівень 4 — перевірка що сервери живі

```bash
# Чи слухають порти?
lsof -i :8901 -i :8902 -i :8903 | grep LISTEN

# ACP discovery
curl -s http://127.0.0.1:8903/agents | python3 -m json.tool | grep name
```

---

## HITL (Human-in-the-Loop)

Коли Supervisor готовий зберегти звіт — система зупиняється і питає підтвердження:

```
⏸️  ACTION REQUIRES APPROVAL
  Tool:  save_report
  File:  rag_comparison.md

  --- Preview ---
  # Comparison of RAG Approaches...
  --- End Preview (3500 chars total) ---

👉 approve / edit / reject:
```

| Команда | Що відбувається |
|---|---|
| `approve` | Звіт зберігається у `output/` |
| `edit` | Вводиш feedback → Supervisor переробляє звіт → знову питає |
| `reject` | Збереження скасовується |

---

## Що може піти не так

| Симптом | Причина | Фікс |
|---|---|---|
| `Connection refused` на порту 890x | Сервер не запущений | Запусти відповідний сервер |
| `422 Unprocessable Content` від ACP | Відсутній `Content-Type` header | Вже виправлено в коді (`headers={'Content-Type': 'application/json'}`) |
| `InvalidAPIKeyError` у Tavily | Невалідний ключ або дублікат у `.env` | Має бути один `TAVILY_API_KEY=tvly-dev-...` |
| Supervisor зависає | SearchMCP або ACP не відповідає | Перевір логи серверів (`/tmp/*.log`) |
| CrossEncoder завантажується довго | Перший запуск моделі (~30 сек) | Зачекати, далі буде швидше |

---

## RAG pipeline

```
Offline (один раз):
  PDF files → PyPDFLoader → RecursiveCharacterTextSplitter (chunk=500, overlap=100)
  → OpenAI text-embedding-3-small → FAISS index (збережено на диск)

Online (при кожному knowledge_search):
  query → BM25 search  ↘
                         EnsembleRetriever (BM25 40% + FAISS 60%) → top-10
  query → FAISS search ↗
                         → CrossEncoder Reranker (BAAI/bge-reranker-base) → top-3
```

---

## Тестування (hw10 — DeepEval)

```bash
.venv/bin/deepeval test run tests/test_planner.py -v
.venv/bin/deepeval test run tests/test_researcher.py -v
.venv/bin/deepeval test run tests/test_critic.py -v
.venv/bin/deepeval test run tests/test_tools.py -v
.venv/bin/deepeval test run tests/test_e2e.py -v
.venv/bin/deepeval test run tests/ -v   # всі тести, ~15 хв
```

## Observability (hw12 — Langfuse)

Трейсинг, Prompt Management і LLM-as-a-Judge через Langfuse.

- System prompts агентів завантажуються з Langfuse Prompt Management з fallback на локальні (`config.py`)
- Кожен запит трейситься: session_id + user_id, кроки агентів, tool calls
- LLM-as-a-Judge evaluators: `research_relevance` (numeric), `response_completeness` (boolean)

Потрібні додаткові змінні в `.env`:
```dotenv
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com
```

## Обмеження

Це навчальний проєкт:
- логування через `print()` (Langfuse трейсинг додано в hw12)
- немає кешування результатів пошуку між запитами
- CrossEncoder модель завантажується при першому виклику (~30 сек)
- LangGraph стан (`InMemorySaver`) губиться при перезапуску контейнера — `langgraph-checkpoint-postgres` несумісний з `langgraph==1.0.2`; metadata сесій (запит, час, звіт) зберігається у Postgres
- кожен ACP агент відкриває новий MCP client на кожен запит (немає connection pooling)
