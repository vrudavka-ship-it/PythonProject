"""
Session Store — зберігає метадані сесій у Postgres.

Чому окрема таблиця?
- LangGraph зберігає STATE (повідомлення, tool calls) у langgraph_checkpoints
- Нам потрібна також METADATA: назва сесії, запит, час — для history sidebar
- Окрема таблиця `research_sessions` — простий і контрольований підхід

Аналогія Java:
- asyncpg.Connection = java.sql.Connection
- Ми використовуємо raw SQL (не ORM) — для простоти і прозорості
"""
import asyncio
import os
from datetime import datetime

import asyncpg

# DATABASE_URL для asyncpg — без "+asyncpg" prefix (asyncpg читає нативний формат)
# Формат: postgresql://user:password@host:port/dbname
_DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://research:research@localhost:5432/research_agent",
).replace("postgresql+asyncpg://", "postgresql://")

# _pool — пул з'єднань asyncpg.
# Аналогія Java: HikariCP connection pool — не створюємо нове з'єднання на кожен запит.
_pool: asyncpg.Pool | None = None


async def _get_pool() -> asyncpg.Pool:
    """Повертає або створює пул з'єднань asyncpg."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(_DB_URL, min_size=2, max_size=10)
    return _pool


async def setup_sessions_table() -> None:
    """
    Створює таблицю research_sessions якщо вона не існує.

    Викликається при startup FastAPI (разом з LangGraph setup()).
    CREATE TABLE IF NOT EXISTS — ідемпотентна операція (безпечно запускати повторно).

    Схема:
      session_id  — UUID рядка LangGraph (thread_id)
      query       — початковий запит користувача
      created_at  — час початку сесії
      report_path — шлях до збереженого звіту (null якщо ще не збережено)
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # async with pool.acquire() — отримуємо з'єднання з пулу
        # Аналогія Java: try (Connection conn = dataSource.getConnection()) {}
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS research_sessions (
                session_id  TEXT PRIMARY KEY,
                query       TEXT NOT NULL,
                created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                report_path TEXT
            )
        """)


async def save_session(session_id: str, query: str) -> None:
    """Зберігає нову сесію в БД."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        # INSERT ... ON CONFLICT DO NOTHING — ідемпотентно (якщо сесія вже є — пропускаємо)
        await conn.execute(
            """
            INSERT INTO research_sessions (session_id, query)
            VALUES ($1, $2)
            ON CONFLICT (session_id) DO NOTHING
            """,
            session_id, query,
        )


async def update_report_path(session_id: str, report_path: str) -> None:
    """Оновлює шлях до звіту після успішного збереження."""
    pool = await _get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE research_sessions SET report_path = $1 WHERE session_id = $2",
            report_path, session_id,
        )


async def get_sessions(limit: int = 20) -> list[dict]:
    """
    Повертає список останніх сесій для history sidebar.

    Повертає list[dict] — список рядків таблиці як словники.
    Аналогія Java: List<Map<String, Object>> з ResultSet.
    """
    pool = await _get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT session_id, query, created_at, report_path
            FROM research_sessions
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        # Record → dict: asyncpg.Record підтримує dict(row)
        return [dict(row) for row in rows]
