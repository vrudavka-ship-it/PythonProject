# Конвеєр створення контенту

## Опис

Мультиагентна система для створення контенту для блогу або соцмереж. Планує, пише та перевіряє якість перед публікацією.

## Архітектурний патерн

**Основний патерн:** комбінація двох патернів Anthropic: Prompt Chaining (Strategist → Writer — лінійний pipeline з HITL gate між ними) + Evaluator-Optimizer (Writer ↔ Editor — цикл генерації та оцінки якості).

**Тип взаємодії:** кооперативна — всі агенти працюють на спільну мету (якісний контент). Editor виконує роль Reviewer (Assurance), як у патерні Planner–Coder–Reviewer.

## Агенти та мінімальні інструменти

**Content Strategist** (Planning)
- Роль: отримує бриф, досліджує тему, створює контент-план
- Інструменти: DuckDuckGo Search (тренди, конкуренти), RAG (style guide та приклади контенту)

**Writer** (Execution)
- Роль: пише статтю/пост за планом, може шукати додаткові факти
- Інструменти: DuckDuckGo Search (факти, статистика), File System tool (збереження готового контенту)

**Editor** (Assurance)
- Роль: рев'ює контент (tone, фактична точність, структура, відповідність плану), повертає structured feedback або затверджує
- Інструменти: DuckDuckGo Search (fact-check), LLM structured output (EditFeedback)

### Навіщо кожен інструмент (real-world motivation)

1. **DuckDuckGo Search (Strategist, Writer, Editor)**: Strategist вивчає тренди та конкурентів перед плануванням, Writer шукає факти та статистику для підтвердження тез, Editor верифікує ключові твердження (fact-check).
2. **RAG (Strategist)**: Контент-команди працюють із brand book: tone of voice, заборонені слова, приклади «хороших» текстів, правила для різних каналів. RAG дозволяє Strategist шукати по цих внутрішніх документах і враховувати стиль бренду вже на етапі планування — не планувати жартівливий tone для бренду з серйозним голосом.
3. **File System tool (Writer)**: Writer зберігає фінальний затверджений контент як `.md`-файл — готовий артефакт для передачі в CMS, WordPress або клієнту. Проміжні дані (план, чернетки, feedback) передаються через LangGraph state; файлова система — тільки для кінцевого результату.
4. **LLM structured output (Editor)**: Editor повертає `EditFeedback` з числовими оцінками (tone_score, accuracy_score, structure_score) та бінарним вердиктом — це дозволяє conditional routing у графі. Structured output забезпечує машинно-зчитуваний feedback замість вільного тексту.

## Structured Output контракти (Pydantic)

- **ContentPlan:** `outline: list[str], keywords: list[str], key_messages: list[str], target_audience: str, tone: str`
- **DraftContent:** `content: str, word_count: int, keywords_used: list[str]`
- **EditFeedback:** `verdict: Literal["APPROVED","REVISION_NEEDED"], issues: list[str], tone_score: float, accuracy_score: float, structure_score: float`

## Підготовка даних для RAG

Студент створює style guide та приклади для вигаданого бренду:

- Style guide: tone of voice, аудиторія, заборонені/рекомендовані формулювання (1–2 стор.)
- 5–10 прикладів "хороших" постів/статей
- Опис бренду: місія, продукт, конкурентні переваги (1 стор.)

*Бренд може бути вигаданим.*

**Приклади style guides для натхнення:**
- [Mailchimp Content Style Guide](https://styleguide.mailchimp.com/) — один з найкращих публічних style guides
- [Microsoft Writing Style Guide](https://learn.microsoft.com/en-us/style-guide/welcome/) — стиль технічного контенту
- Як приклади контенту можна взяти реальні блог-пости будь-якого бренду (Buffer, HubSpot, Stripe)

## Взаємодія між агентами

*LangGraph: Prompt Chaining (Strategist → HITL gate → Writer) + Evaluator-Optimizer loop (Writer ↔ Editor). Command API для routing від Editor назад до Writer.*

| Від | Кому | Що передається (structured output)                                  |
|-----|------|---------------------------------------------------------------------|
| User | Strategist | Бриф (topic, target_audience, channel, tone, word_count)            |
| Strategist | User | ContentPlan на затвердження (Human-in-the-Loop gate)                |
| User | Strategist | Feedback (якщо план не затверджено) → Strategist переробляє план    |
| Strategist | Writer | Затверджений ContentPlan                                            |
| Writer | Editor | DraftContent                                                        |
| Editor | Writer | EditFeedback (verdict=REVISION_NEEDED, scores{}) — макс. 5 ітерації |
| Editor | User | EditFeedback (verdict=APPROVED) + фінальний контент                 |

## Workflow (LangGraph)

1. **START → Strategist:** бриф від користувача.
2. **Strategist** досліджує (DuckDuckGo + RAG), формує ContentPlan.
3. **HITL gate:** користувач затверджує план або повертає з feedback → Strategist переробляє (цикл до затвердження). Потрібен, бо писати контент за неправильним планом — марна витрата токенів.
4. **Strategist → Writer:** затверджений ContentPlan.
5. **Writer** створює DraftContent.
6. **Writer → Editor:** передача чернетки.
7. **Editor** оцінює (`with_structured_output` → EditFeedback).
8. **Conditional edge (Command):** `verdict=REVISION_NEEDED` і `iteration < 5` → Writer з payload (попередній контент + зауваження). Інакше → END. Command API потрібен, бо Writer має отримати і контент, і feedback, а не просто перезапуститися.

## Опціональні функції (бонус)

Список не вичерпний — можна запропонувати власні розширення:

**Додаткові інтеграції (MCP-сервери та API)**
- Google Trends (pytrends) — аналіз популярності пошукових запитів.
- [Notion MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/notion) — збереження планів та статей у Notion (контент-команди часто ведуть editorial calendar у Notion).
- [Google Drive MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/gdrive) — збереження контенту в Google Docs для спільної роботи з клієнтом.
- [Slack MCP](https://github.com/modelcontextprotocol/servers/tree/main/src/slack) — нотифікація команди про готовий контент або запит на рев'ю.
- Будь-які інші існуючі MCP-сервери на власний розсуд.

## Моніторинг та тестування (обов'язково)

### Langfuse або LangSmith

Підключити один з сервісів моніторингу до всього pipeline. Кожен виклик LLM (Strategist, Writer, Editor) має логуватися з:
- Input/output кожного агента
- Latency та кількість токенів
- Metadata: назва агента, номер ітерації, session ID

**Навіщо:** Без моніторингу неможливо зрозуміти, чому система згенерувала поганий контент: слабкий план від Strategist, порушення tone of voice у Writer, чи пропущена помилка Editor. Langfuse/LangSmith дозволяють побачити весь trace від брифу до фінального тексту, знайти bottleneck і порівняти якість між запусками.

### Тести через LLM-as-a-Judge

Написати автоматизовані тести, які оцінюють якість роботи компонентів системи. Кожен тест — це окремий LLM-виклик з критеріями оцінки та тестовими даними.

**Мінімальні тести:**

| Що тестується | Критерій | Приклад тестового сценарію |
|--------------|----------|--------------------------|
| **Strategist** | План відповідає брифу: враховує target audience, tone, channel | Бриф: «пост для LinkedIn про AI у медицині, професійний тон» → Judge перевіряє, що план не містить casual tone, мемів тощо |
| **Writer** | Контент відповідає плану: покриває всі пункти outline, використовує keywords | План з 5 пунктами outline → Judge перевіряє, що всі 5 розкриті у тексті |
| **Editor** | Feedback конкретний і actionable, scores відповідають реальній якості | Подати свідомо поганий текст (off-topic, wrong tone) → Judge перевіряє, що Editor виявив проблеми та поставив низькі scores |
| **End-to-end** | Фінальний контент відповідає початковому брифу | Повний run від брифу до approved контенту → Judge оцінює відповідність, якість, tone |

**Навіщо:** LLM-as-a-Judge — еквівалент тестів для LLM-систем: окрема модель оцінює output за визначеними критеріями. Дозволяє виявляти регресії при зміні промптів та гарантувати мінімальну якість. Без тестів зміна одного промпту може зламати весь pipeline непомітно.

## Що здавати

- Вихідний код у Git-репозиторії.
- Записане демо роботи системи (відео або GIF).
- README з діаграмою архітектури, інструкцією запуску та прикладами використання.
- Скріншоти або посилання на dashboard Langfuse/LangSmith з прикладами traces.
- Тести (LLM-as-a-Judge) з результатами запуску.
