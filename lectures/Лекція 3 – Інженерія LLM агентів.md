# Лекція 3 — Інженерія LLM агентів

**Курс:** Multi-Agent Systems  
**Лектор:** Владислав Шанін — Lead AI Engineer @ Lenovo

---

## Ключова ідея

> Агенти — це просто софт з LLM всередині. Більшість продакшн-агентів — детермінований код з LLM у ключових точках.
>
> **Не магія — а інженерія.**

---

## План заняття

1. Tool / Function Calling — як LLM викликає зовнішні інструменти
2. Фреймворки: LangChain, LlamaIndex, OpenAI SDK
3. Пам'ять, Context Engineering та керування контекстом
4. Model Context Protocol та стандартизація інтеграцій
5. 12-Factor Agents — принципи надійної інженерії та best practices

---

## Tool Calling

**Tool Calling** — механізм, через який LLM взаємодіє із зовнішнім світом: генерує структурований запит (JSON), а ваш код виконує відповідну дію і повертає результат.

**Що включає:**
- Custom-функції (API-виклики, БД-запити)
- Вбудовані інструменти (code interpreter, file search, web browsing)

**Як працює:**
1. Ви описуєте доступні tools у JSON Schema
2. LLM обирає потрібний tool і генерує аргументи
3. Ваш код виконує реальну функцію
4. Результат повертається в LLM

**Еволюція:** парсинг регулярками (2022) → function calling (OpenAI, 2023) → tool use як стандарт індустрії (2023-24) → structured outputs (серпень 2024)

### Схема роботи

```
① Користувач надсилає запит
② LLM аналізує запит з описами tools у контексті
③ LLM генерує: {"name": "get_weather", "args": {"city": "Kyiv"}}
④ Ваш код виконує реальну функцію
⑤ Результат повертається в контекст LLM
⑥ LLM формує фінальну відповідь користувачу
```

### Tool Schema (JSON)

```json
{
  "name": "get_weather",
  "description": "Get weather for a city",
  "parameters": {
    "type": "object",
    "properties": {
      "city": {
        "type": "string",
        "description": "City name, e.g. Kyiv"
      }
    },
    "required": ["city"]
  }
}
```

| Поле | Призначення |
|---|---|
| `name` | Унікальний ідентифікатор інструменту |
| `description` | **LLM вибирає tool саме за цим** — пишіть чітко! |
| `parameters` | JSON Schema: тип і опис кожного аргументу |

### Tool Calling без фреймворку (OpenAI SDK)

```python
import json
from openai import OpenAI

client = OpenAI()

messages = [
    {"role": "system", "content": "You are a weather assistant."},
    {"role": "user", "content": "What is the weather in Kyiv?"},
]

# Крок 1 — передаємо tools= до LLM
response = client.responses.create(
    model="gpt-5.4",
    input=messages,
    tools=[{
        "type": "function",
        "name": "get_weather",
        "description": "Get weather for a city",
        "parameters": {...}
    }]
)

# Крок 2 — відповідь моделі містить tool_call
tool_call = response.output[0]

# Крок 3 — ВИ розпаковуєте аргументи і викликаєте Python-функцію
args = json.loads(tool_call.arguments)
result = get_weather(**args)
```

### Structured Output — три підходи

| Підхід | Коли використовувати |
|---|---|
| **JSON Mode** | Простий спосіб отримати JSON, без гарантій структури |
| **Function Calling** | Коли треба викликати конкретну функцію з параметрами |
| **Pydantic** | Повна типізація та валідація через `response_format=Person` |

```python
# Pydantic підхід — найбезпечніший
from pydantic import BaseModel

class Person(BaseModel):
    name: str
    age: int
    city: str

resp = client.beta.chat.completions.parse(
    model="gpt-5.4",
    messages=msgs,
    response_format=Person,
)
out = resp.choices[0].message.parsed  # типізований об'єкт Person
```

---

## Фреймворки

| Фреймворк | Особливості | Для чого |
|---|---|---|
| **LangChain** | Модель-агностичний, LCEL композиція, гнучка зміна моделей | Швидкий старт, будь-який провайдер |
| **OpenAI SDK** | Нативний для OpenAI, Responses API з вбудованими tools | Якщо тільки OpenAI |
| **LlamaIndex** | Спеціалізація на Document AI та RAG, Workflows 1.0 | Обробка документів |
| **CrewAI** | Рольовий multi-agent підхід, агенти з ролями та цілями | Швидке прототипування команд агентів |

### LangChain — Chat Models

```python
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

# Однаковий інтерфейс для різних провайдерів
llm_openai = ChatOpenAI(model="gpt-5.4")
llm_claude = ChatAnthropic(model="claude-opus-4-6")

messages = [HumanMessage(content="Hello!")]
resp_oai = llm_openai.invoke(messages)
resp_ant = llm_claude.invoke(messages)  # той самий виклик!
```

**Ключові параметри:** `model`, `temperature` (0.0 точно → 1.0 творчо), `streaming`

### LangChain — Tools

```python
from langchain_core.tools import tool

@tool
def get_weather(city: str) -> str:
    """Return current weather for a city."""
    return f"Weather in {city}: 22C, sunny"

@tool
def search_db(query: str, limit: int = 5) -> list:
    """Search database records by query.
    Args: query: search string. limit: max results."""
    return db.search(query, limit)[:limit]

# Прив'язуємо tools до моделі
llm_with_tools = llm.bind_tools([get_weather, search_db])
```

> `@tool` читає ім'я функції, docstring та type hints — і автоматично генерує JSON-схему для LLM.

### LangChain — LCEL Chains

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

prompt = ChatPromptTemplate.from_messages([
    ("system", "You are a {role}. Be concise."),
    ("human", "{question}")
])
model = ChatOpenAI(model="gpt-5.4")
parser = StrOutputParser()

# LCEL: потік через оператор |
chain = prompt | model | parser

result = chain.invoke({
    "role": "Python expert",
    "question": "What is a decorator?"
})
```

**Переваги LCEL:** автоматичний streaming, async/await, трасування через LangSmith, паралельне виконання.

### LangChain — Agents

```python
from langchain.agents import create_agent
from langgraph.checkpoint.memory import MemorySaver

agent = create_agent(
    model="gpt-5.4",
    tools=[get_weather, search_db],
    checkpointer=MemorySaver(),
    system_prompt="You are a helpful assistant."
)

# thread_id ізолює історію по користувачу
config = {"configurable": {"thread_id": "alice"}}

resp1 = agent.invoke(
    {"messages": [{"role": "user", "content": "My name is Alice."}]},
    config=config
)

# Агент пам'ятає контекст автоматично
resp2 = agent.invoke(
    {"messages": [{"role": "user", "content": "What is my name?"}]},
    config=config
)
# -> "Your name is Alice."
```

---

## Типи пам'яті агента

| Тип | Область | Зберігає | Реалізація |
|---|---|---|---|
| **Working Memory** | Поточний запит | messages[], tool results, system prompt | Context window (8K–200K токенів) |
| **Short-term** | Сесія користувача | Останні N повідомлень | Redis з TTL на сесію |
| **Long-term** | Між сесіями | Факти, переваги користувача | Postgres, Redis (persistent), Key-value |
| **Semantic / RAG** | Знання, документи | Будь-який текстовий контент | Pinecone, Chroma, pgvector |

---

## Advanced Tool Use

### Tool Search — проблема масштабу

```
10 інструментів   ≈   3 000 токенів
100 інструментів  ≈  30 000 токенів
500+ інструментів →  переповнення контексту
```

**Рішення:** векторне сховище індексує описи інструментів → агент отримує Top-K за потреби → 3–5 інструментів замість сотень.

```python
from langchain_community.vectorstores import Chroma

tool_docs = ["search_web: searches the web", ...]
vectorstore = Chroma.from_texts(tool_docs, OpenAIEmbeddings())

# On-demand retrieval під час роботи агента
def agent_step(query):
    tools = vectorstore.similarity_search(query, k=5)
    return llm.call(query, tools=tools)
```

> Поріг: **20+ інструментів** — динамічний пошук перевершує статичний список.

### Code Calling — Sandbox

```python
import subprocess

def run_in_sandbox(code: str) -> dict:
    res = subprocess.run(
        ["docker", "run", "--rm", "--network=none"],
        input=code, capture_output=True, timeout=30
    )
    return {"stdout": res.stdout, "stderr": res.stderr}

code = llm.generate_code("Find the sum from 1 to 100")
out = run_in_sandbox(code)

# Самоперевірка: якщо stderr — LLM виправляє і запускає знову
if out["stderr"]:
    fixed = llm.invoke(f"Fix this code:\n{code}\nError:\n{out['stderr']}")
    out = run_in_sandbox(fixed)
```

---

## Model Context Protocol (MCP)

**MCP** — відкритий стандарт від Anthropic (листопад 2024), прийнятий OpenAI, Google DeepMind, Microsoft.

**Аналогія:** USB-C для AI — один стандартний роз'єм замість сотень кастомних інтеграцій.

```
MCP HOST (AI-застосунок: Claude Desktop, IDE)
    ↕
MCP CLIENT (перекладає запити LLM у протокол)
    ↕
MCP SERVER (надає tools, resources, prompts)
```

| Аспект | Деталі |
|---|---|
| **Транспорт** | JSON-RPC 2.0 через STDIO (локально) або HTTP (remote) |
| **Що надає сервер** | Tools (функції), Resources (файли/БД), Prompts (шаблони) |
| **vs Tool Calling** | Tool Calling — кастомний код. MCP — стандартний протокол, plug-and-play екосистема >16 000 серверів |

---

## 12-Factor Agents

| # | Принцип | Суть |
|---|---|---|
| **01** | Natural Language → Tools | Запит → структурований JSON |
| **02** | Own Your Prompts | Повний контроль над промптом |
| **03** | Own Your Context Window | Явно керуйте контекстом LLM |
| **04** | Tools = JSON + Code | AI-рішення ≠ логіка виконання |
| **05** | Unified Execution State | Один стан на весь пайплайн |
| **06** | Launch via Simple API | Агент = один HTTP-виклик |
| **07** | Human-in-the-Loop | HITL — операція першого класу |
| **08** | Own Your Control Flow | Явний loop/switch, не фреймворк |
| **09** | Compact Errors | Помилка → в контекст → retry |
| **10** | Small, Focused Agents | 3–10 кроків. Більше = ненадійність |
| **11** | Trigger from Anywhere | Email, Slack, webhook — однаковий інтерфейс |
| **12** | Stateless Reducer Design | `(state, event) → new_state` |

---

## Підсумки

- **Агент — це не магія.** Це звичайний софт, де LLM приймає рішення, а детермінований код їх виконує
- **Все починається з tool calling:** NL → JSON → ваш код → результат назад у LLM. Решта — надбудова
- **Фреймворк прискорює старт,** але ви маєте володіти своїм промптом, контекстом і control flow
- **Контекст — найцінніший ресурс.** Хто краще керує context window — той будує кращих агентів
- **MCP** — стандарт, що замінює кастомні інтеграції на plug-and-play екосистему
- **12-Factor Agents** — практичні принципи для надійних продакшн-агентів
