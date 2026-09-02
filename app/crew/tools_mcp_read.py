"""Tools MCP de LECTURA para crews de consulta.

Envuelven ``llamar_tool`` (GET). No hay POST/PUT/PATCH/DELETE.
``via`` debe ser ``"mcp"``. Las escrituras van al sandbox, no aquí.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from crewai.tools import tool

from app.crew.ctx import authorization as jwt_sesion
from app.crew.ctx import correr_async, log_taller, set_sesion
from app.services.mcp_client import llamar_tool
from app.tools.writes import WRITE_TOOLS

TOOLS_LECTURA_INVESTIGACION = (
    "consultar_dashboard",
    "contar_usuarios",
    "listar_usuarios",
    "consultar_auditoria",
    "listar_eventos",
    "listar_deportes",
    "listar_discapacidades",
)


def set_authorization(token: Optional[str]) -> None:
    """Compat: guarda el JWT (preferir ``ctx.set_sesion``)."""
    set_sesion(authorization=token)


def _llamar_lectura(nombre: str, argumentos: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Llama MCP solo si ``nombre`` no está en WRITE_TOOLS."""
    args = dict(argumentos or {})
    log_taller(f"👉 [Tool] {nombre} args={args!r}")

    if nombre in WRITE_TOOLS:
        return {
            "success": False,
            "via": "crew",
            "error": f"{nombre} es escritura; no está en tools_mcp_read",
        }

    auth = jwt_sesion()

    async def _go() -> dict[str, Any]:
        return await llamar_tool(nombre, args, auth)

    datos = correr_async(_go)
    if not isinstance(datos, dict):
        return {"success": True, "via": "mcp", "data": datos}
    if "via" not in datos:
        datos = {**datos, "via": "mcp"}
    return datos


def _texto(datos: dict[str, Any]) -> str:
    """JSON acotado: CrewAI espera string y el contexto del LLM no es infinito."""
    return json.dumps(datos, ensure_ascii=False, default=str)[:6000]


@tool("consultar_dashboard")
def consultar_dashboard() -> str:
    """Métricas del dashboard de InkluSport (lectura MCP GET)."""
    return _texto(_llamar_lectura("consultar_dashboard"))


@tool("contar_usuarios")
def contar_usuarios() -> str:
    """Cuenta usuarios registrados (lectura MCP GET)."""
    return _texto(_llamar_lectura("contar_usuarios"))


@tool("listar_usuarios")
def listar_usuarios() -> str:
    """Lista usuarios de la plataforma (lectura MCP GET)."""
    return _texto(_llamar_lectura("listar_usuarios"))


@tool("consultar_auditoria")
def consultar_auditoria() -> str:
    """Consulta la auditoría administrativa (lectura MCP GET)."""
    return _texto(_llamar_lectura("consultar_auditoria"))


@tool("listar_eventos")
def listar_eventos() -> str:
    """Lista eventos deportivos publicados (lectura MCP GET). Devuelve JSON con via=mcp."""
    return _texto(_llamar_lectura("listar_eventos"))


@tool("listar_deportes")
def listar_deportes() -> str:
    """Lista deportes del catálogo (lectura MCP GET)."""
    return _texto(_llamar_lectura("listar_deportes"))


@tool("listar_discapacidades")
def listar_discapacidades() -> str:
    """Lista tipos de discapacidad (lectura MCP GET)."""
    return _texto(_llamar_lectura("listar_discapacidades"))


@tool("listar_eventos_disponibles")
def listar_eventos_disponibles() -> str:
    """Eventos abiertos a inscripción (lectura MCP GET)."""
    return _texto(_llamar_lectura("listar_eventos_disponibles"))


@tool("listar_rutinas_publicadas")
def listar_rutinas_publicadas() -> str:
    """Rutinas publicadas en la plataforma (lectura MCP GET)."""
    return _texto(_llamar_lectura("listar_rutinas_publicadas"))


@tool("consultar_usuario")
def consultar_usuario(user_id_o_email: str = "") -> str:
    """Perfil de una persona por nombre, id o email (lectura MCP GET)."""
    args: dict[str, Any] = {}
    if user_id_o_email.strip():
        args["user_id_o_email"] = user_id_o_email.strip()
    return _texto(_llamar_lectura("consultar_usuario", args))


@tool("consultar_inscripciones")
def consultar_inscripciones(user_id: str = "") -> str:
    """Inscripciones a eventos de un usuario (lectura MCP GET)."""
    args: dict[str, Any] = {}
    if user_id.strip():
        args["user_id"] = user_id.strip()
    return _texto(_llamar_lectura("consultar_inscripciones", args))


@tool("listar_adaptaciones_deporte")
def listar_adaptaciones_deporte(sport_id: int = 1) -> str:
    """Adaptaciones deporte-discapacidad (lectura MCP GET)."""
    return _texto(_llamar_lectura("listar_adaptaciones_deporte", {"sport_id": sport_id}))


TOOLS_INVESTIGACION = (
    consultar_dashboard,
    contar_usuarios,
    listar_usuarios,
    consultar_auditoria,
    listar_eventos,
    listar_deportes,
    listar_discapacidades,
)

TOOLS_COMPETENCIA_MCP = (
    listar_eventos_disponibles,
    listar_rutinas_publicadas,
)

TOOLS_CONSULTA_MCP = (
    consultar_usuario,
    consultar_inscripciones,
    listar_eventos,
    listar_deportes,
    listar_adaptaciones_deporte,
)


if __name__ == "__main__":
    import os

    jwt = os.getenv("CREW_JWT")
    if jwt:
        set_authorization(jwt if jwt.startswith("Bearer ") else f"Bearer {jwt}")

    def _mostrar(titulo: str, datos: dict[str, Any]) -> None:
        log_taller(titulo)
        log_taller(f"via={datos.get('via')!r} success={datos.get('success')!r}")
        log_taller(json.dumps(datos, ensure_ascii=False, default=str)[:2000])

    _mostrar("--- listar_eventos ---", _llamar_lectura("listar_eventos"))
    _mostrar("--- consultar_dashboard ---", _llamar_lectura("consultar_dashboard"))
    log_taller("(Si MCP no está en :8000 verás via='mcp' y success=false; no es sandbox.)")
