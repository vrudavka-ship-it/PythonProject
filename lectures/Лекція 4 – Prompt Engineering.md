# Лекція 4 — Prompt Engineering: Техніки

**Курс:** Multi-Agent Systems  
**Лектор:** Владислав Шанін — Lead AI Engineer @ Lenovo

---

## План лекції

1. Базові техніки: Zero-Shot, Few-Shot, Chain-of-Thought
2. Просунуті патерни: Self-Consistency, Self-Reflection, RAG
3. Reasoning + Acting: ReAct та Tree-of-Thoughts
4. Крихкість промптів та eval-driven підхід
5. Загальні правила промптінгу для MAS

---

## Промпт = конституція агента

Для агента промпт — це набагато більше ніж просто питання. Він визначає **ЩО** агент робить, **ЯК** думає, **З КИМ** спілкується, і **КОЛИ** зупиняється.

> **Аналогія:** уявіть, що ви наймаєте працівника. Ви ж не скажете "ну, роби щось корисне". Ви даєте посадову інструкцію — роль, обов'язки, обмеження, формат звітності.

### Чотири компоненти промпту

| Компонент | Призначення | Приклад |
|---|---|---|
| **Instruction** | Що агент робить — роль, задача | `You are a customer support classifier. Categorize the incoming ticket` |
| **Context** | Знання та контекст середовища | `Our company sells SaaS PM tools. Tiers: Billing, Technical, Feature Request, Bug Report` |
| **Input Data** | Вхідні дані для обробки | `Ticket: "I was charged twice for my Pro subscription this month."` |
| **Output Format** | Формат та структура відповіді | `JSON: {"category": "...", "priority": "high|medium|low", "summary": "..."}` |

### System Prompt для Planner агента

```
## Identity
You are a Task Planner agent in a software development team.

## Capabilities
Delegate to: Coder, Tester, Reviewer

## Goals
Create step-by-step execution plan.
Each step: which agent + input.

## Constraints
- Never write code yourself
- Maximum 7 steps per plan
- If ambiguous, ask for clarification

## Output Format
[{"step": 1, "agent": "Coder", "task": "..."}]
```

> **Real-world приклад:** Cline (VS Code agent) має system prompt ~11,000 символів з розділенням Plan Mode / Act Mode.

### Розмитий vs Конкретний промпт

| Розмитий | Конкретний |
|---|---|
| `"Напиши щось про наш продукт"` | `"Напиши опис PM-tool до 100 слів. Фокус: економія часу для менеджерів"` |
| `"Не використовуй жаргон"` | `"Пиши простою мовою, зрозумілою для нетехнічного менеджера"` |
| `"Проаналізуй цей код"` | `"Ти — Security Auditor. Знайди вразливості. Відповідай у JSON: {severity, issue, fix}"` |
| `"Відповідай коротко"` | `"Відповідь: 1-2 речення. Формат: [Категорія]: пояснення"` |
| `"Будь корисним асистентом"` | `"Ти — DevOps-агент. Діагностуй проблему, запропонуй kubectl-команду"` |

> **Правило:** Конкретність > оригінальність. Позитивні інструкції > негативні.

---

## Базові техніки

### Zero-Shot Prompting

Модель отримує лише інструкцію — без жодного прикладу відповіді.

```
system: You are a support ticket classifier.
        Categories: «Billing», «Bug», «Feature Request», «Other»
        Reply with one category only.
user:   Dashboard keeps crashing on export.
ai:     Bug
```

**Де використовувати:** класифікація тікетів, переклад, сумаризація, просте витягування даних.

> Zero-shot — це **baseline**. Починай з нього, ускладнюй лише коли якість недостатня.

### Few-Shot Prompting

В інструкцію додаються приклади правильних відповідей — модель копіює патерн.

```
system: You are a support ticket classifier.
        Categories: «Billing», «Bug», «Feature Request», «Other»
        Reply with one category only. Examples:
        "I was charged twice"       → Billing
        "Add dark mode"             → Feature Request
        "App crashes on export"     → Bug
user:   Team can't see shared dashboards
ai:     Bug
```

**Best practices:** 3–5 різноманітних прикладів в однаковому форматі.

### Chain-of-Thought (CoT)

Модель міркує покроково перед тим, як дати фінальну відповідь.

```
system: You are a math tutor. Think step by step.
        Show each reasoning step, then the answer.
user:   Masks cost $2 each. 5+ get 20% off. 7 masks = ?
ai:     Step 1: Base cost: 7 × $2 = $14
        Step 2: 7 >= 5 → discount applies
        Step 3: Discount: 20% of $14 = $2.80
        Answer: $14 - $2.80 = $11.20
```

**Обмеження:** лінійний reasoning, немає доступу до зовнішнього світу, може галюцинувати кроки.

### Few-Shot CoT

В прикладах показуємо не лише відповідь, а й хід міркувань.

```
system: You are a backend developer. For each feature:
        1) Clarify → 2) Data model → 3) API → 4) Code
        Example:
        User: "Add password reset"
        1) Email-based reset with expiring token
        2) reset_tokens(user_id, token, expires_at)
        3) POST /reset-request, POST /reset-confirm
        4) [code]
user:   "Add authentication"
ai:     1) OAuth2 or JWT? → JWT for stateless API
        2) users(id, email, password_hash)
        3) POST /login, POST /register, GET /me
        4) [code]
```

---

## Просунуті патерни

### Self-Consistency

Запускаємо той самий промпт N разів → обираємо найчастішу відповідь (majority voting).

```
user: "My invoice shows wrong tax amount"

── Run 1 ──  ai: Billing
── Run 2 ──  ai: Bug
── Run 3 ──  ai: Billing

── majority vote → Billing (2/3)
```

**Trade-off:** N × вартість та latency, але вища точність.

**Для MAS:** N паралельних агентів + агент-агрегатор.

> **Аналогія:** як в суді — 12 присяжних краще ніж один суддя для складних справ. *(Wang et al., ICLR 2023)*

### Self-Reflection

Модель генерує відповідь → перечитує → знаходить помилки → виправляє (2 виклики моделі в ланцюжку).

```
── Виклик 1: згенеруй ────────────────────────────
system: You are a backend developer. Write code.
user:   Write a login endpoint with JWT
ai:     def login(email, pwd): ... return jwt.encode()

── Виклик 2: перевір себе ────────────────────────
system: Review this code for bugs, edge cases,
        and security. List issues, then fix.
user:   [ai response from the previous call]
ai:     Issues: no rate limit, plain-text pwd, no exp
        Fixed: bcrypt.hash(pwd) + exp=1h + limiter
```

**Ключова техніка для coding-агентів:** generate → critique → refine.

### RAG-Prompting

Перед генерацією шукаємо релевантні дані і вставляємо їх у промпт.

```
── Крок 1: пошук (vector search) ──────────────────
query:  "How to reset 2FA?"
found:  docs/security/2fa-reset.md (score: 0.94)
        docs/security/account-recovery.md (0.87)

── Крок 2: генерація з контекстом ─────────────────
system: You are a support agent. Answer using ONLY
        the provided context. If unsure, say so.
        Context: [2fa-reset.md content here]
user:   "How to reset 2FA?"
ai:     Go to Settings → Security → Reset 2FA...
```

**Навіщо:** менше галюцинацій, актуальні дані, відповіді з джерелами.  
**Для MAS:** агент-retriever шукає, агент-generator відповідає.

### Agentic RAG

Агент **сам вирішує** коли і що шукати — RAG як tool call.

```
system: You are a support agent.
        Tools: search_docs(query), get_user(id)
        Use tools when you need information.
user:   "How do I reset 2FA for user #4521?"
ai:     I need the docs and user info. Calling:
        tool: search_docs("reset 2FA")
        tool: get_user(4521)
result: [2fa-reset.md] + [user: Pro plan, 2FA on]
ai:     User #4521 has 2FA enabled. To reset:...
```

**Різниця з RAG:** агент сам вирішує що шукати, може комбінувати кілька джерел.

---

## Reasoning + Acting

### ReAct

**ReAct** (Yao et al., ICLR 2023) — фундаментальний патерн для AI агентів: reasoning + actions в інтерлівному форматі.

- **Переваги над CoT:** може дістати інформацію із зовнішнього світу (tools!)
- **Переваги над Act-only:** обґрунтовує кожну дію (Thought перед Action)
- **Результати:** ALFWorld +34%, WebShop +10% з 1-2 few-shot

```
user:    Birthplace of the director of Jaws?

Thought: I need to find who directed Jaws.
Action:  Search["Jaws film director"]
Observe: Jaws (1975) directed by Steven Spielberg.

Thought: Now I need Spielberg's birthplace.
Action:  Search["Steven Spielberg birthplace"]
Observe: Born in Cincinnati, Ohio.

Thought: I have the answer.
Action:  Finish["Cincinnati, Ohio"]
```

### ReAct — шаблон промпту

```
system: You are a research assistant. Answer questions using tools.
        You have access to these tools:
        - Search(query): web search
        - Calc(expr): calculator
        - Finish(answer): final answer
        Solve by repeating this cycle:
        Thought: [reason about what to do next]
        Action:  [call one tool]
        Observe: [tool returns result]
        Rules: max 5 steps, use ONLY listed tools.
```

**Механіка:** 1 ітерація = 1 API call → LLM генерує text + tool_call → оркестратор додає `{role:"tool"}` → новий API call.

### Tree of Thoughts (ToT)

Покроковий пошук рішення з генерацією, оцінкою та відсіканням гілок.

```
Задача: Make 24 from [4, 9, 10, 13] using +−×÷

── API call 1: generate ──────────────────────────
A: 13−9=4 → [4,4,10]   B: 10−4=6 → [6,9,13]   C: 13+9=22 → [4,10,22]

── API calls 2–4: evaluate (паралельно) ──────────
call 2  [4,4,10]: impossible ✘ pruned
call 3  [6,9,13]: maybe → expand
call 4  [4,10,22]: impossible ✘ pruned

── API call 5: expand B ──────────────────────────
B1: 13−9=4 → 6×4=24 ✔   B2: 9−6=3 → [3,13]   B3: 6+9=15 → [15,13]
```

> Мін. 5 API calls на 1 задачу. Оцінки calls 2–4 можна паралелити.

### Meta Prompting

Сильна LLM пише промпт → eval на тестах → LLM фіксить → повторюємо.

```
1. DEFINE: task + критерії + test_set (50 розмічених тикетів)
2. GENERATE: gpt-5.2 пише prompt_v1
3. EVAL: gpt-5-mini(prompt_v1, ticket) → accuracy = 78%
4. REFINE: gpt-5.2 аналізує 11 помилок → prompt_v2
5. LOOP: v1 78% → v2 89% → v3 94% → v4 95% (converged)
6. DEPLOY: production = gpt-5-mini + prompt_v4
```

> gpt-5.2 Thinking = dev-time cost. В продакшні працює тільки дешева модель з оптимізованим промптом.

### Reasoning в сучасних LLM

```
Standard LLM:  Pretrain → SFT → RLHF (align з preferences людей)
Reasoner:      Pretrain → SFT (з CoT прикладами) → RL з verifiable rewards
```

| | RLHF | RLVR (reasoning) |
|---|---|---|
| **Reward signal** | «яка відповідь більше подобається людям?» | «чи правильна фінальна відповідь?» (math/code correctness) |

**Що змінює RL для reasoning:**
1. Модель сама вчиться генерувати CoT — не промптом, а нативно
2. **Backtracking** — помітила помилку → повертається, пробує інший шлях
3. **Self-verification** — o3 пише brute-force, потім перевіряє оптимальне рішення
4. **Test-time compute scaling** — більше думає = краще відповідає (логарифмічно)

**Аналогія Kahneman:**
- System 1 (GPT-4o, Claude Sonnet) — швидко, інтуїтивно
- System 2 (o3, R1, GPT-5.2 Thinking) — повільно, аналітично

---

## Яку техніку обрати?

```
Проста задача, стандартний формат          → Zero-Shot
Потрібен специфічний формат/патерн         → Few-Shot

Багатокрокове міркування                   → CoT / Few-Shot CoT
Критична точність, є бюджет                → Self-Consistency
Складна задача з розгалуженнями            → Tree of Thought
Модель помиляється — потрібна перевірка    → Self-Reflection

Потрібні актуальні/зовнішні дані           → RAG / Agentic RAG
Потрібні інструменти + міркування          → ReAct
```

> **Правило:** НІКОЛИ не починай з CoT або Self-Consistency. Спочатку спробуй Zero-Shot. Якщо не працює — Few-Shot. І так далі. Це економить і гроші, і час.

---

## Типові помилки промптінгу

| Помилка | Як уникнути |
|---|---|
| **Розмитість** | "Write something" → конкретний промпт з обмеженнями |
| **Over-engineering** | Починай з zero-shot, ускладнюй лише коли не працює |
| **Ігнорування edge cases** | Враховуй пустий input, gibberish, prompt injection |
| **Один тест нічого не доводить** | Тестуй 5+ разів з різними inputs |

---

## Крихкість промптів

**Проблема:** один промпт — різні результати на різних моделях.

```
GPT-4.1         → 95% accuracy
GPT-5 mini      → 60% accuracy
Claude Sonnet   → parser fails
```

**Рішення:** версіонування + eval-driven підхід.

```
Промпт:  prompts/agent.yaml
Тести:   evals/test_cases.json
Workflow: змінив модель → прогнав eval → побачив де зламалось → виправив
```

---

## Загальні правила промптінгу для MAS

1. **Вузька спеціалізація:** 5 простих агентів > 1 складний
2. **Жорсткі формати:** JSON/XML schema + валідація між агентами
3. **Ітеративна розробка:** Zero-shot → Few-shot → CoT → ReAct
4. **Промпти = код:** git, changelog, rollback
5. **Eval-driven:** без метрик гадаєте, а не покращуєте
6. **Observability:** логуй кожен промпт і відповідь
7. **Human-in-the-Loop:** для дій з наслідками — confirmation step

---

## Висновки

- **Промпт = посадова інструкція** для агента. Визначає роль, стиль міркувань, взаємодію та межі
- **Ітеративний підхід:** Zero-shot → Few-shot → CoT → ReAct — ускладнюй лише коли треба
- **ReAct** — ключовий патерн для агентів: Thought → Action → Observation у циклі
- **Промпти = код:** версіонування в git, eval-driven розробка, observability
- **Жорсткі формати обов'язкові:** JSON/XML schema + валідація між агентами
- **5 простих агентів > 1 складний:** вузька спеціалізація + Human-in-the-Loop
