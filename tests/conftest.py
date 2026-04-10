"""
conftest.py — спільна конфігурація pytest для всіх тестів у tests/.

У pytest conftest.py — це як @BeforeAll/@BeforeEach у JUnit, але на рівні директорії.
Він автоматично завантажується перед будь-яким тестовим файлом у тій самій папці.

Що робимо тут:
1. Додаємо project root у sys.path (щоб імпортувати agents/, tools/, config.py)
2. Завантажуємо .env ключі в os.environ до будь-яких langchain-імпортів
"""
import os
import sys

# Додаємо корінь проєкту у sys.path — аналогія Java: додаємо src/ у classpath
# __file__ тут: /path/to/project/tests/conftest.py
# dirname(dirname(...)) → /path/to/project
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Завантажуємо API ключі в os.environ ДО будь-яких langchain/openai імпортів.
# pydantic-settings не встановлює os.environ автоматично — треба робити вручну.
from config import settings

os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key)
