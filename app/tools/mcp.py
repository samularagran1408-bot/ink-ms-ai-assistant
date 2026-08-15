"""Metadatos del protocolo interno estilo MCP (tools OpenAI-compatible).

No es un servidor MCP de Cursor: el chatbot de la plataforma expone tools
con schema, el LLM las elige y el backend las ejecuta contra datos reales.
Si el modelo no soporta tools, el motor local hace el mismo trabajo.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import settings
from app.tools.registry import TOOL_DEFINITIONS, nombres_tools


def descripcion_protocolo() -> dict[str, Any]:
    return {
        "nombre": "mcp_interno",
        "estilo": "openai_tools",
        "que_es": (
            "El agente declara herramientas (tools) con nombre, descripción y "
            "parámetros. El LLM puede pedir ejecutarlas; el servidor las corre "
            "en Python (eventos, rutinas, etc.) y devuelve hechos. Eso es el "
            "mismo patrón que MCP, embebido en el chat de InkluSport."
        ),
        "no_es": (
            "No es el MCP de Cursor (Notion/Figma). No hay servidor MCP aparte."
        ),
        "fallback": "motor_local",
        "habilitado": settings.LLM_TOOL_CALLING_ENABLED,
        "max_rondas": settings.LLM_TOOL_MAX_RONDAS,
        "tools": [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
            }
            for t in TOOL_DEFINITIONS
        ],
        "nombres": nombres_tools(),
    }


def mcp_del_turno(
    *,
    tool_calling: bool,
    herramientas_usadas: list[str],
    modelo: Optional[str] = None,
    fuente: str = "motor_local",
) -> dict[str, Any]:
    usadas = [h for h in (herramientas_usadas or []) if h and h != "catalogo_plataforma"]
    return {
        "protocolo": "mcp_interno",
        "estilo": "openai_tools",
        "llm_eligio_tools": bool(tool_calling),
        "tools_usadas": usadas,
        "tools_disponibles": nombres_tools(),
        "modelo": modelo,
        "fuente": fuente,
        "fallback_si_falla": "motor_local",
        "nota": (
            "Si llm_eligio_tools es false, el clasificador local ejecutó la "
            "misma herramienta (mismo dato, sin que el LLM la pidiera)."
        ),
    }
