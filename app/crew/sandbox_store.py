"""Store fake en memoria + JSON local.

Nunca importa httpx ni llama a Users/Sports. Si este archivo cambia y
GET /api/events no, el sandbox está haciendo su trabajo.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from threading import Lock
from typing import Any, Optional

_LOCK = Lock()
_RUTA = Path(__file__).resolve().parent / "sandbox_data.json"

_VACIO: dict[str, Any] = {
    "siguiente_id": 1,
    "eventos": [],
    "deportes": [],
    "discapacidades": [],
    "usuarios": [],
}

_estado: dict[str, Any] = deepcopy(_VACIO)


def _cargar() -> None:
    """Lee el JSON si existe; si no, deja el estado vacío en memoria."""
    if not _RUTA.is_file():
        return
    try:
        datos = json.loads(_RUTA.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(datos, dict):
        return
    _estado["siguiente_id"] = int(datos.get("siguiente_id") or 1)
    for clave in ("eventos", "deportes", "discapacidades", "usuarios"):
        _estado[clave] = list(datos.get(clave) or [])


def _guardar() -> None:
    """Persiste el store para que puedas abrirlo en el editor y verlo."""
    _RUTA.write_text(
        json.dumps(_estado, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


_cargar()


def reset() -> None:
    """Vacía el sandbox (útil en demos). No afecta MySQL ni Sports."""
    with _LOCK:
        _estado.clear()
        _estado.update(deepcopy(_VACIO))
        _guardar()


def listar(coleccion: str) -> list[dict[str, Any]]:
    """Copia de una colección fake."""
    with _LOCK:
        return list(_estado.get(coleccion) or [])


def listar_eventos() -> list[dict[str, Any]]:
    """Copia de los eventos fake."""
    return listar("eventos")


def insertar(coleccion: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Inserta un registro solo en este store."""
    with _LOCK:
        eid = int(_estado.get("siguiente_id") or 1)
        _estado["siguiente_id"] = eid + 1
        registro = {"id": eid, **payload}
        _estado.setdefault(coleccion, []).append(registro)
        _guardar()
        return dict(registro)


def crear_evento(payload: dict[str, Any]) -> dict[str, Any]:
    """Inserta un evento fake."""
    return insertar("eventos", payload)


def actualizar(coleccion: str, eid: int, campos: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Actualiza por id. None si no existe."""
    with _LOCK:
        for item in _estado.get(coleccion) or []:
            if int(item.get("id") or 0) == int(eid):
                item.update(campos)
                _guardar()
                return dict(item)
        return None
