"""Sesión del crew: JWT, usuario y discapacidad del token (no se imprimen)."""

from __future__ import annotations

import asyncio
import threading
from contextvars import ContextVar
from typing import Any, Callable, Coroutine, Optional

from app.tools.writes import es_confirmacion

_authorization: ContextVar[Optional[str]] = ContextVar("crew_auth", default=None)
_usuario_id: ContextVar[Optional[str]] = ContextVar("crew_uid", default=None)
_discapacidad: ContextVar[str] = ContextVar("crew_disc", default="general")
_confirmacion: ContextVar[str] = ContextVar("crew_confirma", default="")


def set_sesion(
    authorization: Optional[str] = None,
    usuario_id: Optional[str] = None,
    discapacidad: Optional[str] = None,
    mensaje: Optional[str] = None,
) -> None:
    """Fija JWT y perfil para las tools de este kickoff."""
    _authorization.set(authorization)
    _usuario_id.set(usuario_id)
    _discapacidad.set(discapacidad or "general")
    _confirmacion.set("Confirmo" if es_confirmacion(mensaje or "") else "")


def authorization() -> Optional[str]:
    """Bearer JWT de la petición, o None."""
    return _authorization.get()


def usuario_id() -> Optional[str]:
    """Id del usuario autenticado (para perfil / competencia / consulta)."""
    return _usuario_id.get()


def discapacidad() -> str:
    """Discapacidad canónica del token, o general."""
    return _discapacidad.get() or "general"


def confirmacion_sesion() -> str:
    """«Confirmo» si el mensaje del usuario autoriza (estilo writes.py)."""
    return _confirmacion.get() or ""


def log_taller(msg: str) -> None:
    """Print del taller. En consolas cp1252 cae a ASCII."""
    try:
        print(msg, flush=True)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"), flush=True)


def correr_async(factory: Callable[[], Coroutine[Any, Any, Any]]) -> Any:
    """Ejecuta una corrutina desde una tool síncrona de CrewAI."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    caja: dict[str, Any] = {}

    def _en_hilo() -> None:
        caja["r"] = asyncio.run(factory())

    hilo = threading.Thread(target=_en_hilo, daemon=True)
    hilo.start()
    hilo.join()
    return caja.get("r")
