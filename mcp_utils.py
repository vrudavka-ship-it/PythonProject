"""
mcp_utils.py — утиліта для конвертації MCP tools у LangChain StructuredTool.

Навіщо це потрібно?
- MCP (Model Context Protocol) — стандартний протокол опису tools для LLM.
  Сервер повертає список tools у форматі MCP (назва, опис, JSON Schema параметрів).
- LangChain агенти очікують tools у своєму форматі: StructuredTool з pydantic args_schema.
- mcp_tools_to_langchain() — bridge між двома форматами.

Аналогія з Java:
- MCP tool definition ≈ OpenAPI/Swagger операція
- LangChain StructuredTool ≈ Spring @Component що реалізує Tool interface
- mcp_tools_to_langchain() ≈ Adapter Pattern: адаптує один інтерфейс до іншого
"""
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import Field, create_model


def mcp_tools_to_langchain(mcp_tools: list, mcp_client) -> list[StructuredTool]:
    """
    Конвертує список MCP tool definitions у LangChain StructuredTool об'єкти.

    Кожен MCP tool → StructuredTool, що async викликає MCP сервер через client.

    Args:
        mcp_tools: список MCP tool об'єктів (результат client.list_tools())
        mcp_client: відкритий fastmcp.Client (async context manager)

    Returns:
        list[StructuredTool] — tools у форматі LangChain, готові для create_agent()

    Аналогія з Java:
        List<MCPTool> → stream().map(t -> new LangChainStructuredTool(t)).collect(...)
    """
    # lc_tools — список конвертованих LangChain tools
    # list comprehension — будуємо список через _build_tool для кожного MCP tool
    lc_tools = []

    for tool in mcp_tools:
        # inputSchema — JSON Schema опис параметрів tool (може бути None)
        # Fallback: порожній об'єкт схеми якщо schema відсутня
        schema = tool.inputSchema or {"type": "object", "properties": {}}
        props = schema.get("properties", {})
        # required — множина обов'язкових параметрів (як @NotNull у Java)
        # set() — для швидкого пошуку через `in`
        required = set(schema.get("required", []))

        # type_map — маппінг JSON Schema типів на Python типи
        # dict — як HashMap<String, Class<?>> у Java
        type_map = {
            "string": str,
            "integer": int,
            "number": float,
            "boolean": bool,
        }

        # Будуємо pydantic fields для кожного параметра tool
        # fields — dict для create_model() — як Map<String, FieldInfo> у Java
        fields = {}
        for name, prop in props.items():
            py_type = type_map.get(prop.get("type"), str)
            # Якщо параметр обов'язковий (... = Ellipsis) — як @NotNull у Java
            # Якщо опціональний — Optional[type] зі значенням за замовчуванням
            default = ... if name in required else prop.get("default")
            fields[name] = (
                py_type if name in required else Optional[py_type],
                Field(default=default, description=prop.get("description", "")),
            )

        # create_model() — динамічно створює Pydantic клас зі схеми
        # Аналогія Java: генерація класу через reflection або Lombok @Data
        args_model = create_model(f"{tool.name}_args", **fields) if fields else None

        # Closure: кожен tool захоплює свою назву і клієнт
        # _name і _client в default args — стандартний Python pattern для closures
        # (без default args всі closures захопили б останні значення з циклу)
        _name = tool.name
        _client = mcp_client

        # async функція виклику — async бо fastmcp.Client.call_tool() — coroutine
        # Аналогія Java: CompletableFuture<String> invoke(...)
        async def _invoke(_name=_name, _client=_client, **kwargs):
            """Async виклик MCP tool через client."""
            result = await _client.call_tool(_name, kwargs)
            # call_tool повертає список TextContent/ImageContent — беремо текст
            return str(result)

        # StructuredTool.from_function() — фабричний метод LangChain
        # coroutine= замість func= означає async tool
        lc_tools.append(StructuredTool.from_function(
            coroutine=_invoke,
            name=tool.name,
            description=tool.description or tool.name,
            args_schema=args_model,
        ))

    return lc_tools
