# Research Agent

Навчальний проєкт на **Python + OpenAI API** — мультиагентна дослідницька система з Supervisor, спеціалізованими sub-агентами і HITL (Human-in-the-Loop).

Проєкт написаний у навчальному стилі: у коді є додаткові коментарі, щоб було простіше розібратись у Python, якщо у вас бекграунд переважно з Java.

---

## Архітектура (lesson-8)

```
User (REPL)
  │
  ▼
Supervisor Agent
  │
  ├── 1. plan(request)       → Planner Agent      → ResearchPlan
  │
  ├── 2. research(plan)      → Research Agent     → [web_search, read_url, knowledge_search]
  │
  ├── 3. critique(findings)  → Critic Agent       → CritiqueResult
  │       │
  │       ├── verdict: APPROVE  → step 4
  │       └── verdict: REVISE   → back to step 2 з feedback
  │
  └── 4. save_report(...)    → HITL: approve / edit / reject
```

Патерн: **Subagents-as-Tools** — Supervisor бачить кожного sub-агента як звичайний tool.

---

## Структура проєкту

```text
PythonProject/
├── main.py              # REPL (hw5: single agent, OpenAI API прямо)
├── main_supervisor.py   # REPL (hw8: Supervisor + HITL)
├── agent.py             # Власний ReAct loop (hw5)
├── supervisor.py        # Supervisor Agent + sub-agents-as-tools
├── schemas.py           # Pydantic: ResearchPlan, CritiqueResult
├── agents/
│   ├── __init__.py
│   ├── planner.py       # Planner Agent → ResearchPlan
│   ├── research.py      # Research Agent
│   └── critic.py        # Critic Agent → CritiqueResult
├── tools.py             # web_search (Tavily), read_url, knowledge_search, write_report
├── config.py            # Settings + system prompts для всіх агентів
├── retriever.py         # Hybrid RAG: BM25 + FAISS + CrossEncoder Reranking
├── ingest.py            # PDF → chunks → embeddings → FAISS
├── requirements.txt
├── data/                # PDF-документи для RAG (не в git)
├── faiss_index/         # FAISS-індекс (генерується через ingest.py, не в git)
├── output/              # Збережені Markdown-звіти
└── README.MD
```

---

## Технології

- **Python 3.13**
- **OpenAI API** — офіційний `openai` SDK (без LangChain агентних абстракцій у hw5)
- **Tavily API** — пошук у вебі і читання сторінок (оптимізовано для LLM-агентів)
- **LangChain / LangGraph** — `create_agent`, `HumanInTheLoopMiddleware`, `InMemorySaver`
- **faiss-cpu** — векторний індекс для semantic search
- **rank_bm25** — лексичний пошук за ключовими словами
- **sentence-transformers** — CrossEncoder reranker (`BAAI/bge-reranker-base`)
- **pypdf** — парсинг PDF
- **pydantic-settings** — конфігурація через `.env`

---

## Встановлення

```bash
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Налаштування `.env`

```dotenv
OPENAI_API_KEY=<YOUR_OPENAI_API_KEY>
TAVILY_API_KEY=<YOUR_TAVILY_API_KEY>
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

**НІКОЛИ не комітьте `.env` у git.** Використовуйте `.env.example` як шаблон.

---

## Запуск

### Крок 1 — Побудова локальної бази знань (один раз)

```bash
# Додай PDF-файли в директорію data/
.venv/bin/python3 ingest.py
```

### Крок 2 — Запуск

```bash
# Мультиагентна система (hw8) — рекомендовано
.venv/bin/python3 main_supervisor.py

# Single agent (hw5)
.venv/bin/python3 main.py
```

### Тестування окремих агентів

```bash
.venv/bin/python3 agents/planner.py "What is RAG?"
.venv/bin/python3 agents/research.py "What is RAG and how does it work?"
.venv/bin/python3 agents/critic.py   # без аргументів — вбудований приклад
```

---

## HITL (Human-in-the-Loop)

Коли Supervisor готовий зберегти звіт — система зупиняється і питає підтвердження:

```
⏸️  ACTION REQUIRES APPROVAL
  Tool:  save_report
  File:  rag_comparison.md
  Preview: # Comparison of RAG Approaches...

👉 approve / edit / reject:
```

- `approve` — зберегти як є
- `edit` — ввести feedback, Supervisor переробить звіт
- `reject` — скасувати

---

## RAG pipeline

```
Offline (один раз):
  PDF files → PyPDFLoader → RecursiveCharacterTextSplitter
  → OpenAI Embeddings → FAISS index (збережено на диск)

Online (при кожному knowledge_search):
  query → BM25 search  ↘
                         EnsembleRetriever → top-10 кандидатів
  query → FAISS search ↗
                         → CrossEncoder Reranker → top-3 результати
```

---

## Обмеження

Це навчальний проєкт:
- логування через `print()`
- немає кешування результатів пошуку
- CrossEncoder модель завантажується при першому виклику (~5-10 сек)
- пам'ять між сесіями не зберігається (InMemorySaver — тільки в межах процесу)
