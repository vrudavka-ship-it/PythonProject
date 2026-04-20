"""
Головний REPL-цикл для мультиагентної системи (homework-lesson-9).

Архітектура (порівняно з hw8):
- Supervisor залишається локальним create_agent з HITL middleware
- Sub-агенти (planner, researcher, critic) тепер запускаються через ACP протокол
- Tools (web_search, read_url, knowledge_search) виставлені через SearchMCP
- save_report виклика через ReportMCP

Порядок запуску:
    # Термінал 1: .venv/bin/python3 mcp_servers/search_mcp.py   (порт 8901)
    # Термінал 2: .venv/bin/python3 mcp_servers/report_mcp.py   (порт 8902)
    # Термінал 3: .venv/bin/python3 acp_server.py               (порт 8903)
    # Термінал 4: .venv/bin/python3 main.py                     (REPL)

HITL flow (без змін):
  1. Supervisor викликає save_report
  2. HumanInTheLoopMiddleware перехоплює → граф зупиняється (interrupt)
  3. REPL показує деталі і питає: approve / edit / reject
  4. Користувач вводить рішення
  5. REPL відновлює граф через Command(resume=...)
"""
import json
import os
import uuid

from langgraph.types import Command

# Завантажуємо API ключ із pydantic settings в os.environ
# до того як LangChain намагається прочитати os.environ["OPENAI_API_KEY"]
from config import settings
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key)
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url)

from supervisor import get_supervisor
from langfuse_utils import langfuse_handler, flush as langfuse_flush
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
    """
    _print_separator()
    print("⏸️  ACTION REQUIRES APPROVAL")
    _print_separator()

    filename = ""
    content_preview = ""

    for req in interrupt_value.get("action_requests", []):
        tool_name = req.get("action") or req.get("tool", "save_report")
        args = req.get("args") or req.get("tool_input", {})

        print(f"  Tool:  {tool_name}")

        if tool_name == "save_report":
            filename = args.get("filename", "report.md")
            content = args.get("content", "")
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

    Повертає tuple (decision, feedback).
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
    """Будує структуру рішення для Command(resume=...)."""
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
    """
    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 40,
        "callbacks": [langfuse_handler],
    }

    with propagate_attributes(
        session_id=session_id,
        user_id="vasyl",
        tags=["supervisor", "multi-agent", "hw12"],
        metadata={"thread_id": thread_id},
    ):
        for step in get_supervisor().stream(
            {"messages": [{"role": "user", "content": query}]},
            config,
            stream_mode="updates",
        ):
            if "__interrupt__" in step:
                interrupts = step["__interrupt__"]
                interrupt_value = interrupts[0].value

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
                    return _resume_with_hitl(resume_data, config)

            else:
                for node_name, node_output in step.items():
                    if isinstance(node_output, dict):
                        for message in node_output.get("messages", []):
                            if hasattr(message, "pretty_print"):
                                message.pretty_print()

        return True


def _resume_supervisor(resume_data: dict, config: dict) -> None:
    """Відновлює граф після interrupt з заданим рішенням."""
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
    """Відновлює граф і обробляє можливі наступні interrupts (для 'edit' flow)."""
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
    REPL-цикл для мультиагентної системи (hw9: MCP + ACP).

    Перед запуском переконайтесь що запущені:
      - mcp_servers/search_mcp.py (порт 8901)
      - mcp_servers/report_mcp.py (порт 8902)
      - acp_server.py             (порт 8903)
    """
    session_id = f"mas-session-{uuid.uuid4().hex[:8]}"

    print("Multiagent Research System (homework-lesson-12: MCP + ACP + Langfuse)")
    print("Architecture: Supervisor → ACP → [Planner|Researcher|Critic] → MCP → Tools")
    print("Servers required:")
    print("  8901: SearchMCP  (web_search, read_url, knowledge_search)")
    print("  8902: ReportMCP  (save_report)")
    print("  8903: ACP Server (planner, researcher, critic)")
    print(f"Langfuse session: {session_id}")
    print("Commands: exit, quit, :q")
    print()

    while True:
        user_input = input("You: ").strip()

        if user_input.lower() in {"exit", "quit", ":q"}:
            print("Bye!")
            langfuse_flush()
            break

        if not user_input:
            print("Please enter a non-empty question.")
            continue

        thread_id = str(uuid.uuid4())

        try:
            _stream_supervisor(user_input, thread_id, session_id)
            langfuse_flush()

        except UnicodeEncodeError:
            print("\n⚠️  Web page contained invalid characters. Please try another query.")
            langfuse_flush()
        except KeyboardInterrupt:
            print("\nInterrupted by user.")
            langfuse_flush()
            break
        except Exception as exc:
            print(f"\nError: {type(exc).__name__}: {exc}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    main()
