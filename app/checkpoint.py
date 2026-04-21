"""
Postgres checkpoint для LangGraph — замінює InMemorySaver.

InMemorySaver (hw8/hw9):
- зберігає стан тільки в RAM
- втрачається при перезапуску процесу
- не підходить для production і Web UI

AsyncPostgresSaver (hw13):
- зберігає стан у Postgres (таблиці langgraph_*)
- персистентно між перезапусками
- дозволяє відновлювати сесії з history sidebar

Аналогія Java:
- InMemorySaver = HashMap<String, State> в пам'яті
- AsyncPostgresSaver = JPA/Hibernate + Postgres (стан зберігається на диску)

setup_checkpointer() — ініціалізує таблиці в Postgres при першому запуску.
Аналогія Java: Liquibase/Flyway міграція при старті Spring Boot.
"""
import os
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


# DATABASE_URL — рядок підключення до Postgres.
# asyncpg — async драйвер (набагато швидший за psycopg2 для async коду).
# Формат: postgresql+asyncpg://user:password@host:port/dbname
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://research:research@localhost:5432/research_agent",
)

# _checkpointer — глобальний singleton, ініціалізується один раз при старті
# Аналогія Java: Spring Bean зі scope=singleton
_checkpointer: AsyncPostgresSaver | None = None


async def get_checkpointer() -> AsyncPostgresSaver:
    """
    Повертає AsyncPostgresSaver, створює і ініціалізує при першому виклику.

    setup() — створює таблиці langgraph_* в Postgres якщо їх ще нема.
    Безпечно викликати повторно (CREATE TABLE IF NOT EXISTS).
    """
    global _checkpointer
    if _checkpointer is None:
        # AsyncPostgresSaver.from_conn_string() — фабрика з рядка підключення
        # Аналогія Java: DataSource.getConnection() / EntityManagerFactory
        _checkpointer = AsyncPostgresSaver.from_conn_string(
            DATABASE_URL.replace("+asyncpg", "")  # psycopg3 не потребує +asyncpg prefix
        )
        # setup() — DDL: CREATE TABLE IF NOT EXISTS для langgraph_checkpoints та ін.
        await _checkpointer.setup()
    return _checkpointer


@asynccontextmanager
async def lifespan_checkpointer():
    """
    Context manager для lifecycle FastAPI застосунку.

    Викликається один раз при старті (startup) і один раз при зупинці (shutdown).
    Аналогія Java: @PostConstruct / @PreDestroy у Spring Bean.

    Використання у FastAPI:
        @asynccontextmanager
        async def lifespan(app):
            async with lifespan_checkpointer():
                yield
    """
    await get_checkpointer()
    yield
    # При shutdown — звільняємо пул з'єднань
    # (AsyncPostgresSaver закриває внутрішній connection pool)
