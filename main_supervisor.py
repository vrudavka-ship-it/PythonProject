"""
Головний REPL-цикл для мультиагентної системи (homework-lesson-8).

Особливості порівняно з main.py (hw5):
- Supervisor замість одного агента
- HITL (Human-in-the-Loop): при виклику save_report користувач бачить звіт
  і вибирає: approve / edit / reject
- thread_id: унікальний ідентифікатор для InMemorySaver (стан між interrupt/resume)
- Streaming: відповіді стрімляться покроково (не одним блоком)

HITL flow:
  1. Supervisor викликає save_report
  2. HumanInTheLoopMiddleware перехоплює → граф зупиняється (interrupt)
  3. REPL показує деталі і питає: approve / edit / reject
  4. Користувач вводить рішення
  5. REPL відновлює граф через Command(resume=...)
  6. Граф продовжується далі
"""
import json
import os
import uuid

from langgraph.types import Command

# Завантажуємо API ключ із pydantic settings в os.environ
# до того як LangChain намагається прочитати os.environ["OPENAI_API_KEY"].
# Це потрібно бо pydantic_settings читає .env але не встановлює os.environ автоматично,
# а LangChain init_chat_model очікує ключ саме в os.environ.
from config import settings
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key)
# Langfuse ключі теж виставляємо до будь-яких langfuse імпортів
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url)

from supervisor import get_supervisor
from langfuse_utils import langfuse_handler, langfuse_client, flush as langfuse_flush
from langfuse import propagate_attributes


# ==============================
# Допоміжні функції для HITL
# ==============================

def _print_separator(char: str = "=", width: int = 60) -> None:
    """Друкує розділювальну лінію."""
    print(char * width)


def _show_interrupt(interrupt_value: dict) -> tuple[str, str]:
    """
    Відображає деталі перерваної операції і повертає (filename, preview).

    interrupt_value містить action_requests від HumanInTheLoopMiddleware.
    Структура: {"action_requests": [{"action": "save_report", "args": {...}}]}
    """
    _print_separator()
    print("⏸️  ACTION REQUIRES APPROVAL")
    _print_separator()

    filename = ""
    content_preview = ""

    # action_requests — список запитів на схвалення (зазвичай один)
    # HumanInTheLoopMiddleware повертає: {"action": "tool_name", "args": {...}}
    # або {"tool": "tool_name", "tool_input": {...}} — залежить від версії
    for req in interrupt_value.get("action_requests", []):
        tool_name = req.get("action") or req.get("tool", "save_report")
        args = req.get("args") or req.get("tool_input", {})

        print(f"  Tool:  {tool_name}")

        if tool_name == "save_report":
            filename = args.get("filename", "report.md")
            content = args.get("content", "")
            # Показуємо перші 500 символів як превʼю
            content_preview = content[:500] + ("..." if len(content) > 500 else "")

            print(f"  File:  {filename}")
            print(f"\n  --- Preview ---")
            print(content_preview)
            print(f"  --- End Preview ({len(content)} chars total) ---\n")
        else:
            print(f"  Args:  {json.dumps(args, indent=2, ensure_ascii=False)}")

    _print_separator()
    return filename, content_preview


def _get_user_decision() -> tuple[str, str]:
    """
    Запитує рішення користувача: approve / edit / reject.

    Повертає tuple (decision, feedback):
    - ("approve", "") — зберегти як є
    - ("edit", "user feedback text") — переробити з фідбеком
    - ("reject", "") — скасувати
    """
    while True:
        raw = input("👉 approve / edit / reject: ")
        # Видаляємо surrogate і non-ASCII сміття що потрапляє в stdin з stdout
        decision = raw.encode("utf-8", errors="ignore").decode("utf-8").strip().lower()

        if decision == "approve":
            return "approve", ""

        elif decision == "edit":
            feedback = input("✏️  Your feedback: ").strip()
            if feedback:
                return "edit", feedback
            print("  Please enter your feedback.")

        elif decision == "reject":
            return "reject", ""

        else:
            print("  Please enter: approve, edit, or reject")


def _build_resume_command(decision: str, feedback: str) -> dict:
    """
    Будує структуру рішення для Command(resume=...).

    Структура відповідає HumanInTheLoopMiddleware API:
    - approve: {"decisions": [{"type": "approve"}]}
    - edit:    {"decisions": [{"type": "edit", "edited_action": {"feedback": ...}}]}
    - reject:  {"decisions": [{"type": "reject", "message": "User rejected"}]}

    У Java це як будівник команди: new ResumeCommand.Builder().decision(...).build()
    """
    if decision == "approve":
        return {"decisions": [{"type": "approve"}]}
    elif decision == "edit":
        return {"decisions": [{"type": "edit", "edited_action": {"feedback": feedback}}]}
    else:  # reject
        return {"decisions": [{"type": "reject", "message": "User rejected the report"}]}


# ==============================
# Стрімінг відповідей від Supervisor
# ==============================

def _stream_supervisor(query: str, thread_id: str, session_id: str) -> bool:
    """
    Стрімить відповіді Supervisor і обробляє HITL interrupts.

    Повертає True якщо виконання завершилось нормально,
    False якщо було відхилено (reject).

    supervisor.stream() — генератор, що повертає кроки виконання графа.
    Кожен крок — або dict з оновленнями стану, або Interrupt-об'єкт.

    thread_id — унікальний ідентифікатор сесії для InMemorySaver.
    session_id — Langfuse session ID (групує кілька thread_id в одну сесію).
    """
    # recursion_limit=40 — plan+research+critique+(revision)+save = достатньо кроків
    # callbacks=[langfuse_handler] — Langfuse трейсить всі LangGraph кроки автоматично
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 40,
        "callbacks": [langfuse_handler],
    }

    # propagate_attributes — Langfuse 4.x спосіб передати session_id/user_id/tags
    # в межах контекстного блоку всі трейси отримають ці атрибути.
    # Аналогія Java: MDC (Mapped Diagnostic Context) — thread-local метадані для логів.
    with propagate_attributes(
        session_id=session_id,
        user_id="vasyl",
        tags=["supervisor", "multi-agent", "hw12"],
        metadata={"thread_id": thread_id},
    ):
        # Основний цикл стрімінгу
        # Supervisor.stream() повертає кроки: dict (оновлення стану) або tuple (interrupt)
        for step in get_supervisor().stream(
            {"messages": [{"role": "user", "content": query}]},
            config,
            stream_mode="updates",
        ):
            # Перевіряємо чи це interrupt від HITL middleware
            # __interrupt__ — спеціальний ключ у LangGraph для переривань
            if "__interrupt__" in step:
                interrupts = step["__interrupt__"]

                # Беремо тільки перший interrupt — їх може бути кілька але ми обробляємо один
                interrupt_value = interrupts[0].value

                # Показуємо деталі і запитуємо рішення
                _show_interrupt(interrupt_value)
                decision, feedback = _get_user_decision()

                if decision == "reject":
                    print("\n❌ Report rejected. Cancelling save.")
                    resume_data = _build_resume_command("reject", "")
                    _resume_supervisor(resume_data, config)
                    return False

                elif decision == "approve":
                    print("\n✅ Approved! Saving report...")
                    resume_data = _build_resume_command("approve", "")
                    _resume_supervisor(resume_data, config)
                    return True

                else:  # edit
                    print(f"\n✏️  Sending feedback to Supervisor: {feedback!r}")
                    resume_data = _build_resume_command("edit", feedback)
                    # Після edit — Supervisor переробляє і знову викличе save_report
                    # Тому рекурсивно обробляємо відновлення
                    return _resume_with_hitl(resume_data, config)

            else:
                # Звичайне оновлення стану — показуємо повідомлення агентів
                for node_name, node_output in step.items():
                    if isinstance(node_output, dict):
                        for message in node_output.get("messages", []):
                            # pretty_print() — форматований вивід повідомлення LangChain
                            if hasattr(message, "pretty_print"):
                                message.pretty_print()

        return True


def _resume_supervisor(resume_data: dict, config: dict) -> None:
    """
    Відновлює граф після interrupt з заданим рішенням.

    Command(resume=...) — LangGraph API для відновлення після interrupt.
    resume_data — структура рішення для HumanInTheLoopMiddleware.

    Якщо middleware знову генерує interrupt (наприклад після approve) —
    автоматично approve ще раз без питання до користувача.
    """
    for step in get_supervisor().stream(
        Command(resume=resume_data),
        config,
        stream_mode="updates",
    ):
        if "__interrupt__" in step:
            # Middleware знову генерує interrupt після approve — автоматично підтверджуємо
            _resume_supervisor(_build_resume_command("approve", ""), config)
            return
        else:
            for node_name, node_output in step.items():
                if isinstance(node_output, dict):
                    for message in node_output.get("messages", []):
                        if hasattr(message, "pretty_print"):
                            message.pretty_print()


def _resume_with_hitl(resume_data: dict, config: dict) -> bool:
    """
    Відновлює граф і обробляє можливі наступні interrupts (для 'edit' flow).

    Після 'edit' Supervisor може знову викликати save_report → знову interrupt.
    Тому потрібно обробляти HITL в циклі.

    Повертає True якщо завершилось нормально, False якщо reject.
    """
    for step in get_supervisor().stream(
        Command(resume=resume_data),
        config,
        stream_mode="updates",
    ):
        if "__interrupt__" in step:
            interrupts = step["__interrupt__"]
            _show_interrupt(interrupts[0].value)
            decision, feedback = _get_user_decision()

            if decision == "reject":
                print("\n❌ Report rejected.")
                _resume_supervisor(_build_resume_command("reject", ""), config)
                return False
            elif decision == "approve":
                print("\n✅ Approved! Saving report...")
                _resume_supervisor(_build_resume_command("approve", ""), config)
                return True
            else:
                _resume_supervisor(_build_resume_command("edit", feedback), config)
                return True
        else:
            for node_name, node_output in step.items():
                if isinstance(node_output, dict):
                    for message in node_output.get("messages", []):
                        if hasattr(message, "pretty_print"):
                            message.pretty_print()

    return True


# ==============================
# Головний REPL
# ==============================

def main() -> None:
    """
    REPL-цикл для мультиагентної системи Supervisor.

    session_id — один на весь запуск REPL; групує всі thread_id в одну Langfuse session.
    thread_id — новий для кожного запиту; зберігає стан між interrupt і resume.

    Аналогія Java: session_id ~ HttpSession.getId(), thread_id ~ individual request trace ID.
    """
    # session_id — унікальний для одного запуску програми
    # Всі запити в межах одного REPL-запуску = одна Langfuse session
    session_id = f"mas-session-{uuid.uuid4().hex[:8]}"

    print("Multiagent Research System (homework-lesson-12, Langfuse observability)")
    print("Supervisor → Planner → Researcher → Critic → save_report")
    print(f"Langfuse session: {session_id}")
    print("Commands: exit, quit, :q")
    print()

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in {"exit", "quit", ":q"}:
            print("Bye!")
            # Надсилаємо всі буферизовані events перед виходом
            langfuse_flush()
            break

        if not user_input:
            print("Please enter a non-empty question.")
            continue

        # Новий thread_id для кожного запиту
        # Це гарантує незалежність сесій (нема cross-contamination між запитами)
        thread_id = str(uuid.uuid4())

        try:
            _stream_supervisor(user_input, thread_id, session_id)
            # flush після кожного запиту — щоб trace одразу з'явився у Langfuse UI
            langfuse_flush()

        except UnicodeEncodeError:
            print("\n⚠️  Web page contained invalid characters. Please try another query.")
            langfuse_flush()
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            break
        except Exception as exc:
            print(f"\nError: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
