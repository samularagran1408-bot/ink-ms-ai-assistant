"""Metadatos MCP del turno de chat (servidor real + fallback local)."""

from __future__ import annotations

from typing import Any, Optional

from app.config import settings
from app.tools.registry import TOOL_DEFINITIONS, nombres_tools
from app.tools.roles import nombres_permitidos


def descripcion_protocolo() -> dict[str, Any]:
    remoto = bool(settings.MCP_ENABLED and settings.MCP_URL)
    return {
        "nombre": "inklusport-mcp" if remoto else "mcp_interno",
        "estilo": "mcp_streamable_http" if remoto else "openai_tools",
        "que_es": (
            "El chat es cliente del servidor MCP (ink-mcp-inklusport): lista "
            "tools, el LLM las elige y el backend las ejecuta contra Users/Sports "
            "con el JWT del usuario. Las escrituras piden confirmación. Si el MCP "
            "no está, se usan las tools locales del motor."
        ),
        "url": settings.MCP_URL if remoto else None,
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
    roles: Optional[list[str]] = None,
) -> dict[str, Any]:
    usadas = [h for h in (herramientas_usadas or []) if h and h != "catalogo_plataforma"]
    remoto = bool(settings.MCP_ENABLED and settings.MCP_URL)
    return {
        "protocolo": "mcp" if remoto else "mcp_interno",
        "estilo": "mcp_streamable_http" if remoto else "openai_tools",
        "url": settings.MCP_URL if remoto else None,
        "llm_eligio_tools": bool(tool_calling),
        "tools_usadas": usadas,
        "tools_disponibles": sorted(nombres_permitidos(roles or []))
        if roles is not None
        else nombres_tools(),
        "modelo": modelo,
        "fuente": fuente,
        "fallback_si_falla": "motor_local",
        "nota": (
            "Las escrituras no se ejecutan hasta que el usuario responde Confirmo. "
            "Si llm_eligio_tools es false, el clasificador local cubrió el turno."
        ),
    }
