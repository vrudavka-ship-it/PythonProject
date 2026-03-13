# Research Agent

Навчальний проєкт на **Python + OpenAI API** — Research Agent з власною реалізацією ReAct-циклу.

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
- зв'язний діалог у межах однієї сесії (пам'ять через ручний список `messages`);
- multi-step tool calling;
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
├── config.py            # System prompts, settings, константи
├── requirements.txt
├── example_output/
│   └── report.md        # Приклад згенерованого звіту
└── README.md
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
- друк фінальної відповіді;
- автоматичне збереження звіту у файл.

### `agent.py`
Містить власну реалізацію ReAct-циклу:
- прямий виклик OpenAI API (без LangChain агентних абстракцій);
- цикл: LLM call → перевірка `finish_reason` → виконання tool calls → повторити;
- логування кожного кроку ітерації;
- обробка помилок при виконанні tools;
- зупинка при досягненні ліміту ітерацій.

### `tools.py`
Містить два блоки:
- **реалізація tools** — веб-пошук, читання URL, запис звіту;
- **`TOOLS_SCHEMA`** — JSON Schema опис tools для OpenAI API (без `@tool` декоратора LangChain);
- **`TOOLS_MAP`** — словник `{назва → функція}` для виклику tool за іменем.

Також тут є:
- обрізання довгих текстів (context engineering);
- timeout-захист для мережевих викликів;
- логування кожного tool call у консоль.

### `config.py`
Містить:
- налаштування застосунку через `.env` (pydantic-settings);
- бібліотеку system prompts для різних технік (zero-shot, few-shot, CoT, ReAct та інші);
- константи й ліміти.

Активний промпт: `SYSTEM_PROMPTS["react"]`.

---

## Які технології використані

- **Python 3.13**
- **OpenAI API** (через офіційний `openai` SDK, без LangChain агентних абстракцій)
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
- `TEMPERATURE` — "креативність" моделі
- `SEARCH_RESULTS_LIMIT` — скільки результатів повертати в `web_search`
- `SEARCH_SNIPPET_MAX_CHARS` — ліміт для сніпетів пошуку
- `PAGE_TEXT_MAX_CHARS` — ліміт для тексту сторінки
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

─── Iteration 1/12 (messages in context: 2) ───
🔧 Tool call: web_search(query='naive RAG retrieval method')
📎 Result: Found 5 results

─── Iteration 2/12 (messages in context: 5) ───
🔧 Tool call: read_url(url='https://...')
📎 Result: [7704 chars] extracted from page

─── Iteration 3/12 (messages in context: 8) ───
🔧 Tool call: write_report(filename='report.md', content_len=3200)
📎 Result: Report saved to example_output/report.md

Agent: [short summary to the user]
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

## Як працює пам'ять

У проєкті пам'ять реалізована вручну через список `messages`:
- `main.py` створює список і веде його між запитами;
- агент отримує список, додає нові повідомлення (assistant + tool results) і повертає оновлений список;
- агент пам'ятає попередні повідомлення в межах **поточного запуску програми**;
- після завершення процесу пам'ять сесії скидається.

Це свідома заміна `MemorySaver` (LangGraph) — тепер ми повністю контролюємо список повідомлень.

---

## Context engineering

Щоб не перевантажувати контекстне вікно моделі:
- результати `web_search` обрізаються до розумного ліміту;
- текст із `read_url` теж обрізається;
- великі сторінки не передаються у LLM повністю.

Це важливо, тому що:
- великі tool results уповільнюють роботу;
- збільшують вартість запиту;
- можуть "розмити" увагу моделі.

---

## Обробка помилок

У tools додано базовий захист:
- невалідний URL;
- timeout мережевого виклику;
- помилки завантаження сторінки;
- відсутність результатів пошуку;
- невідомий tool name (агент отримує зрозуміле повідомлення про помилку і продовжує).

---

## Збереження звіту

Фінальна відповідь автоматично зберігається у Markdown-файл:

```text
example_output/report.md
```

Також реалізовано окремий tool `write_report(...)`, щоб агент міг зберігати результат самостійно, якщо це потрібно сценарію. Для research-запитів виклик `write_report` є обов'язковим (прописано в system prompt).

---

## Залежності

Файл `requirements.txt` містить зафіксовані версії бібліотек для відтворюваного середовища.

Основні залежності:
- `openai` — офіційний SDK для OpenAI API
- `ddgs` — DuckDuckGo search
- `trafilatura` — витягування тексту зі сторінок
- `pydantic`
- `pydantic-settings`

---

## Обмеження поточної реалізації

Це навчальний проєкт, тому тут є кілька свідомих спрощень:
- звіти зберігаються в один і той самий файл;
- логування зроблене через прості `print(...)`;
- немає кешування результатів;
- немає довготривалої пам'яті між сесіями.

---

## Можливі покращення

Ідеї для наступних версій:
- генерувати унікальні імена файлів звітів;
- додати structured logging замість `print`;
- додати cache для `web_search` і `read_url`;
- підтримати кілька LLM-провайдерів через `.env`;
- зберігати історію сесій у SQLite або іншому сховищі;
- додати цитування джерел у фінальному звіті.

---

## Висновок

Цей проєкт демонструє власну реалізацію **ReAct agent**:
- з прямим викликом OpenAI API (без LangChain агентних абстракцій);
- з tool calling через JSON Schema;
- з ручним керуванням пам'яттю (список `messages`);
- з context engineering;
- з генерацією Markdown-звітів.

Окремо він спроєктований так, щоб код був більш зрозумілим для розробника, який переходить із Java на Python.
