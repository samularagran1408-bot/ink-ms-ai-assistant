"""Tools de escritura FAKE. No hay POST/PUT/PATCH/DELETE a :3002 ni :3003.

Estas mutaciones no afectan la plataforma real. Confirmación = writes.py.
"""

from __future__ import annotations

import json
from typing import Any

from crewai.tools import tool

from app.crew import sandbox_store
from app.crew.ctx import confirmacion_sesion, log_taller
from app.tools.writes import es_confirmacion, mensaje_pedir_confirmacion


def _texto(datos: dict[str, Any]) -> str:
    return json.dumps(datos, ensure_ascii=False, default=str)[:4000]


def _autorizado(confirmacion: str) -> bool:
    return es_confirmacion(confirmacion) or es_confirmacion(confirmacion_sesion())


def _pendiente(accion: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "success": False,
        "via": "sandbox",
        "accion": accion,
        "pendiente_confirmacion": True,
        "mensaje": mensaje_pedir_confirmacion(accion, payload),
        "payload": payload,
    }


def _ok(accion: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "via": "sandbox", "accion": accion, "payload": payload}


def _mutar(
    accion: str,
    payload: dict[str, Any],
    confirmacion: str,
    escribir,
) -> dict[str, Any]:
    log_taller(f"👉 [SANDBOX Tool] {accion} payload={payload!r}")
    if not _autorizado(confirmacion):
        return _pendiente(accion, payload)
    return _ok(accion, escribir())


@tool("crear_evento_sandbox")
def crear_evento_sandbox(
    name: str,
    event_date: str,
    confirmacion: str = "",
) -> str:
    """Simula crear un evento. NO toca Sports real. Sin Confirmo no escribe."""
    args = {"name": name, "event_date": event_date}
    return _texto(
        _mutar("crear_evento", args, confirmacion, lambda: sandbox_store.crear_evento(args))
    )


@tool("cancelar_evento_sandbox")
def cancelar_evento_sandbox(event_id: int, confirmacion: str = "") -> str:
    """Simula cancelar un evento del sandbox (status=cancelled)."""
    args = {"event_id": event_id}

    def _write() -> dict[str, Any]:
        actual = sandbox_store.actualizar("eventos", event_id, {"status": "cancelled"})
        return actual or {"error": "evento no encontrado en sandbox", "event_id": event_id}

    return _texto(_mutar("cancelar_evento", args, confirmacion, _write))


@tool("crear_deporte_sandbox")
def crear_deporte_sandbox(name: str, confirmacion: str = "") -> str:
    """Simula crear un deporte. NO toca el catálogo real."""
    args = {"name": name}
    return _texto(
        _mutar(
            "crear_deporte",
            args,
            confirmacion,
            lambda: sandbox_store.insertar("deportes", args),
        )
    )


@tool("eliminar_deporte_sandbox")
def eliminar_deporte_sandbox(sport_id: int, confirmacion: str = "") -> str:
    """Simula marcar un deporte sandbox como eliminado."""
    args = {"sport_id": sport_id}

    def _write() -> dict[str, Any]:
        actual = sandbox_store.actualizar("deportes", sport_id, {"eliminado": True})
        return actual or {"error": "deporte no encontrado en sandbox", "sport_id": sport_id}

    return _texto(_mutar("eliminar_deporte", args, confirmacion, _write))


@tool("registrar_discapacidad_sandbox")
def registrar_discapacidad_sandbox(name: str, confirmacion: str = "") -> str:
    """Simula registrar un tipo de discapacidad. NO toca Users/Sports."""
    args = {"name": name}
    return _texto(
        _mutar(
            "registrar_discapacidad",
            args,
            confirmacion,
            lambda: sandbox_store.insertar("discapacidades", args),
        )
    )


@tool("bloquear_usuario_sandbox")
def bloquear_usuario_sandbox(nombre_o_email: str, confirmacion: str = "") -> str:
    """Simula bloquear un usuario. NO llama a Users :3002."""
    args = {"nombre_o_email": nombre_o_email, "bloqueado": True}
    return _texto(
        _mutar(
            "bloquear_usuario",
            args,
            confirmacion,
            lambda: sandbox_store.insertar("usuarios", args),
        )
    )


@tool("listar_sandbox")
def listar_sandbox() -> str:
    """Lista el store fake (eventos/deportes/discapacidades/usuarios). Lectura sandbox."""
    log_taller("👉 [SANDBOX Tool] listar_sandbox")
    datos = {
        "success": True,
        "via": "sandbox",
        "accion": "listar",
        "payload": {
            "eventos": sandbox_store.listar("eventos"),
            "deportes": sandbox_store.listar("deportes"),
            "discapacidades": sandbox_store.listar("discapacidades"),
            "usuarios": sandbox_store.listar("usuarios"),
        },
    }
    return _texto(datos)


TOOLS_SANDBOX = (
    crear_evento_sandbox,
    cancelar_evento_sandbox,
    crear_deporte_sandbox,
    eliminar_deporte_sandbox,
    registrar_discapacidad_sandbox,
    bloquear_usuario_sandbox,
    listar_sandbox,
)


if __name__ == "__main__":
    from app.crew.ctx import set_sesion

    set_sesion(mensaje="")
    log_taller(crear_evento_sandbox.run(name="Copa sandbox", event_date="2026-09-15"))
    set_sesion(mensaje="Confirmo")
    log_taller(
        crear_evento_sandbox.run(
            name="Copa sandbox", event_date="2026-09-15", confirmacion="Confirmo"
        )
    )
    log_taller(listar_sandbox.run())
