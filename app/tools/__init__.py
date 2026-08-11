"""Herramientas del chatbot (estilo OpenAI tools / MCP interno)."""

from app.tools.registry import (
    TOOL_DEFINITIONS,
    accion_de_tool,
    nombres_tools,
)

__all__ = [
    "TOOL_DEFINITIONS",
    "accion_de_tool",
    "nombres_tools",
]
