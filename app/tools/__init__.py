"""Herramientas del chatbot (estilo OpenAI tools / MCP interno)."""

from app.tools.cards import construir_cards
from app.tools.mcp import descripcion_protocolo, mcp_del_turno
from app.tools.registry import (
    TOOL_DEFINITIONS,
    accion_de_tool,
    nombres_tools,
)

__all__ = [
    "TOOL_DEFINITIONS",
    "accion_de_tool",
    "construir_cards",
    "descripcion_protocolo",
    "mcp_del_turno",
    "nombres_tools",
]
