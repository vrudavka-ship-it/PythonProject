"""
ReportMCP — MCP сервер для збереження звітів (порт 8902).

Виставляє через FastMCP:
  - save_report(filename, content) → зберігає Markdown звіт у ./output/

Resources:
  - resource://output-dir → шлях до директорії і список збережених звітів

HITL (Human-in-the-Loop) захист реалізований на рівні Supervisor:
HumanInTheLoopMiddleware перехоплює виклик save_report до того як він потрапляє
до ReportMCP. Тобто сам ReportMCP не знає про HITL — він просто зберігає файл.

Запуск:
    .venv/bin/python3 mcp_servers/report_mcp.py   # порт 8902
"""
import json
import os
import sys
from pathlib import Path

# sys.path fix — щоб знаходити config, tools при запуску напряму
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from fastmcp import FastMCP

from config import settings, MCP_REPORT_PORT, BASE_DIR
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
os.environ.setdefault("TAVILY_API_KEY", settings.tavily_api_key)

from tools import write_report as _write_report

# FastMCP("ReportMCP") — окремий сервер від SearchMCP
mcp_server = FastMCP(name="ReportMCP")


# ==============================
# MCP Tools
# ==============================

@mcp_server.tool
def save_report(filename: str, content: str) -> str:
    """
    Save a Markdown research report to the output directory.

    IMPORTANT: This tool requires human approval (HITL) before execution.
    The Supervisor's HumanInTheLoopMiddleware intercepts this call
    and pauses until the user approves, edits, or rejects.

    Args:
        filename: Target file name (e.g. 'rag_comparison.md')
        content: Full Markdown content of the report
    """
    # Делегуємо до write_report() з tools.py
    # write_report вже містить захист від path traversal атаки (Path.name)
    return _write_report(filename, content)


# ==============================
# MCP Resources
# ==============================

@mcp_server.resource("resource://output-dir")
def get_output_dir_info() -> str:
    """
    Information about the output directory: path and list of saved reports.

    Returns JSON with:
        - path: абсолютний шлях до output директорії
        - reports: список збережених .md файлів
        - report_count: кількість звітів
    """
    # output_dir — шлях до директорії зі звітами
    output_dir = BASE_DIR / settings.output_dir

    reports = []
    if output_dir.exists():
        # glob("*.md") — всі Markdown файли в директорії
        # sorted() — сортуємо за назвою для стабільного порядку
        reports = sorted(
            f.name for f in output_dir.glob("*.md")
        )

    return json.dumps({
        "path": str(output_dir),
        "reports": reports,
        "report_count": len(reports),
    })


# ==============================
# Точка входу
# ==============================

if __name__ == "__main__":
    print(f"Starting ReportMCP server on port {MCP_REPORT_PORT}...")
    print(f"  Tools:     save_report")
    print(f"  Resources: resource://output-dir")
    print(f"  URL:       http://127.0.0.1:{MCP_REPORT_PORT}/mcp")
    mcp_server.run(transport="streamable-http", port=MCP_REPORT_PORT)
