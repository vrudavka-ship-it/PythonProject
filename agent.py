from langchain.agents import create_agent
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver

from config import SYSTEM_PROMPT, settings
from tools import TOOLS


def build_agent():
    """
    Створює та повертає агента.

    Що тут відбувається:
    - створюємо модель;
    - підключаємо tools;
    - додаємо system prompt;
    - додаємо MemorySaver для пам'яті діалогу в межах процесу.

    Аналогія з Java:
    це схоже на factory / configuration method, яка збирає всі залежності.
    """
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=settings.temperature,
        api_key=settings.openai_api_key,
    )

    # MemorySaver зберігає короткоживучу пам'ять у межах поточного запуску програми.
    # Тобто агент пам'ятає попередні повідомлення, поки процес не завершився.
    checkpointer = MemorySaver()

    agent = create_agent(
        model=llm,
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        checkpointer=checkpointer,
    )
    return agent