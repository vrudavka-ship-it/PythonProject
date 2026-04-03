# Цей файл позначає директорію agents/ як Python-пакет.
#
# Аналогія з Java: в Java пакет визначається структурою директорій + оголошенням
# `package com.example.agents;` в кожному файлі.
# У Python достатньо наявності цього файлу — і директорія стає пакетом.
#
# Завдяки цьому можна писати:
#   from agents.planner import get_planner_agent
#   from agents.research import get_research_agent
#   from agents.critic import get_critic_agent
