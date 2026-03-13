from agent import build_initial_messages, run_agent


def main() -> None:
    """
    Головний REPL-цикл програми.

    REPL = Read → Eval → Print → Loop
    1. Читаємо ввід користувача.
    2. Відправляємо агенту.
    3. Друкуємо відповідь.
    4. Повторюємо.

    Ключова відмінність від lesson-3:
    - messages — це звичайний Python list, який ми ведемо самі.
    - Немає MemorySaver, немає thread_id, немає LangGraph state.
    - Пам'ять між запитами — просто список повідомлень, що росте.
    - Збереження звіту — відповідальність агента через write_report tool,
      а не автоматика в main.py.
    """
    print("Research Agent started.")
    print("Type your question and press Enter.")
    print("Commands: 'exit', 'quit', ':q'")

    # Ініціалізуємо список повідомлень із system prompt.
    # messages — це як LinkedList<Message> у Java, де ми вручну додаємо елементи.
    # Один список на всю сесію — агент "пам'ятає" весь діалог.
    messages = build_initial_messages()

    while True:
        # input() — читає рядок з консолі (блокуючий виклик)
        # .strip() — прибирає пробіли по краях, як String.trim() у Java
        user_input = input("\nYou> ").strip()

        if user_input.lower() in {"exit", "quit", ":q"}:
            print("Bye!")
            break

        if not user_input:
            print("Please enter a non-empty question.")
            continue

        # Додаємо повідомлення користувача в список.
        # dict з роллю "user" — стандарт OpenAI Chat API.
        messages.append({"role": "user", "content": user_input})

        try:
            # Запускаємо ReAct loop.
            # Передаємо messages — агент додає до нього нові повідомлення.
            # Після повернення з run_agent список messages вже оновлений (пам'ять збережена).
            final_text = run_agent(messages)
            print(f"\nAgent>\n{final_text}")

        except KeyboardInterrupt:
            print("\nInterrupted by user. Exiting.")
            break
        except Exception as exc:
            print(f"\nAgent error: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
