import json

from openai import OpenAI

from config import SYSTEM_PROMPT, settings
from tools import TOOLS_MAP, TOOLS_SCHEMA


def _assistant_message_to_dict(message) -> dict:
    """
    Конвертує об'єкт відповіді OpenAI SDK у звичайний dict.

    Навіщо?
    OpenAI SDK повертає Pydantic-об'єкт (ChatCompletionMessage), а не dict.
    Але наступний API call очікує list[dict] у полі messages.
    Якщо залишити об'єкт — SDK серіалізує його сам, але явний dict надійніший
    і дає нам повний контроль над тим, що зберігається в history.

    У Java аналог: ObjectMapper.convertValue(object, Map.class)

    tool_calls — це список викликів інструментів, які LLM хоче зробити.
    Якщо їх не серіалізувати явно — вони можуть загубитись в history.
    """
    # Базова структура повідомлення асистента
    # dict — як HashMap<String, Object> у Java
    result: dict = {
        "role": "assistant",
        # content може бути None коли є tool_calls — це нормально для OpenAI API
        "content": message.content,
    }

    # Якщо є tool_calls — серіалізуємо їх явно у список dict
    if message.tool_calls:
        # list comprehension — стислий спосіб перетворити список об'єктів у список dict
        # у Java: toolCalls.stream().map(tc -> Map.of(...)).collect(toList())
        result["tool_calls"] = [
            {
                "id": tc.id,                        # унікальний ID виклику (як correlation ID)
                "type": "function",                 # завжди "function" для tool calls
                "function": {
                    "name": tc.function.name,       # назва функції
                    "arguments": tc.function.arguments,  # JSON-рядок з аргументами
                },
            }
            for tc in message.tool_calls
        ]

    return result


def run_agent(messages: list[dict], max_iterations: int = None) -> str:
    """
    Власна реалізація ReAct-циклу (Reason + Act).

    Що таке ReAct loop?
    1. Відправляємо повідомлення в LLM.
    2. LLM або відповідає текстом (фінальна відповідь) — тоді зупиняємось,
       або повертає tool_calls (хоче викликати інструмент) — тоді виконуємо і повторюємо.

    У Java-термінах це схоже на цикл:
    while (!agent.isDone()) {
        Response response = llm.call(messages);
        if (response.hasToolCalls()) {
            executeTools(response.toolCalls());
        } else {
            return response.text();
        }
    }

    Параметри:
    - messages: list[dict] — список повідомлень діалогу (керуємо вручну, без MemorySaver)
      list[dict] — це як List<Map<String, String>> у Java
    - max_iterations: int — максимальна кількість кроків (захист від нескінченного циклу)

    Повертає: str — фінальна текстова відповідь агента
    """

    # Якщо ліміт не переданий явно — беремо з конфігурації
    if max_iterations is None:
        max_iterations = settings.max_iterations

    # Створюємо клієнт OpenAI API
    # OpenAI() — як new OpenAIClient(apiKey) у Java
    client = OpenAI(api_key=settings.openai_api_key)

    # Головний цикл ReAct
    # range(max_iterations) — генерує числа від 0 до max_iterations-1
    # як for (int i = 0; i < maxIterations; i++) у Java
    for iteration in range(max_iterations):

        # Лог ітерації — зручно для дебагу, видно де агент знаходиться
        print(f"\n─── Iteration {iteration + 1}/{max_iterations} (messages in context: {len(messages)}) ───")

        # ── Крок 1: відправляємо запит у LLM ──────────────────────────────
        response = client.chat.completions.create(
            model=settings.openai_model,
            temperature=settings.temperature,
            messages=messages,       # увесь контекст діалогу
            tools=TOOLS_SCHEMA,      # список доступних tools у форматі JSON Schema
            tool_choice="auto",      # LLM сам вирішує: відповісти текстом чи викликати tool
        )

        # response.choices — список варіантів відповіді (зазвичай один)
        # [0] — беремо перший (і єдиний) варіант
        choice = response.choices[0]

        # message — об'єкт відповіді від LLM (Pydantic-об'єкт OpenAI SDK)
        assistant_message = choice.message

        # Конвертуємо у dict і додаємо в history явно.
        # Це і є "ручна пам'ять" — без MemorySaver ми самі ведемо список.
        # Зберігаємо dict (а не SDK-об'єкт) — надійніше і передбачуваніше.
        assistant_dict = _assistant_message_to_dict(assistant_message)
        messages.append(assistant_dict)

        # ── Крок 2: перевіряємо — фінальна відповідь чи tool call? ────────

        # finish_reason — причина зупинки генерації:
        # "stop"       — LLM закінчив відповідь (фінальна відповідь)
        # "tool_calls" — LLM хоче викликати інструмент
        if choice.finish_reason == "stop":
            # Фінальна відповідь — повертаємо текст
            return assistant_message.content or ""

        if choice.finish_reason != "tool_calls":
            # Невідома причина зупинки — безпечно зупиняємось
            return assistant_message.content or ""

        # ── Крок 3: виконуємо tool calls ───────────────────────────────────

        # tool_calls — список інструментів, які LLM хоче викликати
        # Може бути кілька одночасно (parallel tool calling)
        tool_calls = assistant_message.tool_calls

        for tool_call in tool_calls:
            tool_name = tool_call.function.name

            # tool_call.function.arguments — це JSON-рядок з параметрами
            # json.loads() — парсимо JSON у dict, як ObjectMapper.readValue() у Java
            try:
                tool_args: dict = json.loads(tool_call.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            # Шукаємо функцію у словнику TOOLS_MAP за її назвою
            tool_fn = TOOLS_MAP.get(tool_name)

            if tool_fn is None:
                # Невідомий tool — повертаємо помилку назад у LLM
                tool_result = f"Error: unknown tool '{tool_name}'"
                print(f"\n🔧 Tool call: {tool_name} — UNKNOWN TOOL")
            else:
                # Викликаємо функцію з розпакованими аргументами.
                # **tool_args — розпаковує dict у kwargs, як map.spread() у JS.
                # У Java аналогу немає напряму, але схоже на reflection invoke.
                try:
                    tool_result = tool_fn(**tool_args)
                except Exception as exc:
                    tool_result = f"Error: tool '{tool_name}' failed: {type(exc).__name__}: {exc}"
                    print(f"📎 Result: ERROR — {tool_result}")

            # Результат виконання tool повертаємо назад у контекст.
            # Формат повідомлення з роллю "tool" — стандарт OpenAI API.
            # tool_call_id — зв'язує результат із конкретним викликом (як correlation ID).
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    # content має бути рядком — конвертуємо якщо потрібно
                    "content": tool_result if isinstance(tool_result, str) else json.dumps(tool_result, ensure_ascii=False),
                }
            )

    # Якщо вийшли з циклу не через "stop" — значить вичерпали ліміт ітерацій
    return (
        "Агент вичерпав ліміт ітерацій і не дійшов до фінальної відповіді.\n"
        "Спробуй перефразувати запит або збільш MAX_ITERATIONS у .env"
    )


def build_initial_messages() -> list[dict]:
    """
    Створює початковий список повідомлень із system prompt.

    list[dict] — це як ArrayList<HashMap<String, String>> у Java.
    Перший елемент завжди — system prompt, який задає поведінку агента.
    """
    return [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
