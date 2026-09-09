"""Cupo de turnos de chat simultáneos por usuario.

Evita que el mismo JWT dispare varios POST /chat a la vez (doble clic,
reintentos del front) y sature el LLM o el motor local.
"""

from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import HTTPException

from app.config import settings

_en_curso: dict[str, int] = defaultdict(int)


def _cupo() -> int:
    """Turnos simultáneos permitidos por usuario (mínimo 1)."""
    return max(1, settings.CHAT_MAX_INFLIGHT_PER_USER)


def reservar(usuario_id: str) -> None:
    """Marca un turno en curso o lanza 429 si el usuario ya está al cupo."""
    clave = (usuario_id or "").strip()
    if not clave:
        return
    if _en_curso[clave] >= _cupo():
        raise HTTPException(
            status_code=429,
            detail=(
                "Ya hay una respuesta en curso. Espera a que termine "
                "antes de enviar otro mensaje."
            ),
        )
    _en_curso[clave] += 1


def liberar(usuario_id: str) -> None:
    """Libera un turno reservado del usuario."""
    clave = (usuario_id or "").strip()
    if not clave:
        return
    restante = _en_curso.get(clave, 1) - 1
    if restante <= 0:
        _en_curso.pop(clave, None)
    else:
        _en_curso[clave] = restante


@asynccontextmanager
async def turno_usuario(usuario_id: str):
    """Reserva el cupo durante un POST /chat síncrono."""
    reservar(usuario_id)
    try:
        yield
    finally:
        liberar(usuario_id)
