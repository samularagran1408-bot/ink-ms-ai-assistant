"""Perfil de entrenamiento del atleta (sesión, alertas, preferencias)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from app.database.mongodb import get_db
from app.database.repositorio import COL_ENTRENAMIENTO

_MEMORIA: dict[str, dict[str, Any]] = {}


def perfil_vacio(usuario_id: str) -> dict[str, Any]:
    """Estado inicial de sesión para un usuario."""
    return {
        "usuario_id": usuario_id,
        "estado_sesion": "idle",
        "voz_activa": False,
        "ejercicio_activo": None,
        "tipo_ejercicio": "fuerza",
        "variante_actual": None,
        "adaptaciones_rechazadas": [],
        "preferencias_adaptacion": [],
        "alertas_riesgo": [],
        "fatiga_pendiente": False,
        "fatiga_sugeridas": 0,
        "fatiga_ignoradas": 0,
        "sesiones_cerradas": [],
        "series_metricas": [],
        "mejor_marca": None,
        "marca_actual": None,
        "modo_vs_pb": False,
        "ratings_eventos": [],
        "ultima_recomendacion_en": None,
        "primera_sesion_hecha": False,
        "sugerencias_a11y": [],
        "decisiones_a11y": [],
        "umbrales": {"rpe": 8, "alertas_semana": 3, "fatiga_ignora": 3},
        "silenciado_hasta": None,
        "plan_ajuste": None,
        "medallas": [],
        "notificaciones": [],
        "actualizado": datetime.now(timezone.utc).isoformat(),
    }


def reset_memoria() -> None:
    """Limpia el cache en memoria (tests)."""
    _MEMORIA.clear()


async def cargar_perfil(usuario_id: str) -> dict[str, Any]:
    """Lee el perfil de Mongo o memoria; crea uno vacío si no existe."""
    clave = str(usuario_id or "").strip() or "anon"
    db = get_db()
    if db is not None:
        try:
            doc = await db[COL_ENTRENAMIENTO].find_one({"usuario_id": clave}, {"_id": 0})
            if isinstance(doc, dict):
                base = perfil_vacio(clave)
                base.update(doc)
                _MEMORIA[clave] = base
                return base
        except Exception as exc:
            print(f"Error leyendo perfil entrenamiento: {exc}")
    if clave not in _MEMORIA:
        _MEMORIA[clave] = perfil_vacio(clave)
    return deepcopy(_MEMORIA[clave])


async def guardar_perfil(perfil: dict[str, Any]) -> dict[str, Any]:
    """Persiste el perfil en memoria y, si hay Mongo, en la colección."""
    perfil = dict(perfil)
    perfil["actualizado"] = datetime.now(timezone.utc).isoformat()
    clave = str(perfil.get("usuario_id") or "anon")
    perfil["usuario_id"] = clave
    _MEMORIA[clave] = deepcopy(perfil)
    db = get_db()
    if db is not None:
        try:
            await db[COL_ENTRENAMIENTO].replace_one(
                {"usuario_id": clave}, perfil, upsert=True
            )
        except Exception as exc:
            print(f"Error guardando perfil entrenamiento: {exc}")
    return perfil
