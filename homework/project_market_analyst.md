# Аналітик ринку

## Опис

Мультиагентна система для дослідження ринку. Analyst збирає дані, Critic критично оцінює (structured debate), Compiler компілює фінальний звіт.

## Архітектурний патерн

**Основний патерн:** Evaluator-Optimizer (Anthropic) — Analyst генерує звіт, Critic оцінює якість. Якщо якість недостатня — повертаємось до Analyst з feedback. Фінальна частина (Critic → Compiler) — Prompt Chaining.

**Тип взаємодії:** конкурентна (елементи structured debate) — Critic навмисно шукає слабкі місця у звіті Analyst, як Bear Analyst шукає ризики в Investment Committee (Лекція 7 §2.2). Це забезпечує більш збалансований результат.

## Агенти та мінімальні інструменти

**Research Analyst** (Execution + Context)
- Роль: отримує тему, шукає дані, тренди, звіти, компілює чорновик
- Інструменти: DuckDuckGo Search (ринкові дані, новини), RAG (пошук по завантажених статтях)

**Critic** (Assurance)
- Роль: рев'ює чорновик, перевіряє упередженість, необґрунтовані твердження, логічні прогалини. Роль devil's advocate
- Інструменти: DuckDuckGo Search (верифікація тверджень), LLM structured output (CriticFeedback)

**Report Compiler** (Execution)
- Роль: формує фінальний структурований звіт за Pydantic-схемою, зберігає як файл-артефакт
- Інструменти: File System tool (збереження фінального звіту), LLM structured output (генерація за схемою)

### Навіщо кожен інструмент (real-world motivation)

1. **DuckDuckGo Search (Analyst, Critic)**: Analyst збирає первинну інформацію з відкритих джерел: ринкові дані, новини, тренди, звіти компаній. Critic використовує пошук для незалежної верифікації тверджень — якщо звіт стверджує «ринок зростає на 15% YoY», Critic перевіряє цю цифру в інших джерелах.
2. **RAG (Analyst)**: Аналітик працює не тільки з live-пошуком, а й із заздалегідь зібраним корпусом: завантажені PDF-звіти (McKinsey, CB Insights), збережені статті, research notes. RAG дає доступ до цього корпусу. Без RAG агент покладався б тільки на live-пошук, який може не знайти специфічні або раніше збережені дані.
3. **File System tool (Compiler)**: Тільки Compiler зберігає файл — кінцевий артефакт системи: готовий `.md`-звіт як deliverable. Проміжні дані (чорновики, feedback) передаються через LangGraph state.
4. **LLM structured output (Critic, Compiler)**: Critic повертає `CriticFeedback` з вердиктом, списком проблем та score — для автоматичного routing у графі. Compiler генерує `FinalReport` за фіксованою Pydantic-схемою — стандартизований формат звіту (executive summary, findings, recommendations, sources).

## Structured Output контракти (Pydantic)

- **DraftReport:** `executive_summary: str, findings: list[Finding], sources: list[str], data_points: list[str]`
- **CriticFeedback:** `verdict: Literal["APPROVED","NEEDS_REVISION"], issues: list[str], missing_perspectives: list[str], fact_check_results: list[str], score: float`
- **FinalReport:** `executive_summary: str, key_findings: list[str], recommendations: list[str], sources: list[str], methodology: str`

## Підготовка даних для RAG

Студент збирає колекцію документів по обраній темі:

- 5–10 статей з вебу (зберегти як .txt/.md)
- Вільнодоступні PDF-звіти
- Сторінки Wikipedia (зберегти як текст)

*Рекомендовано 10–20 документів. Тема на вибір (ринок EV, хмарні сервіси, fintech тощо).*

**Де брати звіти та дані:**
- [CB Insights Research](https://www.cbinsights.com/research/) — безкоштовні звіти по tech-ринках
- [Statista](https://www.statista.com/) — статистика та інфографіка (free tier)
- [Deloitte Insights](https://www.deloitte.com/us/en/insights.html) — індустріальні огляди та тренди

## Взаємодія між агентами

*LangGraph: StateGraph з Evaluator-Optimizer loop (Analyst ↔ Critic). Command API для routing від Critic назад до Analyst. Лічильник ітерацій у state.*

| Від | Кому | Що передається (structured output) |
|-----|------|-----------------------------------|
| User | Analyst | Тема та скоуп (topic, scope, focus_areas[]) |
| Analyst | Critic | DraftReport |
| Critic | Analyst | CriticFeedback (verdict=NEEDS_REVISION) — макс. 5 ітерацій |
| Analyst | Critic | Оновлений DraftReport + changes_made[] |
| Critic | Compiler | DraftReport (verdict=APPROVED) |
| Compiler | User | FinalReport |

## Workflow (LangGraph)

1. **START → Analyst:** тема та скоуп.
2. **Analyst** збирає дані (DuckDuckGo + RAG), формує DraftReport. Ключова вимога: `sources` у DraftReport змушує вказувати джерела, а не генерувати факти з повітря.
3. **Analyst → Critic:** передача DraftReport.
4. **Critic** аналізує (`with_structured_output` → CriticFeedback). Роль devil's advocate: навмисно шукає слабкі місця, упередженість, необґрунтовані твердження.
5. **Conditional edge (Command):** `verdict=NEEDS_REVISION` і `iteration < 5` → Analyst з payload (`issues`, `missing_perspectives`). Інакше → Compiler.
6. **Compiler** формує FinalReport за Pydantic-схемою. Окремий агент, бо задача інша: не генерувати контент, а структурувати затверджений матеріал.
7. **Compiler → END:** фінальний звіт зберігається як `.md`-файл.

## Опціональні функції (бонус)

Список не вичерпний — можна запропонувати власні розширення:

**Додаткові інтеграції (MCP-сервери та API)**
- Wikipedia API — фонова інформація (історія компанії, географія ринку, визначення термінів).
- yfinance — фінансові дані Yahoo Finance.
- NewsAPI — пошук новин за ключовими словами.
- [Google Drive MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive) — збереження звітів у Google Docs для спільного доступу.
- [Notion MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/notion) — ведення бази досліджень у Notion (аналітичні команди часто зберігають research notes у Notion).
- [Brave Search MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/brave-search) — альтернатива DuckDuckGo з доступом до Brave Search API.
- Будь-які інші існуючі MCP-сервери на власний розсуд.

## Моніторинг та тестування (обов'язково)

### Langfuse або LangSmith

Підключити один з сервісів моніторингу до всього pipeline. Кожен виклик LLM (Analyst, Critic, Compiler) має логуватися з:
- Input/output кожного агента
- Latency та кількість токенів
- Metadata: назва агента, номер ітерації Analyst↔Critic, session ID

**Навіщо:** Коли Critic повертає звіт на доопрацювання, потрібно бачити, що саме Analyst змінив — чи враховано feedback, чи проігноровано. Без trace-ів цикл Analyst↔Critic — чорна скринька. Моніторинг також дозволяє порівнювати різні теми: на яких ринках система працює добре, а на яких Critic постійно відхиляє звіти.

### Тести через LLM-as-a-Judge

Написати автоматизовані тести, які оцінюють якість роботи компонентів системи. Кожен тест — це окремий LLM-виклик з критеріями оцінки та тестовими даними.

**Мінімальні тести:**

| Що тестується | Критерій | Приклад тестового сценарію |
|--------------|----------|--------------------------|
| **Analyst** | Звіт підкріплений джерелами, findings конкретні (не generic) | Тема: «ринок EV у Європі 2025» → Judge перевіряє, що findings містять конкретні дані, а не загальні фрази типу «ринок зростає» |
| **Critic** | Знаходить реальні слабкості, не пропускає необґрунтовані твердження | Подати звіт з навмисними bias (тільки позитивні дані) та без джерел → Judge перевіряє, що Critic виявив однобокість |
| **Compiler** | Фінальний звіт має всі обов'язкові секції, executive summary точно відображає findings | Передати approved DraftReport → Judge перевіряє, що FinalReport структурований та не втратив ключову інформацію |
| **End-to-end** | Звіт відповідає початковому запиту (topic + scope) | Повний run → Judge оцінює релевантність, повноту, баланс точок зору |

**Навіщо:** LLM-as-a-Judge дозволяє формалізувати суб'єктивні критерії якості (повнота, баланс, наявність джерел) і перевіряти їх автоматично. Особливо важливо для Critic: без тестів зміна промпту може перетворити його з devil's advocate на yes-man.

## Що здавати

- Вихідний код у Git-репозиторії.
- Записане демо роботи системи (відео або GIF).
- README з діаграмою архітектури, інструкцією запуску та прикладами використання.
- Скріншоти або посилання на dashboard Langfuse/LangSmith з прикладами traces.
- Тести (LLM-as-a-Judge) з результатами запуску.
