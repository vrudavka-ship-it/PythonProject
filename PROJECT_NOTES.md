# CLAUDE_MEMORY.md
> Спільна пам'ять Vasyl + Claude. Записуємо думки, рішення, ідеї — щоб не втрачати контекст між сесіями.

---

## Поточний стан проєкту (2026-04-10)

- **Урок 5** — виконано, змержено в master, тег `homework-lesson-5` є (коміт `72fe3f0`)
- **Урок 6** — лекція прочитана (оркестрація: LangGraph, CrewAI, Smolagents, OpenAI Agents SDK). Домашки немає.
- **Урок 7** — лекція прочитана (Дизайн взаємодії агентів). Домашки не було.
- **Урок 8** — виконано, змержено в master, тег є.
- **Урок 9** — виконано, змержено в master, тег є.
- **Урок 10** — виконано (гілка `homework-lesson-10`, коміт `2ba53ac`), змержено в master, тег `homework-lesson-10` є. DeepEval тести: golden dataset (15 прикладів), component tests, tool correctness, e2e.

---

## Архітектурні рішення і чому

### hw8: Subagents-as-Tools (LangGraph + LangChain)
- Вибір: `create_agent` з `HumanInTheLoopMiddleware` і `InMemorySaver`
- Sub-агенти = `@tool` обгортки навколо прямих Python викликів
- `response_format` для Planner/Critic прибраний — баг gpt-4o-mini: з `response_format + tools` повертає схему замість значень. Замінили на regex parse з вільного тексту.

### hw9: MCP + ACP поверх hw8
- SearchMCP (8901): web_search, read_url, knowledge_search — один для всіх трьох ACP агентів
- ReportMCP (8902): save_report — HITL на рівні Supervisor, не MCP
- ACP Server (8903): planner, researcher, critic — `create_agent` + `fastmcp.Client`
- Supervisor: sync tools → `asyncio.run()` → async ACP/MCP клієнти
- Знайдений баг acp-sdk 1.0.3: надсилає bytes без `Content-Type: application/json` → 422. Фікс: `ACPClient(headers={"Content-Type": "application/json"})`

---

## Важливі деталі імплементації

### Чому без response_format (hw8 і hw9)
gpt-4o-mini + `response_format=SomeModel` + `tools=[...]` разом → модель повертає JSON Schema замість значень. Рішення: агент пише JSON в кінці тексту, ми парсимо regex.

### Async/sync mix у Supervisor
`create_agent` — sync контекст. ACP і MCP клієнти — async.
Рішення: `asyncio.run(coro)` всередині кожного `@tool`. Це безпечно бо `supervisor.stream()` — sync, event loop не активний.

### Порядок запуску (hw9)
```bash
.venv/bin/python3 mcp_servers/search_mcp.py   # порт 8901
.venv/bin/python3 mcp_servers/report_mcp.py   # порт 8902
.venv/bin/python3 acp_server.py               # порт 8903
.venv/bin/python3 main.py                     # REPL
```

---

## Відомі баги (не виправлені)

### HITL `edit` flow — `KeyError: 'name'` (2026-04-10)
- **Файл:** `main.py::_build_resume_command`
- **Симптом:** при виборі `edit` у HITL — crash з `KeyError: 'name'`
- **Причина:** ми передаємо `{"edited_action": {"feedback": feedback}}`, а `HumanInTheLoopMiddleware._process_decision` очікує `{"edited_action": {"name": <tool_name>, "args": {...}}}` — повний відредагований tool call
- **Варіанти фіксу:**
  - (A) Показати поточні args і дати редагувати `filename`/`content` окремо, потім скласти правильний `edited_action`
  - (B) Прибрати `edit`, залишити тільки `approve`/`reject`

---

## Правильний патерн для Research Agent

**Subagents-as-Tools** (hw8) → **Subagents-as-Tools over ACP** (hw9)

Ключове застереження (Google Research): для **послідовних задач** мультиагентність **погіршує** результат на 39–70%. Compound reliability: при 95% надійності × 10 кроків = 59.9% успіху. Не переускладнювати!

Evaluator-Optimizer (Critic) — єдине місце де мультиагентність реально виправдана: незалежна верифікація фактів дає якість без великого coordination overhead.
