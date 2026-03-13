# Research Agent

Невеликий навчальний проєкт на **Python + LangChain**, який запускає research-агента з інтерактивного терміналу.

Агент:
- приймає питання від користувача;
- сам вирішує, коли треба використати інструменти;
- виконує пошук у вебі;
- читає повний текст релевантних сторінок;
- формує структурований **Markdown-звіт**;
- зберігає результат у файл.

Проєкт написаний у навчальному стилі: у коді є додаткові коментарі, щоб було простіше розібратись у Python, якщо у вас бекграунд переважно з Java.

---

## Можливості

### Реалізовані tools
- `web_search(query: str)` — пошук у вебі через DuckDuckGo
- `read_url(url: str)` — читання повного тексту сторінки
- `write_report(filename: str, content: str)` — збереження Markdown-звіту

### Можливості агента
- інтерактивний запуск через `python main.py`;
- зв'язний діалог у межах однієї сесії;
- multi-step tool calling;
- базова обробка помилок;
- обрізання довгих результатів tools для економії контексту;
- автоматичне збереження фінальної відповіді в Markdown-файл.

---

## Структура проєкту

```text
research-agent/
├── main.py              # Entry point — interactive REPL loop
├── agent.py             # Agent setup (LLM, tools, memory, create_agent)
├── tools.py             # Tool definitions and implementations
├── config.py            # System prompt, settings, constants
├── requirements.txt
├── example_output/
│   └── report.md        # Example generated report
└── README.md            # Setup instructions, architecture overview
```

---

## Архітектура

### `main.py`
Точка входу в програму.

Відповідає за:
- запуск REPL-циклу;
- читання запитів користувача;
- виклик агента;
- друк фінальної відповіді;
- автоматичне збереження звіту у файл.

### `agent.py`
Містить збірку агента:
- створення LLM;
- підключення tools;
- підключення system prompt;
- підключення `MemorySaver` для пам'яті діалогу в межах сесії.

### `tools.py`
Містить реалізацію інструментів:
- веб-пошук;
- читання URL;
- запис звіту у файл.

Також тут є:
- обрізання довгих текстів;
- timeout-захист для мережевих викликів;
- базове логування tool calls для дебагу.

### `config.py`
Містить:
- налаштування застосунку через `.env`;
- системний prompt;
- константи й ліміти.

---

## Які технології використані

- **Python**
- **LangChain**
- **LangGraph / MemorySaver**
- **langchain-openai**
- **ddgs** — для DuckDuckGo search
- **trafilatura** — для витягування основного тексту зі сторінки
- **pydantic-settings** — для конфігурації через `.env`

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
- `TEMPERATURE` — “креативність” моделі
- `SEARCH_RESULTS_LIMIT` — скільки результатів повертати в `web_search`
- `SEARCH_SNIPPET_MAX_CHARS` — ліміт для сніпетів пошуку
- `PAGE_TEXT_MAX_CHARS` — ліміт для тексту сторінки
- `OUTPUT_DIR` — директорія для збереження звітів
- `DEFAULT_REPORT_FILENAME` — стандартне ім’я звіту
- `MAX_ITERATIONS` — ліміт кроків агента
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

```bash
python main.py
```

Після запуску з’явиться REPL:

```text
Research Agent started.
Type your question and press Enter.
Commands: 'exit', 'quit', ':q'
```

---

## Приклади запитів

### Просте питання

```text
чи важко працювати на пайтоні джавісту
```

Очікувана поведінка:
- агент відповідає напряму;
- tools можуть не викликатися;
- результат все одно зберігається у файл.

### Research-запит

```text
Порівняй naive RAG, sentence-window retrieval і parent-child retrieval
```

Очікувана поведінка:
- кілька викликів `web_search`;
- 1–2 або більше викликів `read_url`;
- фінальна Markdown-відповідь;
- збереження результату у `example_output/report.md`.

---

## Приклад реальної поведінки агента

Для research-запиту агент може працювати приблизно так:

```text
User: Порівняй naive RAG, sentence-window retrieval і parent-child retrieval

Agent:
  -> web_search("naive RAG retrieval method")
  -> web_search("sentence-window retrieval method")
  -> web_search("parent-child retrieval method")
  -> read_url("https://...")
  -> read_url("https://...")
  -> final Markdown report
```

---

## Як перевірити, що agent loop справді працює

У проєкті додано логування tool calls.

Для складного запиту в консолі мають з’являтися рядки на кшталт:

```text
[tool] web_search(query='naive RAG retrieval method')
[tool] web_search -> 5 results
[tool] read_url(url='https://...')
[tool] read_url -> 7704 chars
```

Це підтверджує, що агент:
- не просто відповідає з пам’яті моделі;
- а реально використовує інструменти.

---

## Як працює пам’ять

У проєкті використовується `MemorySaver`.

Це означає:
- агент пам’ятає попередні повідомлення в межах **поточного запуску програми**;
- якщо після одного питання поставити уточнення, він може використати попередній контекст;
- після завершення процесу пам’ять сесії скидається.

---

## Context engineering

Щоб не перевантажувати контекстне вікно моделі:
- результати `web_search` обрізаються до розумного ліміту;
- текст із `read_url` теж обрізається;
- великі сторінки не передаються у LLM повністю.

Це важливо, тому що:
- великі tool results уповільнюють роботу;
- збільшують вартість запиту;
- можуть “розмити” увагу моделі.

---

## Обробка помилок

У tools додано базовий захист:
- невалідний URL;
- timeout мережевого виклику;
- помилки завантаження сторінки;
- відсутність результатів пошуку.

У разі помилки tool повертає зрозуміле повідомлення, а не валить увесь процес.

---

## Збереження звіту

Фінальна відповідь автоматично зберігається у Markdown-файл:

```text
example_output/report.md
```

Також реалізовано окремий tool `write_report(...)`, щоб агент міг зберігати результат самостійно, якщо це потрібно сценарію.

---

## Чому використано `create_agent`

У завданні дозволено використовувати:
- `create_react_agent`
- або `create_agent`

У цьому проєкті використано `create_agent`, тому що він дає той самий базовий agent loop з tools і добре інтегрується з поточною структурою.

---

## Залежності

Файл `requirements.txt` містить зафіксовані версії бібліотек для відтворюваного середовища.

Основні залежності:
- `langchain`
- `langgraph`
- `langchain-openai`
- `ddgs`
- `trafilatura`
- `pydantic`
- `pydantic-settings`

---

## Обмеження поточної реалізації

Це навчальний проєкт, тому тут є кілька свідомих спрощень:
- звіти зберігаються в один і той самий файл;
- логування зроблене через прості `print(...)`;
- немає складної системи кешування результатів;
- немає окремого persistence layer для довготривалої пам’яті;
- agent loop ще можна покращити, щоб уникати повторних пошукових запитів.

---

## Можливі покращення

Ідеї для наступних версій:
- генерувати унікальні імена файлів звітів;
- додати structured logging замість `print`;
- додати cache для `web_search` і `read_url`;
- підтримати кілька LLM-провайдерів через `.env`;
- додати окремі runtime-output і example-output директорії;
- зберігати історію сесій у SQLite або іншому сховищі;
- додати цитування джерел у фінальному звіті.

---

## Приклад output

У директорії `example_output/` збережений приклад Markdown-звіту:

```text
example_output/report.md
```

Це приклад того, який результат генерує агент для research-запитів.

---

## Висновок

Цей проєкт демонструє базову реалізацію **research agent**:
- з LangChain agent loop;
- з tool calling;
- з memory;
- з context engineering;
- з генерацією Markdown-звітів.

Окремо він спроєктований так, щоб код був більш зрозумілим для розробника, який переходить із Java на Python.
```