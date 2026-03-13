from pathlib import Path

from agent import build_agent
from config import BASE_DIR, settings
from langgraph.errors import GraphRecursionError


def extract_final_text(agent_result: dict) -> str:
    """
    Дістає фінальний текст відповіді з результату агента.

    create_agent повертає state-об'єкт, де зазвичай є список messages.
    Нас цікавить останнє повідомлення моделі.
    """
    messages = agent_result.get("messages", [])
    if not messages:
        return "No response returned by the agent."

    last_message = messages[-1]

    # У більшості випадків content — це просто рядок.
    content = getattr(last_message, "content", "")
    if isinstance(content, str):
        return content

    # Іноді content може бути складнішою структурою.
    return str(content)


def save_report(content: str) -> Path:
    """
    Автоматично зберігає фінальну відповідь у Markdown-файл.

    Чому це робимо в main.py?
    - так ми ГАРАНТУЄМО, що після кожного запиту буде файл;
    - це простіше для навчального проєкту;
    - менше шансів, що агент "забуде" викликати write_report.

    Path — це об'єкт шляху до файлу.
    У Python це набагато зручніше, ніж вручну склеювати рядки через '/'.
    """
    output_dir = BASE_DIR / settings.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    target_path = output_dir / settings.default_report_filename
    target_path.write_text(content, encoding="utf-8")
    return target_path


def main() -> None:
    """
    Простий інтерактивний цикл (REPL).

    REPL = Read -> Eval -> Print -> Loop
    Тобто:
    1. читаємо ввід,
    2. виконуємо,
    3. друкуємо результат,
    4. повторюємо.
    """
    print("Research Agent started.")
    print("Type your question and press Enter.")
    print("Commands: 'exit', 'quit', ':q'")

    # Створюємо агента один раз на старті.
    # Це важливо для пам'яті сесії.
    agent = build_agent()

    # thread_id — ідентифікатор поточної розмови.
    # Поки він однаковий, checkpointer може зберігати контекст діалогу.
    thread_id = "research-cli-session"

    while True:
        user_input = input("\nYou> ").strip()

        if user_input.lower() in {"exit", "quit", ":q"}:
            print("Bye!")
            break

        if not user_input:
            print("Please enter a non-empty question.")
            continue

        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": user_input}]},
                config={
                    "configurable": {"thread_id": thread_id},
                    # recursion_limit — практичний спосіб обмежити кількість кроків агента.
                    "recursion_limit": settings.max_iterations,
                },
            )

            final_text = extract_final_text(result)
            report_path = save_report(final_text)

            print(f"\nAgent>\n{final_text}")
            print(f"\nReport saved to: {report_path}")

        except GraphRecursionError:
            print(
                "\nAgent>\n"
                "Я зациклився на tool-викликах і не встиг дійти до фінальної відповіді.\n\n"
                "Спробуй одне з двох:\n"
                "- перефразуй запит точніше;\n"
                "- або збільш `MAX_ITERATIONS` у `.env`."
            )
        except KeyboardInterrupt:
            print("\nInterrupted by user. Exiting.")
            break
        except Exception as exc:
            print(f"\nAgent error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()