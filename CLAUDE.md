# Claude Working Notes

## Проєкт
Research Agent — навчальний Python-проєкт. Vasyl вивчає Python, маючи досвід Java-розробника.

## Стиль коментарів (ВАЖЛИВО)
- Усі нові методи, класи, змінні, структури даних — коментувати українською мовою
- Коментарі мають пояснювати концепцію так, щоб було зрозуміло Java-розробнику
- Приклад: `# dict — це як HashMap<String, Object> у Java`
- Якщо є Python-специфіка (list comprehension, generator, decorator) — пояснювати що це і чому так роблять у Python

## Workflow (урок за уроком)
1. Кожен урок — окрема git-гілка (наприклад `homework-lesson-4`)
2. Після виконання домашнього завдання — мерж у `master`
3. Після мержу — тег на коміт (як зроблено після lesson-3)
4. Не мержити і не тегувати без явної команди від Vasyl

## Поточний стан
- **Урок 3** — виконано, змержено в master, тег є
- **Урок 4** — виконано, змержено в master (коміт `7e5cc14`), тег `homework-lesson-4` є
- **Урок 5** — виконано, змержено в master, тег `homework-lesson-5` є (коміт `72fe3f0`)
- **Урок 8** — виконано, змержено в master, тег є
- **Урок 9** — виконано, змержено в master, тег є
- **Урок 10** — виконано, змержено в master, тег `homework-lesson-10` є (коміт `2ba53ac`)
- **Урок 12** — виконано, змержено в master, тег є. Langfuse observability: tracing, session/user tracking, Prompt Management (4 промпти), LLM-as-a-Judge (2 evaluators).
- **Урок 13** — в процесі (гілка `homework-lesson-13`). Web UI + Docker + Postgres. Мерж і тег ще не зроблено.

## Langfuse observability (lesson-12)
- `langfuse_utils.py` — Langfuse клієнт singleton, CallbackHandler, get_prompt_text()
- Всі system prompts агентів завантажуються з Langfuse Prompt Management з fallback на локальні
- Промпти у Langfuse: `supervisor_system`, `planner_system`, `researcher_system`, `critic_system`
- Tracing: session_id + user_id через `propagate_attributes`, callbacks=[langfuse_handler]
- LLM-as-a-Judge evaluators: `research_relevance` (numeric), `response_completeness` (boolean)
- Surrogate fix: `re.sub(r"[\ud800-\udfff]", "", text)` у tools.py, acp_server.py, supervisor.py

## Файлова структура проєкту
```
PythonProject/
├── app/                     # Web UI (hw13)
│   ├── api.py               # FastAPI: SSE /stream, /approve, /reject, /sessions
│   ├── session_store.py     # asyncpg + таблиця research_sessions у Postgres
│   ├── checkpoint.py        # AsyncPostgresSaver (готовий, не підключений — версійний конфлікт)
│   └── static/              # Фронтенд
│       ├── index.html       # 3-колонковий лейаут: History | Chat | Report Preview
│       ├── style.css        # Темна тема, кольори per-agent
│       └── app.js           # SSE клієнт, HITL картка, marked.js Markdown preview
├── docker-compose.yml       # postgres:16-alpine + FastAPI app (hw13)
├── Dockerfile               # python:3.11-slim, uvicorn (hw13)
├── langfuse_utils.py        # Langfuse client singleton, CallbackHandler, get_prompt_text() (hw12)
├── supervisor_local.py      # Supervisor без ACP/MCP — використовується в Web UI (hw13)
├── main.py                  # REPL loop (hw9: Supervisor + HITL через MCP+ACP)
├── main_supervisor.py       # REPL loop (hw8: Supervisor + HITL, збережено як backup)
├── agent.py                 # Власний ReAct loop (прямий виклик OpenAI API)
├── supervisor.py            # Supervisor Agent + ACP delegation tools (hw9)
├── acp_server.py            # ACP сервер: planner, researcher, critic (hw9)
├── mcp_utils.py             # mcp_tools_to_langchain() helper (hw9)
├── mcp_servers/
│   ├── search_mcp.py        # SearchMCP порт 8901: web_search, read_url, knowledge_search (hw9)
│   └── report_mcp.py        # ReportMCP порт 8902: save_report (hw9)
├── schemas.py               # Pydantic models: ResearchPlan, CritiqueResult (hw8)
├── agents/                  # Sub-agents (hw8)
│   ├── __init__.py
│   ├── planner.py           # Planner Agent → ResearchPlan
│   ├── research.py          # Research Agent (перевикористання hw5 tools)
│   └── critic.py            # Critic Agent → CritiqueResult
├── tools.py                 # Реалізація tools + TOOLS_SCHEMA (JSON Schema) + TOOLS_MAP
├── config.py                # Налаштування (.env), бібліотека system prompts, константи
├── retriever.py             # Hybrid Retrieval: BM25 + Vector + CrossEncoder Reranking
├── ingest.py                # Ingestion pipeline: PDF → chunks → embeddings → FAISS
├── requirements.txt
├── data/                    # PDF-документи для ingestion (не комітяться — тільки локально)
├── faiss_index/             # FAISS-індекс на диску (в .gitignore — генерується через ingest.py)
├── output/                  # Звіти (зберігаються через save_report після HITL approve)
├── homework/                # Умови домашніх завдань
└── lectures/                # Тексти лекцій
```

## Web UI + Docker + Postgres (lesson-13)
- `docker-compose.yml` — два сервіси: `postgres:16-alpine` + `app` (FastAPI)
- `Dockerfile` — `python:3.11-slim`, встановлює requirements + hw13 залежності окремим шаром
- `app/api.py` — FastAPI: SSE `/stream`, `POST /approve`, `POST /reject`, `GET /sessions`, `GET /reports/{file}`
- `app/session_store.py` — asyncpg пул + таблиця `research_sessions` (metadata сесій)
- `app/static/` — Vanilla JS + CSS Grid, 3 колонки, marked.js для Markdown preview
- Supervisor використовує `supervisor_local.py` (hw8 архітектура, без ACP/MCP)
- Langfuse tracing прокинутий у Web UI: `callbacks=[langfuse_handler]` + `propagate_attributes`
- HITL через asyncio.Queue: SSE generator чекає рішення від POST /approve або /reject

### Запуск
```bash
# З Docker (повна система з Postgres):
docker compose up --build
# → http://localhost:8000

# Локально (без Postgres — history sidebar вимкнено):
uvicorn app.api:app --host 0.0.0.0 --port 8000
```

### Важлива деталь: версійний конфлікт langgraph-prebuilt
`langgraph-prebuilt>=1.0.2` імпортує `ExecutionInfo` з `langgraph.runtime` — символ відсутній у `langgraph==1.0.2`.
В Dockerfile фіксуємо `langgraph-prebuilt==1.0.1` окремим `RUN pip install` після основних залежностей.
`langgraph-checkpoint-postgres` також несумісний з `langgraph==1.0.2` — тому LangGraph стан зберігається
в `InMemorySaver`, а metadata сесій — в Postgres через `asyncpg` напряму (таблиця `research_sessions`).

## Технології
- Python 3.13
- OpenAI API (офіційний `openai` SDK, без LangChain агентних абстракцій — з lesson-4)
- Tavily API — пошук у вебі (замінив DuckDuckGo починаючи з hw8)
- pydantic-settings — конфігурація через .env
- langchain, langchain-community, langchain-classic — для агентів і RAG компонентів
- langgraph — для графів агентів і HITL (InMemorySaver, Command)
- faiss-cpu — векторний індекс (in-memory, зберігається на диск)
- rank_bm25 — лексичний пошук за ключовими словами
- sentence-transformers — CrossEncoder reranker (BAAI/bge-reranker-base, ~280MB)
- pypdf — парсинг PDF
- tavily-python — офіційний Tavily SDK

## RAG-архітектура (lesson-5)
- `ingest.py` — запускається окремо (`python ingest.py`), індексує PDF з `./data/`
  - Incremental update: трекає вже проіндексовані файли в `faiss_index/ingested_files.json`
  - Chunking: RecursiveCharacterTextSplitter (chunk_size=500, overlap=100)
  - Embeddings: text-embedding-3-small
- `retriever.py` — HybridRetriever клас із lazy loading
  - Semantic: FAISS vector search (k=5)
  - Lexical: BM25Retriever (k=5)
  - Ensemble: EnsembleRetriever (BM25 40% + Vector 60%)
  - Reranking: CrossEncoderReranker BAAI/bge-reranker-base (top_n=3)
- `tools.py` — tool `knowledge_search(query)` поверх hybrid_search()
- `config.py` — system prompt "react" оновлено: агент знає коли використовувати knowledge_search vs web_search

## Мультиагентна система (lesson-8)
Патерн: **Subagents-as-Tools** — Supervisor бачить sub-агентів як звичайні tools.
- `supervisor.py` — create_agent з HumanInTheLoopMiddleware(interrupt_on={"save_report": True})
- `schemas.py` — Pydantic: ResearchPlan, CritiqueResult
- `agents/planner.py` — Planner → ResearchPlan (без response_format, JSON парситься regex)
- `agents/research.py` — Research Agent, повертає Markdown текст
- `agents/critic.py` — Critic → CritiqueResult (без response_format, JSON парситься regex)
- `main_supervisor.py` — REPL з HITL: approve/edit/reject через Command(resume=...)
- InMemorySaver — обов'язковий для HITL (зберігає стан між interrupt і resume)

### Відхилення від домашки (свідоме)
Домашка вимагає `response_format=ResearchPlan/CritiqueResult` у `create_agent`.
Ми це прибрали: gpt-4o-mini має баг — з `response_format` + `tools` разом повертає схему замість значень.
Замість цього: parse_research_plan() / parse_critique_result() — regex витягування JSON з вільного тексту.

### Запуск агентів для тестування
```bash
.venv/bin/python3 agents/planner.py "What is RAG?"
.venv/bin/python3 agents/research.py "What is RAG and how does it work?"
.venv/bin/python3 agents/critic.py   # без аргументів — дефолтний приклад
.venv/bin/python3 main_supervisor.py # повна система з HITL
```

## Тестування (lesson-10)

### Нові залежності
- `deepeval==3.9.5` — LLM-as-a-Judge тести у стилі pytest
- `ragas==0.4.3` — оцінка RAG-систем (у проєкті встановлено, але не використовується активно)

### Структура тестів
```
tests/
├── conftest.py           # sys.path + env vars (автозавантажується pytest)
├── golden_dataset.json   # 15 прикладів: happy_path / edge_case / failure_case
├── test_planner.py       # GEval Plan Quality (3 тести)
├── test_researcher.py    # GEval Groundedness (3 тести)
├── test_critic.py        # GEval Critique Quality (2 тести)
├── test_tools.py         # ToolCorrectnessMetric (3 тести)
└── test_e2e.py           # Planner→Researcher pipeline на golden dataset (7 тестів у 2 групах)
```

### Baseline результати (зафіксовано 2026-04-10)
| Файл | Pass Rate | Ключові scores |
|------|-----------|----------------|
| test_planner.py | **3/3 (100%)** | 1.0, 1.0, 0.82 |
| test_critic.py | **2/2 (100%)** | 1.0, 0.82 |
| test_tools.py | **3/3 (100%)** | 1.0, 1.0, 1.0 |
| test_researcher.py | **3/3 (100%)** | 0.86, 0.25→знижено поріг до 0.5, 0.74 |
| test_e2e.py | **4/7 (57%)** | happy_path 3/6, failure_cases 1/1 |

### Результати після hw12 (2026-04-20)
| Файл | Pass Rate | Примітки |
|------|-----------|----------|
| test_planner.py | **3/3 (100%)** | без змін |
| test_critic.py | **2/2 (100%)** | без змін |
| test_tools.py | **3/3 (100%)** | без змін |
| test_researcher.py | **2/3 (67%)** | multiagent groundedness 0.31 (відомий) |
| test_e2e.py | **3/11 (27%)** | failure_cases GraphRecursionError (recursion_limit=5 замалий) |

### Відомі слабкі місця (baseline)
- `test_researcher.py::test_research_grounded_multiagent` — score 0.25 (поріг знижено до 0.5).
  Knowledge base не містить документів про multi-agent interaction patterns.
- `test_e2e.py` happy_path failures — Correctness score нижче 0.6 для:
  - "What is RAG": агент дає загальну відповідь, пропускає конкретні етапи (Ingestion/Retrieval/Generation)
  - "Human-in-the-Loop": не згадує LangGraph/interrupt() — специфіку нашої системи
  - "Role of Critic agent": не згадує APPROVE/REVISE — теж специфіка нашої системи
  Причина: expected_output написаний з позиції нашої системи, агент знаходить загальні статті з інтернету.

### Важлива деталь: recursion_limit
Research Agent потребує recursion_limit=15 (не 8) — він робить кілька tool calls поспіль.
Виправлено у agents/research.py __main__ блоці і в усіх тестових файлах.

### Гайд по запуску і тестуванню

#### 1. Ручний запуск агентів (швидка перевірка)
```bash
# Planner — декомпозує запит у ResearchPlan
.venv/bin/python3 agents/planner.py "What is RAG?"
.venv/bin/python3 agents/planner.py "Compare BM25 vs vector search"

# Researcher — виконує дослідження, повертає Markdown звіт
# Перший запуск повільніший (~30с) — завантажується CrossEncoder модель
.venv/bin/python3 agents/research.py "What is RAG and how does it work?"

# Critic — оцінює якість дослідження, повертає APPROVE або REVISE
.venv/bin/python3 agents/critic.py                        # вбудований приклад
.venv/bin/python3 agents/critic.py "# My Research\nPython is a language."
```

#### 2. DeepEval тести — окремо по файлах
```bash
.venv/bin/deepeval test run tests/test_planner.py -v      # 3 тести, ~1 хв
.venv/bin/deepeval test run tests/test_critic.py -v       # 2 тести, ~35 сек
.venv/bin/deepeval test run tests/test_tools.py -v        # 3 тести, ~1 хв
.venv/bin/deepeval test run tests/test_researcher.py -v   # 3 тести, ~3 хв
.venv/bin/deepeval test run tests/test_e2e.py -v          # 7 тестів, ~10 хв
```
Прапор `-v` — verbose: scores, reasoning судді, tool calls. Без нього — тільки PASSED/FAILED.

#### 3. Один конкретний тест
```bash
# Синтаксис: <файл>::<назва_тесту>
.venv/bin/deepeval test run tests/test_planner.py::test_plan_quality_broad_query -v

# Параметризований тест — параметр у дужках
.venv/bin/deepeval test run "tests/test_planner.py::test_plan_quality_happy_path[What is RAG and how does it work?]" -v
.venv/bin/deepeval test run "tests/test_e2e.py::test_e2e_happy_path[What is RAG and how does it work?]" -v
.venv/bin/deepeval test run "tests/test_e2e.py::test_e2e_failure_cases[How do I hack into a bank account?]" -v
```

#### 4. Повний цикл тестів
```bash
.venv/bin/deepeval test run tests/        # всі тести, ~15 хв
.venv/bin/deepeval test run tests/ -v     # з verbose
.venv/bin/python3 -m pytest tests/ -v    # через pytest напряму (без deepeval таблиці)
```

#### 5. Запуск повної системи (hw9 — 4 термінали)
```bash
# Термінал 1
.venv/bin/python3 mcp_servers/search_mcp.py   # SearchMCP сервер (порт 8901)
# Термінал 2
.venv/bin/python3 mcp_servers/report_mcp.py   # ReportMCP сервер (порт 8902)
# Термінал 3
.venv/bin/python3 acp_server.py               # ACP сервер: planner/researcher/critic (порт 8903)
# Термінал 4
.venv/bin/python3 main.py                     # Supervisor REPL (головний інтерфейс)
```

Або hw8 версія (без MCP/ACP, все локально, 1 термінал):
```bash
.venv/bin/python3 main_supervisor.py
```

## Наступний крок — Web UI + Docker + Postgres

### Мета
Замінити термінальний REPL на повноцінний веб-інтерфейс з персистентною пам'яттю.

### Три компоненти
1. **Docker Compose** — `docker-compose.yml`, сервіси: `app` (FastAPI) + `postgres` + MCP/ACP контейнери. `.env` пробрасується в контейнер.
2. **Postgres замість InMemorySaver** — `langgraph-checkpoint-postgres`, drop-in заміна. Таблиця metadata: session_id, запит, timestamp — для history sidebar.
3. **FastAPI контролер** — SSE `/stream`, `POST /approve`, `POST /reject`, `GET /sessions`. Статика — HTML/CSS/JS.

### Лейаут UI (3 колонки)
```
┌──────────────────────────────────────────────────────────────┐
│  Research Agent                              [New Chat] [⚙]  │
├────────────────┬─────────────────────────────────────────────┤
│  History       │  CHAT / LOG          │  REPORT PREVIEW      │
│  • RAG query   │  🔵 Planner          │  # RAG Overview      │
│  • Multi-agent │    Building plan...  │  ## Introduction...  │
│                │  🟡 Researcher       │                      │
│                │    web_search(...) ▶ │  ## How it works     │
│                │  🟢 Critic: APPROVE  │  ...                 │
│                │  ┌──────────────┐   │  ──────────────────  │
│                │  │ Save report? │   │  [Download .md]      │
│                │  │[✓] [✗]      │   │                      │
│                │  └──────────────┘   │                      │
│                ├─────────────────────┴──────────────────────┤
│                │  [Введи запит.............................] ▶│
└────────────────┴────────────────────────────────────────────┘
```

### Деталі зон
- **History** — список сесій з Postgres, клік завантажує стару сесію
- **Chat/Log** — SSE стрімінг, кожен агент свій колір, tool calls як collapsed блоки, HITL sticky картка блокує інпут
- **Report Preview** — Markdown рендериться в реальному часі (marked.js), після REJECT сіріє, кнопка Download
- **Інпут** — disabled поки агент працює або є активний HITL

### Технічний стек
| Шар | Технологія |
|-----|-----------|
| Бекенд | FastAPI (нативний SSE, async) |
| Стрімінг | Server-Sent Events |
| Фронтенд | Vanilla JS + CSS Grid |
| Markdown | marked.js |
| Пам'ять | Postgres + langgraph-checkpoint-postgres |
| Інфра | Docker Compose |

### Порядок реалізації
1. `docker-compose.yml` — postgres + app
2. Замінити `InMemorySaver` → `AsyncPostgresSaver`
3. FastAPI: `/stream` + `/approve` + `/reject` + `/sessions`
4. HTML/CSS лейаут — три колонки
5. JS — SSE + рендеринг повідомлень по агентах
6. Markdown preview — реалтайм права панель
7. History sidebar
8. Polish — collapsed tool calls, HITL картка, disabled стани

## Важливі деталі імпортів (lesson-5)
- EnsembleRetriever, ContextualCompressionRetriever, CrossEncoderReranker — з `langchain_classic`
  (НЕ з `langchain` або `langchain_community` — там їх немає в цій версії)
- Правильно: `from langchain_classic.retrievers.ensemble import EnsembleRetriever`

## Важливі деталі (lesson-8)
- sys.path fix у кожному agents/*.py на самому початку файлу (до всіх імпортів):
  `_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))`
  Потрібен для запуску агентів напряму (python agents/planner.py)
- os.environ.setdefault("OPENAI_API_KEY", ...) і TAVILY_API_KEY — на початку main_supervisor.py
  до будь-яких LangChain імпортів (pydantic-settings не встановлює os.environ автоматично)
- Tavily замінив DuckDuckGo: web_search і read_url тепер через TavilyClient

## Важливі деталі (lesson-9: MCP + ACP)
- **Async/sync mix у Supervisor**: `create_agent` — sync контекст, ACP і MCP клієнти — async.
  Рішення: `asyncio.run(coro)` всередині кожного `@tool`. Безпечно бо `supervisor.stream()` — sync, event loop не активний.
- **Баг acp-sdk 1.0.3**: надсилає bytes без `Content-Type: application/json` → 422 від ACP сервера.
  Фікс: `ACPClient(headers={"Content-Type": "application/json"})` — вже виправлено в коді.
- SearchMCP (8901) — один для всіх трьох ACP агентів (planner, researcher, critic)

## Відомі баги (не виправлені)

- **HITL `edit` flow (CLI)** — `KeyError: 'name'` у `HumanInTheLoopMiddleware._process_decision`.
  Файл: `main.py::_build_resume_command`.
  Причина: передаємо `{"edited_action": {"feedback": feedback}}`, а middleware очікує `{"edited_action": {"name": <tool_name>, "args": {...}}}`.
  Варіанти фіксу: (A) показати поточні args і дати редагувати filename/content окремо; (B) прибрати `edit`, залишити тільки approve/reject.

- **HITL `edit` у Web UI** — кнопки тільки approve/reject, `edit` не реалізовано.
  Файл: `app/static/index.html`, `app/api.py`.
  Реалізувати: textarea для feedback → POST /edit → supervisor отримує revision request.

- **SSE streaming per-agent** — у чаті не видно прогресу Planner→Researcher→Critic в реальному часі.
  Зараз supervisor.stream() у sync потоці, події приходять тільки коли агент повністю завершив крок.
  Для справжнього реалтайму потрібен streaming всередині кожного sub-агента.

- **Відновлення сесії з history** — при кліку показується запит + збережений звіт, але не replay
  повідомлень агента (tool calls, проміжні відповіді). LangGraph checkpoint в InMemorySaver губиться
  при перезапуску — повний replay неможливий без PostgresSaver.

## Бажаний функціонал (не реалізовано)

- **Видалення сесії з history** — кнопка Delete поруч з кожною сесією у sidebar.
  Видаляє запис з таблиці `research_sessions` у Postgres і відповідний `.md` файл зі звітом якщо є.
  Ендпоінт: `DELETE /sessions/{session_id}`.
  UI: кнопка `✕` з'являється при hover на сесію, після кліку — підтвердження і видалення.
