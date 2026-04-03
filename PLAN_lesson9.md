# План реалізації homework-lesson-9

## Мета
Перевести мультиагентну систему з hw8 на архітектуру з протоколами комунікації:
- **MCP** (FastMCP) — для tools
- **ACP** (acp-sdk) — для agent-to-agent комунікації

---

## Нові залежності

```bash
pip install fastmcp==3.2.0 acp-sdk==1.0.3 uvicorn==0.35.0
```

Додати в `requirements.txt`.

---

## Нові файли (треба створити)

| Файл | Що робить |
|---|---|
| `mcp_servers/search_mcp.py` | FastMCP сервер, порт 8901: web_search, read_url, knowledge_search + resource://knowledge-base-stats |
| `mcp_servers/report_mcp.py` | FastMCP сервер, порт 8902: save_report + resource://output-dir |
| `mcp_servers/__init__.py` | package marker |
| `acp_server.py` | ACP сервер, порт 8903: planner, researcher, critic агенти |
| `mcp_utils.py` | mcp_tools_to_langchain() — конвертація MCP tools у LangChain format |
| `main.py` | REPL з HITL (замінює main_supervisor.py) |

## Файли що змінюються

| Файл | Що змінюється |
|---|---|
| `supervisor.py` | sub-agent @tool обгортки → виклики через acp_sdk.client.Client; save_report → через ReportMCP клієнт |
| `requirements.txt` | + fastmcp, acp-sdk, uvicorn |
| `config.py` | + порти MCP/ACP серверів як константи |

## Файли без змін

- `schemas.py` — ResearchPlan, CritiqueResult
- `tools.py` — бізнес-логіка web_search, read_url, knowledge_search, save_report
- `retriever.py`, `ingest.py` — RAG pipeline
- `agents/` — system prompts можна перевикористати (але агенти тепер живуть в acp_server.py)

---

## Покроковий план

### Крок 1 — Встановлення залежностей
- [ ] `pip install fastmcp==3.2.0 acp-sdk==1.0.3 uvicorn==0.35.0`
- [ ] Перевірити що імпортуються без помилок
- [ ] Додати в requirements.txt

### Крок 2 — mcp_utils.py
- [ ] Скопіювати `mcp_tools_to_langchain()` з лекції 9
- [ ] Адаптувати під наш проєкт (коментарі українською)

### Крок 3 — mcp_servers/search_mcp.py (порт 8901)
- [ ] `FastMCP(name="SearchMCP")`
- [ ] `@mcp_server.tool` для `web_search` — делегує до `tools.web_search()`
- [ ] `@mcp_server.tool` для `read_url` — делегує до `tools.read_url()`
- [ ] `@mcp_server.tool` для `knowledge_search` — делегує до `tools.knowledge_search()`
- [ ] `@mcp_server.resource("resource://knowledge-base-stats")` — кількість документів, дата оновлення
- [ ] `if __name__ == "__main__"` — запуск через `mcp_server.run(transport="streamable-http", port=8901)`

### Крок 4 — mcp_servers/report_mcp.py (порт 8902)
- [ ] `FastMCP(name="ReportMCP")`
- [ ] `@mcp_server.tool` для `save_report` — делегує до `tools.save_report()`
- [ ] `@mcp_server.resource("resource://output-dir")` — шлях і список збережених звітів
- [ ] `if __name__ == "__main__"` — запуск на порт 8902

### Крок 5 — acp_server.py (порт 8903)
- [ ] `Server()` з acp-sdk
- [ ] `@acp_server.agent(name="planner")` handler:
  - async підключення до SearchMCP через `fastmcp.Client`
  - `mcp_tools_to_langchain()` → LangChain tools
  - `create_agent` з PLANNER_SYSTEM_PROMPT
  - Повертає `Message(role="agent", parts=[MessagePart(content=...)])`
  - parse_research_plan() на результат (без response_format — той самий баг)
- [ ] `@acp_server.agent(name="researcher")` handler — аналогічно з RESEARCH_SYSTEM_PROMPT
- [ ] `@acp_server.agent(name="critic")` handler — аналогічно з CRITIC_SYSTEM_PROMPT + parse_critique_result()
- [ ] `if __name__ == "__main__"` — `server.run(port=8903)`

### Крок 6 — supervisor.py (переписати)
- [ ] Прибрати прямі виклики `get_planner_agent()`, `get_research_agent()`, `get_critic_agent()`
- [ ] `@tool plan()` → `acp_sdk.client.Client.run_sync(agent="planner", ...)`
- [ ] `@tool research()` → `acp_sdk.client.Client.run_sync(agent="researcher", ...)`
- [ ] `@tool critique()` → `acp_sdk.client.Client.run_sync(agent="critic", ...)`
- [ ] `@tool save_report()` → `fastmcp.Client.call_tool("save_report", ...)` на ReportMCP
- [ ] HITL залишається — `HumanInTheLoopMiddleware(interrupt_on={"save_report": True})`
- [ ] `InMemorySaver` залишається
- [ ] Вирішити async/sync проблему: supervisor sync → ACP async (через `asyncio.run()`)

### Крок 7 — config.py
- [ ] Додати константи портів:
  ```python
  MCP_SEARCH_PORT = 8901
  MCP_REPORT_PORT = 8902
  ACP_PORT = 8903
  MCP_SEARCH_URL = f"http://127.0.0.1:{MCP_SEARCH_PORT}/mcp"
  MCP_REPORT_URL = f"http://127.0.0.1:{MCP_REPORT_PORT}/mcp"
  ACP_BASE_URL = f"http://127.0.0.1:{ACP_PORT}"
  ```

### Крок 8 — main.py
- [ ] Або перейменувати main_supervisor.py → main.py
- [ ] Або створити новий main.py що імпортує з supervisor
- [ ] HITL flow залишається без змін

### Крок 9 — Тестування по частинах
- [ ] Запустити search_mcp.py окремо, протестувати через fastmcp.Client
- [ ] Запустити report_mcp.py окремо, протестувати
- [ ] Запустити acp_server.py, протестувати кожного агента через acp-sdk client
- [ ] Запустити повний pipeline: search_mcp + report_mcp + acp_server + main.py

---

## Архітектура запуску

```bash
# Термінал 1
.venv/bin/python3 mcp_servers/search_mcp.py   # порт 8901

# Термінал 2
.venv/bin/python3 mcp_servers/report_mcp.py   # порт 8902

# Термінал 3
.venv/bin/python3 acp_server.py               # порт 8903

# Термінал 4
.venv/bin/python3 main.py                     # REPL
```

---

## Ризики і питання

1. **Async/sync mix** — supervisor (`create_agent`) sync, ACP client async.
   Рішення: `asyncio.run()` всередині кожного `@tool` або перевести supervisor на async.

2. **response_format баг** — домашка знову просить response_format для Planner і Critic.
   Рішення: так само як в hw8 — без response_format, parse_research_plan() / parse_critique_result().

3. **MCP клієнт async** — `fastmcp.Client` async context manager.
   Рішення: `asyncio.run(async_call())` в sync supervisor tools.

4. **acp-sdk API** — перевірити актуальний API `run_sync` vs `run_async` в версії 1.0.3.
