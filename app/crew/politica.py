"""Política de escritura de InkluSport.

CrewAI (página Crew IA) NUNCA muta Users :3002 ni Sports :3003.
Toda alta/baja/bloqueo del crew va al store fake (via=sandbox) y exige Confirmo.

El chat (POST /api/ai/chat) SÍ puede llamar tools MCP de escritura, también
tras Confirmo. Son dos vías a propósito: sandbox para el taller / demos;
MCP real para el producto.

CREW_WRITE_MODE en .env se ignora si no es sandbox: no hay interruptor a MCP.
"""

from __future__ import annotations

import os
from typing import Any

MODO_CREW = "sandbox"
MODO_CHAT = "mcp"


def modo_escritura_crew() -> str:
    """Siempre sandbox. Si alguien pone mcp en .env, se ignora."""
    pedido = (os.getenv("CREW_WRITE_MODE") or MODO_CREW).strip().lower()
    if pedido and pedido != MODO_CREW:
        print(
            f"CREW_WRITE_MODE={pedido!r} se ignora; las mutaciones del crew "
            f"siguen en {MODO_CREW}.",
            flush=True,
        )
    return MODO_CREW


def descripcion_escritura() -> dict[str, Any]:
    """Contrato para health, GET /dominios y el front."""
    return {
        "crew": modo_escritura_crew(),
        "chat": MODO_CHAT,
        "nota": (
            "CrewAI solo escribe en sandbox_data.json (via=sandbox) tras Confirmo. "
            "No hay POST/PUT/PATCH/DELETE a Users ni Sports. "
            "Las altas reales van por POST /api/ai/chat, también con Confirmo."
        ),
    }


def tools_escritura_crew():
    """Única lista de tools de mutación que puede llevar un Agent de crew."""
    from app.crew.tools_sandbox import TOOLS_SANDBOX

    return list(TOOLS_SANDBOX)
