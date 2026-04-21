"""
FastAPI бекенд для Research Agent Web UI (homework-lesson-13).

Ендпоінти:
  GET  /              → index.html (Web UI)
  GET  /stream        → SSE стрімінг (EventSource у браузері)
  POST /approve       → HITL: схвалення збереження звіту
  POST /reject        → HITL: відхилення збереження звіту
  GET  /sessions      → список сесій для history sidebar
  GET  /sessions/{id} → метадані конкретної сесії

SSE (Server-Sent Events):
- Однонаправлений стрімінг: server → client
- Браузер підключається через EventSource JS API
- Кожне повідомлення: "data: <json>\n\n"
- Аналогія Java: @Produces(MediaType.SERVER_SENT_EVENTS) у JAX-RS

HITL flow через SSE + POST:
  1. SSE подія type="hitl_interrupt" → браузер показує картку approve/reject
  2. Користувач натискає → POST /approve або POST /reject
  3. asyncio.Queue — місток між SSE generator і POST handler
     (черга повідомлень між двома async корутинами)
  4. SSE generator продовжує стрімінг після отримання рішення
"""
import asyncio
import json
import os
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime

# sys.path — додаємо корінь проєкту щоб імпортувати supervisor_local, config тощо
# Аналогія Java: CLASSPATH — де шукати класи
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Встановлюємо env vars до будь-яких LangChain/OpenAI імпортів
from config import settings
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key)
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url)

# Патч OpenAI JSON encoder (surrogate chars fix з hw12)
import json as _json
import re as _re
import openai._utils._json as _openai_json
import openai._base_client as _openai_base_client

def _safe_dumps(obj):
    s = _json.dumps(obj, cls=_openai_json._CustomEncoder,
                    ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return _re.sub(r"[\ud800-\udfff]", "", s).encode("utf-8", errors="ignore")

_openai_json.openapi_dumps = _safe_dumps
_openai_base_client.openapi_dumps = _safe_dumps

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse
from langgraph.types import Command

from app.session_store import setup_sessions_table, save_session, get_sessions, update_report_path


# ─────────────────────────────────────────────────────────────
# In-memory store для HITL queues
# ─────────────────────────────────────────────────────────────

# _hitl_queues — dict: session_id → asyncio.Queue
# Коли SSE generator натикається на __interrupt__, він кладе дані в чергу і чекає рішення.
# POST /approve або /reject кладе рішення в чергу — generator продовжує роботу.
#
# Аналогія Java: ConcurrentHashMap<String, BlockingQueue<Decision>>
# де session_id = ключ, BlockingQueue = asyncio.Queue
_hitl_queues: dict[str, asyncio.Queue] = {}


# ─────────────────────────────────────────────────────────────
# Lifespan — ініціалізація при старті FastAPI
# ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifecycle hook FastAPI.

    Все до yield — startup (як @PostConstruct у Spring).
    Все після yield — shutdown (як @PreDestroy).

    При старті:
    - Ініціалізуємо таблицю research_sessions у Postgres
    - Якщо Postgres недоступний — логуємо warning і продовжуємо
      (локальний запуск без Docker — history sidebar не буде працювати,
       але решта функціональності — так)
    """
    try:
        await setup_sessions_table()
        print("[startup] Postgres connected, sessions table ready")
    except Exception as e:
        print(f"[startup] WARNING: Postgres unavailable ({e}). History disabled.")
    yield


# ─────────────────────────────────────────────────────────────
# FastAPI застосунок
# ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Research Agent Web UI",
    version="1.0.0",
    lifespan=lifespan,
)

# StaticFiles — роздаємо HTML/CSS/JS з директорії app/static/
# Аналогія Java: resources/static/ у Spring Boot
_static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ─────────────────────────────────────────────────────────────
# GET / — головна сторінка
# ─────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index():
    """Повертає index.html — Web UI."""
    html_path = _static_dir / "index.html"
    return HTMLResponse(html_path.read_text(encoding="utf-8"))


# ─────────────────────────────────────────────────────────────
# GET /stream — SSE стрімінг виконання агента
# ─────────────────────────────────────────────────────────────

@app.get("/stream")
async def stream(query: str = Query(..., description="Research query")):
    """
    SSE endpoint — стрімить події виконання агента.

    Клієнт підключається через EventSource:
        const es = new EventSource(`/stream?query=What+is+RAG`)

    Типи подій (event type у SSE):
      agent_message  — повідомлення від агента (text content)
      tool_call      — агент викликає tool (назва + аргументи)
      tool_result    — результат виконання tool
      hitl_interrupt — потрібне схвалення (HITL картка)
      hitl_resolved  — HITL завершено (approved/rejected)
      done           — виконання завершено
      error          — помилка

    Формат SSE повідомлення:
      event: <type>\n
      data: <json>\n
      \n
    """
    session_id = str(uuid.uuid4())

    # Зберігаємо метадані сесії у Postgres
    await save_session(session_id, query)

    # Створюємо чергу для HITL рішень
    # asyncio.Queue — thread-safe черга для async коду
    # Аналогія Java: LinkedBlockingQueue (але async, не blocking)
    hitl_queue: asyncio.Queue = asyncio.Queue()
    _hitl_queues[session_id] = hitl_queue

    async def event_generator():
        """
        Async generator — генерує SSE події.

        yield dict(event=..., data=...) — sse_starlette перетворює в SSE формат.

        Supervisor.stream() — sync generator (LangGraph).
        Ми запускаємо його в executor щоб не блокувати event loop.
        """
        try:
            # Перша подія — session_id щоб клієнт знав свій ID для /approve, /reject
            yield {
                "event": "session_start",
                "data": json.dumps({"session_id": session_id, "query": query}),
            }

            # Запускаємо supervisor в окремому потоці (він sync).
            # asyncio.to_thread() — запускає sync функцію в thread pool executor.
            # Аналогія Java: CompletableFuture.supplyAsync(() -> blockingCall(), executor)
            await asyncio.to_thread(
                _run_supervisor_sync,
                query=query,
                session_id=session_id,
                hitl_queue=hitl_queue,
                event_queue=asyncio.get_event_loop().create_future(),  # placeholder
            )

            # Замість return — використовуємо Queue для подій між потоками
            # Дивись _run_supervisor_sync нижче

        except Exception as exc:
            yield {
                "event": "error",
                "data": json.dumps({"message": str(exc)}),
            }
        finally:
            # Очищаємо HITL queue після завершення сесії
            _hitl_queues.pop(session_id, None)

    # Реалізація через event_queue (правильний підхід — Queue між потоками)
    # event_queue — asyncio.Queue для передачі подій з sync thread у async generator
    event_queue: asyncio.Queue = asyncio.Queue()

    async def proper_event_generator():
        """Generator що читає з event_queue і стрімить SSE."""
        # Перша подія — session_id
        yield {
            "event": "session_start",
            "data": json.dumps({"session_id": session_id, "query": query}),
        }

        # Запускаємо supervisor в окремому потоці (бо він sync)
        loop = asyncio.get_event_loop()
        task = loop.run_in_executor(
            None,  # default ThreadPoolExecutor
            lambda: _run_supervisor_sync(query, session_id, hitl_queue, event_queue, loop),
        )

        # Читаємо події з черги поки не отримаємо sentinel None (кінець стріму)
        while True:
            try:
                # Чекаємо наступну подію з черги (з таймаутом щоб не зависнути)
                event = await asyncio.wait_for(event_queue.get(), timeout=120.0)
                if event is None:
                    break  # sentinel — supervisor завершив роботу
                yield event
            except asyncio.TimeoutError:
                yield {"event": "error", "data": json.dumps({"message": "Timeout"})}
                break

        # Чекаємо завершення потоку (можуть бути exceptions)
        try:
            await task
        except Exception as exc:
            yield {"event": "error", "data": json.dumps({"message": str(exc)})}

        yield {"event": "done", "data": json.dumps({"session_id": session_id})}

        # Очищаємо HITL queue
        _hitl_queues.pop(session_id, None)

    return EventSourceResponse(proper_event_generator())


def _run_supervisor_sync(
    query: str,
    session_id: str,
    hitl_queue: asyncio.Queue,
    event_queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Запускає supervisor.stream() у синхронному потоці і кладе події у event_queue.

    Це sync функція яка виконується у ThreadPoolExecutor.
    event_queue — bridge між sync потоком і async SSE generator.
    loop.call_soon_threadsafe() — безпечна передача подій у event loop з іншого потоку.

    Аналогія Java: Runnable що кладе результати у BlockingQueue
    яку читає async CompletableFuture chain.
    """

    def put_event(event: dict | None):
        """Thread-safe: кладе подію у async queue з sync потоку."""
        # call_soon_threadsafe — єдиний безпечний спосіб взаємодіяти з event loop з іншого потоку
        # Аналогія Java: Platform.runLater() у JavaFX або SwingUtilities.invokeLater()
        loop.call_soon_threadsafe(event_queue.put_nowait, event)

    def get_hitl_decision() -> str:
        """
        Блокуючо чекає рішення від HITL queue.

        Sync потік блокується поки async POST /approve або /reject не покладе рішення.
        Аналогія Java: future.get() — блокує до завершення.
        """
        import concurrent.futures
        future = concurrent.futures.Future()

        async def _await_queue():
            decision = await hitl_queue.get()
            future.set_result(decision)

        loop.call_soon_threadsafe(asyncio.ensure_future, _await_queue())
        return future.result(timeout=300)  # 5 хвилин таймаут

    try:
        # Lazy import supervisor_local (hw8 архітектура — без ACP/MCP серверів)
        # supervisor_local використовує InMemorySaver.
        # У production — замінити на AsyncPostgresSaver.
        from supervisor_local import get_supervisor

        supervisor = get_supervisor()

        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": 40,
        }

        for step in supervisor.stream(
            {"messages": [{"role": "user", "content": query}]},
            config,
            stream_mode="updates",
        ):
            if "__interrupt__" in step:
                # HITL interrupt — витягуємо деталі і відправляємо у браузер
                interrupts = step["__interrupt__"]
                interrupt_value = interrupts[0].value

                filename = ""
                content = ""
                for req in interrupt_value.get("action_requests", []):
                    args = req.get("args") or req.get("tool_input", {})
                    filename = args.get("filename", "report.md")
                    content = args.get("content", "")

                # Відправляємо подію hitl_interrupt у браузер
                put_event({
                    "event": "hitl_interrupt",
                    "data": json.dumps({
                        "filename": filename,
                        "preview": content[:1000],
                        "content": content,
                        "content_length": len(content),
                    }),
                })

                # Чекаємо рішення від POST /approve або /reject
                decision = get_hitl_decision()

                if decision == "approve":
                    put_event({
                        "event": "hitl_resolved",
                        "data": json.dumps({"decision": "approve", "filename": filename}),
                    })
                    resume_data = {"decisions": [{"type": "approve"}]}
                else:  # reject
                    put_event({
                        "event": "hitl_resolved",
                        "data": json.dumps({"decision": "reject"}),
                    })
                    resume_data = {"decisions": [{"type": "reject", "message": "User rejected"}]}

                # Відновлюємо граф після HITL
                for resume_step in supervisor.stream(
                    Command(resume=resume_data),
                    config,
                    stream_mode="updates",
                ):
                    _process_step(resume_step, put_event, session_id, loop, decision == "approve")

            else:
                _process_step(step, put_event, session_id, loop, False)

    except Exception as exc:
        put_event({
            "event": "error",
            "data": json.dumps({"message": f"{type(exc).__name__}: {exc}"}),
        })
    finally:
        # Sentinel — кінець стріму
        put_event(None)


def _process_step(
    step: dict,
    put_event,
    session_id: str,
    loop: asyncio.AbstractEventLoop,
    after_approve: bool,
) -> None:
    """
    Обробляє один крок supervisor.stream() і перетворює у SSE події.

    LangGraph stream_mode="updates" повертає dict: {node_name: node_output}
    node_output.messages — список BaseMessage (AIMessage, ToolMessage, HumanMessage)
    """
    for node_name, node_output in step.items():
        if not isinstance(node_output, dict):
            continue

        for message in node_output.get("messages", []):
            msg_type = type(message).__name__  # AIMessage, ToolMessage, HumanMessage

            if msg_type == "AIMessage":
                # Відповідь агента — text content
                content = getattr(message, "content", "")
                if content:
                    put_event({
                        "event": "agent_message",
                        "data": json.dumps({
                            "node": node_name,
                            "content": str(content),
                        }),
                    })

                # Tool calls — що агент збирається зробити
                tool_calls = getattr(message, "tool_calls", [])
                for tc in tool_calls:
                    put_event({
                        "event": "tool_call",
                        "data": json.dumps({
                            "tool": tc.get("name", ""),
                            "args": tc.get("args", {}),
                            "node": node_name,
                        }),
                    })

            elif msg_type == "ToolMessage":
                # Результат виконання tool
                content = getattr(message, "content", "")
                tool_name = getattr(message, "name", "")

                # save_report після approve — зберігаємо шлях у БД
                if tool_name == "save_report" and after_approve and content:
                    async def _update_path():
                        await update_report_path(session_id, str(content))
                    loop.call_soon_threadsafe(asyncio.ensure_future, _update_path())

                put_event({
                    "event": "tool_result",
                    "data": json.dumps({
                        "tool": tool_name,
                        "result": str(content)[:500],  # перші 500 символів
                        "node": node_name,
                    }),
                })


# ─────────────────────────────────────────────────────────────
# POST /approve — HITL approve
# ─────────────────────────────────────────────────────────────

@app.post("/approve")
async def approve(body: dict):
    """
    Схвалення HITL операції (збереження звіту).

    Body: {"session_id": "<uuid>"}

    Кладе "approve" у HITL queue сесії.
    SSE generator прочитає рішення і продовжить виконання.
    """
    session_id = body.get("session_id")
    if not session_id or session_id not in _hitl_queues:
        raise HTTPException(status_code=404, detail="Session not found or no pending HITL")

    await _hitl_queues[session_id].put("approve")
    return {"status": "ok", "decision": "approve"}


# ─────────────────────────────────────────────────────────────
# POST /reject — HITL reject
# ─────────────────────────────────────────────────────────────

@app.post("/reject")
async def reject(body: dict):
    """
    Відхилення HITL операції.

    Body: {"session_id": "<uuid>"}
    """
    session_id = body.get("session_id")
    if not session_id or session_id not in _hitl_queues:
        raise HTTPException(status_code=404, detail="Session not found or no pending HITL")

    await _hitl_queues[session_id].put("reject")
    return {"status": "ok", "decision": "reject"}


# ─────────────────────────────────────────────────────────────
# GET /sessions — список сесій для history sidebar
# ─────────────────────────────────────────────────────────────

@app.get("/sessions")
async def list_sessions(limit: int = Query(default=20, le=100)):
    """
    Повертає список останніх сесій.

    Response: list of {session_id, query, created_at, report_path}
    Якщо Postgres недоступний — повертає порожній список (не 500).
    """
    try:
        sessions = await get_sessions(limit)
    except Exception:
        return JSONResponse([])

    # datetime не серіалізується в JSON автоматично — конвертуємо в ISO string
    # Аналогія Java: LocalDateTime.toString() або JsonSerializer<LocalDateTime>
    for s in sessions:
        if isinstance(s.get("created_at"), datetime):
            s["created_at"] = s["created_at"].isoformat()

    return JSONResponse(sessions)


# ─────────────────────────────────────────────────────────────
# GET /sessions/{session_id} — деталі сесії
# ─────────────────────────────────────────────────────────────

@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Повертає метадані однієї сесії."""
    sessions = await get_sessions(100)
    for s in sessions:
        if s["session_id"] == session_id:
            if isinstance(s.get("created_at"), datetime):
                s["created_at"] = s["created_at"].isoformat()
            return JSONResponse(s)
    raise HTTPException(status_code=404, detail="Session not found")


# ─────────────────────────────────────────────────────────────
# GET /reports/{filename} — завантаження звіту
# ─────────────────────────────────────────────────────────────

@app.get("/reports/{filename}")
async def download_report(filename: str):
    """Повертає файл звіту для завантаження."""
    output_dir = Path(settings.output_dir)
    filepath = output_dir / filename

    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Report not found")

    # Перевіряємо що шлях не виходить за межі output_dir (path traversal protection)
    try:
        filepath.resolve().relative_to(output_dir.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")

    return FileResponse(
        path=str(filepath),
        media_type="text/markdown",
        filename=filename,
    )
