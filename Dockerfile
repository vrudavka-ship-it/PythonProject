# Dockerfile для Research Agent FastAPI застосунку.
#
# Multi-stage build НЕ використовуємо — залежності важкі (sentence-transformers, faiss),
# і нам потрібен один шар де все встановлено.
#
# Аналогія Java: як Dockerfile для Spring Boot JAR,
# але без multi-stage бо нема compile step.

FROM python:3.11-slim

# Робоча директорія всередині контейнера
# Аналогія Java: WORKDIR = корінь classpath / working directory для JAR
WORKDIR /app

# Системні залежності:
# - gcc, g++ — для компіляції native extensions (faiss, numpy)
# - curl      — для healthcheck якщо потрібно
# Встановлюємо окремим RUN щоб кешувалось між rebuild
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо requirements першим — Docker кешує цей шар
# якщо requirements.txt не змінився (не перевстановлює залежності при кожному build)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо весь код проєкту
COPY . .

# Порт FastAPI
EXPOSE 8000

# CMD — команда запуску.
# uvicorn — ASGI сервер (аналог Tomcat/Jetty для Spring Boot).
# --host 0.0.0.0 — слухаємо на всіх інтерфейсах (не тільки localhost)
# app.api:app — модуль app/api.py, об'єкт FastAPI називається app
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]
