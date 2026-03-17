# Research Agent

Навчальний проєкт на **Python + OpenAI API** — Research Agent з власною реалізацією ReAct-циклу та RAG-системою.

Агент:
- приймає питання від користувача;
- сам вирішує, коли і де шукати — в інтернеті або в локальній базі знань;
- виконує пошук у вебі та по локальних PDF-документах;
- читає повний текст релевантних сторінок;
- формує структурований **Markdown-звіт**;
- зберігає результат у файл.

Проєкт написаний у навчальному стилі: у коді є додаткові коментарі, щоб було простіше розібратись у Python, якщо у вас бекграунд переважно з Java.

---

## Можливості

### Реалізовані tools
- `knowledge_search(query: str)` — гібридний пошук у локальній базі знань (PDF-документи)
- `web_search(query: str)` — пошук у вебі через DuckDuckGo
- `read_url(url: str)` — читання повного тексту сторінки
- `write_report(filename: str, content: str)` — збереження Markdown-звіту

### Можливості агента
- інтерактивний запуск через `python main.py`;
- зв'язний діалог у межах однієї сесії (пам'ять через ручний список `messages`);
- multi-step tool calling;
- агент сам вирішує: шукати в локальних документах чи у вебі, або комбінувати обидва джерела;
- обробка помилок у кожному tool;
- ліміт ітерацій (захист від нескінченного циклу);
- обрізання довгих результатів tools для економії контексту;
- логування кожного tool call у консоль;
- автоматичне збереження фінальної відповіді в Markdown-файл.

---

## Структура проєкту

```text
PythonProject/
├── main.py              # Entry point — interactive REPL loop
├── agent.py             # Власний ReAct loop (прямий виклик OpenAI API)
├── tools.py             # Tool definitions (JSON Schema) та реалізації
├── retriever.py         # Hybrid Retrieval: BM25 + Vector + CrossEncoder Reranking
├── ingest.py            # Ingestion pipeline: PDF → chunks → embeddings → FAISS
├── config.py            # System prompts, settings, константи
├── requirements.txt
├── data/                # PDF-документи для локальної бази знань
├── faiss_index/         # FAISS-індекс (генерується через python ingest.py, не в git)
├── example_output/      # Згенеровані Markdown-звіти
└── README.MD
```

---

## Архітектура

### `main.py`
Точка входу в програму.

Відповідає за:
- запуск REPL-циклу;
- читання запитів користувача;
- ручне ведення списку `messages` (пам'ять сесії без `MemorySaver`);
- виклик агента;
- друк фінальної відповіді.

### `agent.py`
Містить власну реалізацію ReAct-циклу:
- прямий виклик OpenAI API (без LangChain агентних абстракцій);
- цикл: LLM call → перевірка `finish_reason` → виконання tool calls → повторити;
- логування кожного кроку ітерації;
- обробка помилок при виконанні tools;
- зупинка при досягненні ліміту ітерацій.

### `tools.py`
Містить чотири блоки:
- **реалізація tools** — `knowledge_search`, `web_search`, `read_url`, `write_report`;
- **`TOOLS_SCHEMA`** — JSON Schema опис tools для OpenAI API (без `@tool` декоратора LangChain);
- **`TOOLS_MAP`** — словник `{назва → функція}` для виклику tool за іменем.

Також тут є:
- обрізання довгих текстів (context engineering);
- timeout-захист для мережевих викликів;
- логування кожного tool call у консоль.

### `ingest.py`
Pipeline для завантаження документів у векторну базу даних.

Запускається окремо: `python ingest.py`

Алгоритм:
1. Сканує `./data/` і знаходить нові або змінені PDF-файли (incremental update).
2. Завантажує і ріже документи на чанки (`RecursiveCharacterTextSplitter`, chunk_size=500).
3. Генерує ембедінги через OpenAI API (`text-embedding-3-small`).
4. Зберігає FAISS-індекс на диск (`faiss_index/`).
5. Трекає вже проіндексовані файли в `faiss_index/ingested_files.json`.

### `retriever.py`
Гібридний пошук по локальній базі знань.

Три шари пошуку:
1. **Semantic (Vector)** — FAISS, пошук за cosine similarity. Розуміє синоніми і контекст.
2. **Lexical (BM25)** — пошук за ключовими словами. Точні збіги термінів, абревіатур.
3. **Reranking (CrossEncoder)** — модель `BAAI/bge-reranker-base` читає пару (запит + документ) разом і дає точніший score релевантності.

Результат: top-3 найрелевантніших чанки з посиланням на джерело (файл + сторінка).

### `config.py`
Містить:
- налаштування застосунку через `.env` (pydantic-settings);
- бібліотеку system prompts для різних технік (zero-shot, few-shot, CoT, ReAct та інші);
- константи й ліміти.

Активний промпт: `SYSTEM_PROMPTS["react"]` — включає інструкції для вибору між `knowledge_search` і `web_search`.

---

## Які технології використані

- **Python 3.13**
- **OpenAI API** (через офіційний `openai` SDK, без LangChain агентних абстракцій)
- **ddgs** — для DuckDuckGo search
- **trafilatura** — для витягування основного тексту зі сторінки
- **pydantic-settings** — для конфігурації через `.env`
- **faiss-cpu** — векторний індекс для semantic search
- **rank_bm25** — лексичний пошук за ключовими словами
- **sentence-transformers** — CrossEncoder reranker (`BAAI/bge-reranker-base`)
- **pypdf** — парсинг PDF документів
- **langchain-community, langchain-classic** — компоненти для RAG pipeline

---

## Встановлення

> Рекомендовано використовувати **Python 3.13**.
> На Python 3.14 деякі залежності можуть мати проблеми зі збіркою нативних модулів.

### 1. Створити virtualenv

```bash
python3.13 -m venv .venv
source .venv/bin/activate
```

### 2. Встановити залежності

```bash
pip install -r requirements.txt
```

---

## Налаштування `.env`

Створи файл `.env` у корені проєкту.

Приклад:

```dotenv
OPENAI_API_KEY=<YOUR_OPENAI_API_KEY>
OPENAI_MODEL=gpt-4o-mini
TEMPERATURE=0.2
SEARCH_RESULTS_LIMIT=5
SEARCH_SNIPPET_MAX_CHARS=500
PAGE_TEXT_MAX_CHARS=8000
OUTPUT_DIR=example_output
DEFAULT_REPORT_FILENAME=report.md
MAX_ITERATIONS=12
REQUEST_TIMEOUT_SECONDS=20
```

### Пояснення змінних
- `OPENAI_API_KEY` — API-ключ моделі
- `OPENAI_MODEL` — назва моделі
- `TEMPERATURE` — "креативність" моделі
- `SEARCH_RESULTS_LIMIT` — скільки результатів повертати в `web_search`
- `SEARCH_SNIPPET_MAX_CHARS` — ліміт для сніпетів пошуку
- `PAGE_TEXT_MAX_CHARS` — ліміт для тексту сторінки і результатів `knowledge_search`
- `OUTPUT_DIR` — директорія для збереження звітів
- `DEFAULT_REPORT_FILENAME` — стандартне ім'я звіту
- `MAX_ITERATIONS` — ліміт кроків агента (захист від нескінченного циклу)
- `REQUEST_TIMEOUT_SECONDS` — timeout для мережевих викликів

---

## Безпека

**НІКОЛИ не комітьте `.env` у git.**

У репозиторії має бути:
- `.env.example` — шаблон
- `.env` — тільки локально

Переконайтесь, що `.env` доданий у `.gitignore`.

---

## Запуск

### Крок 1 — Побудова локальної бази знань

Перед першим запуском потрібно проіндексувати PDF-документи:

```bash
# Додай PDF-файли в директорію data/
python ingest.py
```

Що відбувається:
```text
🔍 Scanning data directory...
📁 Found 3 PDF file(s): [...]
✂️  Total new chunks: 464
🔨 Building new FAISS index from 464 chunk(s)...
💾 FAISS index saved to: faiss_index/
✅ Ingestion complete!
```

При додаванні нових файлів у `data/` — просто запусти `python ingest.py` знову. Вже проіндексовані файли не перероблятимуться.

### Крок 2 — Запуск агента

```bash
python main.py
```

Після запуску з'явиться REPL:

```text
Research Agent started.
Type your question and press Enter.
Commands: 'exit', 'quit', ':q'
```

---

## Приклади запитів

### Питання з локальної бази знань

```text
Що таке RAG і які є підходи до retrieval?
```

Очікувана поведінка:
- агент викликає `knowledge_search` — шукає в локальних PDF;
- формує звіт на основі знайдених фрагментів.

### Комбінований research-запит

```text
Порівняй підходи до RAG з локальної бази і знайди нові RAG-техніки 2025 року
```

Очікувана поведінка:
- `knowledge_search` — локальна база;
- `web_search` → `read_url` — актуальна інформація з веб;
- `write_report` — Markdown-звіт з обох джерел.

---

## Приклад реальної поведінки агента

```text
You: Що таке RAG і які є підходи до retrieval?

─── Iteration 1/12 (messages in context: 2) ───
🔧 Tool call: knowledge_search(query='RAG retrieval approaches')
   [RAG] Loading FAISS index...
   [RAG] Building BM25 index...
   [RAG] Loading CrossEncoder reranker (BAAI/bge-reranker-base)...
   [RAG] Ready.
📎 Result: [3 document(s) found]

─── Iteration 2/12 (messages in context: 4) ───
🔧 Tool call: write_report(filename='rag_approaches.md', content_len=1277)
📎 Result: Report saved to example_output/rag_approaches.md

Agent: RAG — це техніка, де LLM отримує релевантний контекст із зовнішніх джерел...
```

---

## Як працює ReAct loop

`agent.py` реалізує власний ReAct-цикл (Reason + Act):

```
loop:
  1. Відправляємо messages у LLM
  2. LLM повертає відповідь:
     - finish_reason == "stop"       → фінальна відповідь, зупиняємось
     - finish_reason == "tool_calls" → виконуємо tools, додаємо результати в messages, повторюємо
  3. Якщо вичерпали MAX_ITERATIONS → повертаємо повідомлення про ліміт
```

Це пряма реалізація без `create_react_agent` або інших LangChain/LangGraph агентних абстракцій.

---

## Як працює RAG pipeline

```
Offline (один раз або при оновленні даних):
  PDF files → PyPDFLoader → RecursiveCharacterTextSplitter
  → OpenAI Embeddings → FAISS index (збережено на диск)

Online (при кожному запиті knowledge_search):
  query → [BM25 search]     ↘
                              EnsembleRetriever → top-10 кандидатів
  query → [Vector search]   ↗
                              → CrossEncoder Reranker → top-3 результати
                              → відформатований текст → LLM контекст
```

---

## Як працює пам'ять

У проєкті пам'ять реалізована вручну через список `messages`:
- `main.py` створює список і веде його між запитами;
- агент отримує список, додає нові повідомлення (assistant + tool results);
- агент пам'ятає попередні повідомлення в межах **поточного запуску програми**;
- після завершення процесу пам'ять сесії скидається.

Це свідома заміна `MemorySaver` (LangGraph) — ручний контроль над списком повідомлень.

---

## Context engineering

Щоб не перевантажувати контекстне вікно моделі:
- результати `web_search` обрізаються до розумного ліміту;
- текст із `read_url` і `knowledge_search` теж обрізається (`PAGE_TEXT_MAX_CHARS`);
- великі сторінки не передаються у LLM повністю.

---

## Обробка помилок

У tools додано базовий захист:
- невалідний URL;
- timeout мережевого виклику;
- помилки завантаження сторінки;
- відсутність результатів пошуку;
- відсутність FAISS-індексу (підказує запустити `python ingest.py`);
- невідомий tool name (агент отримує зрозуміле повідомлення і продовжує).

---

## Залежності

Файл `requirements.txt` містить зафіксовані версії бібліотек для відтворюваного середовища.

Основні залежності:
- `openai` — офіційний SDK для OpenAI API
- `ddgs` — DuckDuckGo search
- `trafilatura` — витягування тексту зі сторінок
- `faiss-cpu` — векторний індекс
- `rank_bm25` — BM25 лексичний пошук
- `sentence-transformers` — CrossEncoder reranker
- `pypdf` — парсинг PDF
- `langchain-community`, `langchain-classic` — RAG компоненти
- `pydantic`, `pydantic-settings`

---

## Обмеження поточної реалізації

Це навчальний проєкт, тому тут є кілька свідомих спрощень:
- логування зроблене через прості `print(...)`;
- немає кешування результатів web_search;
- немає довготривалої пам'яті між сесіями;
- CrossEncoder модель завантажується при першому виклику `knowledge_search` (~5-10 сек).

---

## Висновок

Цей проєкт демонструє **Agentic RAG**:
- власна реалізація ReAct loop з прямим викликом OpenAI API;
- tool calling через JSON Schema;
- hybrid search (BM25 + vector) + CrossEncoder reranking;
- агент сам вирішує коли шукати локально, а коли — у вебі;
- ручне керування пам'яттю (список `messages`);
- context engineering.

Окремо він спроєктований так, щоб код був більш зрозумілим для розробника, який переходить із Java на Python.
