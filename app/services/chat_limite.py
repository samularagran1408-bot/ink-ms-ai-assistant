"""Cupos de chat: un turno a la vez y tope de mensajes por hora.

Evita que el mismo JWT dispare varios POST /chat a la vez (doble clic,
reintentos del front) y avisa de verdad al llegar al límite horario.
"""

from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import HTTPException

from app.config import settings

_en_curso: dict[str, int] = defaultdict(int)
_envios: dict[str, deque[float]] = defaultdict(deque)
_bloqueo_hasta: dict[str, float] = {}


def _ahora() -> float:
    """Epoch en segundos (inyectable en pruebas parcheando este símbolo)."""
    import time

    return time.time()


def _cupo_inflight() -> int:
    """Turnos simultáneos permitidos por usuario (mínimo 1)."""
    return max(1, settings.CHAT_MAX_INFLIGHT_PER_USER)


def _max_hora() -> int:
    """Mensajes de usuario permitidos por ventana horaria."""
    return max(1, settings.CHAT_MAX_MENSAJES_POR_HORA)


def _espera() -> int:
    """Segundos de bloqueo tras superar el cupo horario."""
    return max(1, settings.CHAT_ESPERA_LIMITE_SEGUNDOS)


def _aviso_desde() -> int:
    """A partir de cuántos mensajes restantes se muestra el aviso preventivo."""
    return max(1, settings.CHAT_AVISO_RESTANTES)


def _purgar(usuario_id: str, ahora: Optional[float] = None) -> None:
    """Tira envíos de hace más de una hora y levanta el bloqueo si ya pasó."""
    ahora = _ahora() if ahora is None else ahora
    cola = _envios.get(usuario_id)
    if cola:
        corte = ahora - 3600
        while cola and cola[0] <= corte:
            cola.popleft()
        if not cola:
            _envios.pop(usuario_id, None)
    hasta = _bloqueo_hasta.get(usuario_id, 0.0)
    if hasta and ahora >= hasta:
        _bloqueo_hasta.pop(usuario_id, None)
        _envios.pop(usuario_id, None)


def _fmt_espera(segundos: int) -> str:
    """Texto corto de espera (p. ej. «1 hora», «1 h 20 min»)."""
    segundos = max(1, int(segundos))
    horas, resto = divmod(segundos, 3600)
    minutos, segs = divmod(resto, 60)
    if horas >= 2 and minutos == 0 and segs == 0:
        return f"{horas} horas"
    if horas == 1 and minutos == 0 and segs == 0:
        return "1 hora"
    if horas >= 1 and minutos >= 1:
        return f"{horas} h {minutos} min"
    if horas >= 1:
        return f"{horas} h"
    if minutos >= 2 and segs == 0:
        return f"{minutos} minutos"
    if minutos == 1 and segs == 0:
        return "1 minuto"
    if minutos >= 1:
        return f"{minutos} min {segs} s"
    return f"{segs} s"


def estado_cupo(usuario_id: str) -> dict[str, Any]:
    """Snapshot del cupo horario (no consume un envío)."""
    clave = (usuario_id or "").strip()
    ahora = _ahora()
    if clave:
        _purgar(clave, ahora)
    usados = len(_envios.get(clave, ())) if clave else 0
    maximo = _max_hora()
    restantes = max(0, maximo - usados)
    espera = _espera()
    bloqueado = 0
    if clave:
        bloqueado = max(0, int(_bloqueo_hasta.get(clave, 0.0) - ahora))
    aviso = None
    if bloqueado > 0:
        aviso = (
            f"Llegaste al límite de {maximo} mensajes por hora. "
            f"Espera {_fmt_espera(bloqueado)} antes de volver a enviar."
        )
    elif restantes <= 0:
        aviso = (
            f"Has usado los {maximo} mensajes de esta hora. "
            f"El siguiente envío tendrá una espera de {_fmt_espera(espera)}."
        )
    elif restantes <= _aviso_desde():
        aviso = (
            f"Aviso: te quedan {restantes} mensaje"
            f"{'s' if restantes != 1 else ''} de {maximo} en esta hora. "
            f"Si llegas al tope, esperarás {_fmt_espera(espera)}."
        )
    return {
        "usados": usados,
        "maximo": maximo,
        "restantes": restantes,
        "ventana_segundos": 3600,
        "espera_segundos": espera,
        "retry_after_segundos": bloqueado or None,
        "aviso": aviso,
    }


def _lanzar_limite(estado: dict[str, Any]) -> None:
    """HTTP 429 con el aviso de espera para el front."""
    espera = int(estado.get("retry_after_segundos") or estado.get("espera_segundos") or _espera())
    mensaje = estado.get("aviso") or (
        f"Llegaste al límite de {estado.get('maximo')} mensajes por hora. "
        f"Espera {_fmt_espera(espera)} antes de volver a enviar."
    )
    raise HTTPException(
        status_code=429,
        detail={
            "codigo": "chat_limite_hora",
            "mensaje": mensaje,
            "retry_after_segundos": espera,
            "usados": estado.get("usados"),
            "maximo": estado.get("maximo"),
        },
        headers={"Retry-After": str(espera)},
    )


def consumir_cupo_hora(usuario_id: str) -> dict[str, Any]:
    """Registra un envío o lanza 429 si el usuario llegó al tope horario."""
    clave = (usuario_id or "").strip()
    if not clave:
        return estado_cupo("")
    ahora = _ahora()
    _purgar(clave, ahora)
    if _bloqueo_hasta.get(clave, 0.0) > ahora:
        _lanzar_limite(estado_cupo(clave))
    if len(_envios[clave]) >= _max_hora():
        _bloqueo_hasta[clave] = ahora + _espera()
        _lanzar_limite(estado_cupo(clave))
    _envios[clave].append(ahora)
    return estado_cupo(clave)


def reservar(usuario_id: str) -> None:
    """Marca un turno en curso o lanza 429 si el usuario ya está al cupo."""
    clave = (usuario_id or "").strip()
    if not clave:
        return
    if _en_curso[clave] >= _cupo_inflight():
        raise HTTPException(
            status_code=429,
            detail={
                "codigo": "chat_ocupado",
                "mensaje": (
                    "Ya hay una respuesta en curso. Espera a que termine "
                    "antes de enviar otro mensaje."
                ),
                "retry_after_segundos": 5,
            },
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
