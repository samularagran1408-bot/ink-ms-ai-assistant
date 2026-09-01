"""Limpieza de datos efímeros del asistente.

Conserva catálogos (ejercicios, conocimiento, banco de quiz) y el modo
competencia (1 documento por usuario). Borra chats, quizzes, alertas,
planes generados y RPE cuando vencen.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings
from app.database.mongodb import get_db
from app.database.repositorio import (
    COL_ALERTAS,
    COL_CONVERSACIONES,
    COL_PLANES,
    COL_QUIZZES,
    COL_SESIONES_RPE,
)


def _ahora() -> datetime:
    """Instante actual en UTC, usado como referencia de vencimiento."""
    return datetime.now(timezone.utc)


def filtro_anterior(campo: str, cutoff: datetime) -> dict[str, Any]:
    """Filtro `$or` que cubre Date nativo de Mongo y strings ISO guardados por el código."""
    return {
        "$or": [
            {campo: {"$lt": cutoff}},
            {campo: {"$lt": cutoff.isoformat()}},
        ]
    }


async def _borrar(coleccion: str, filtro: dict[str, Any]) -> int:
    """Borra los documentos que cumplen el filtro; 0 si no hay conexión."""
    db = get_db()
    if db is None:
        return 0
    resultado = await db[coleccion].delete_many(filtro)
    return int(resultado.deleted_count or 0)


def _parse_fecha(valor: Any) -> datetime | None:
    """Convierte datetime o ISO a UTC; None si el valor no es una fecha reconocible."""
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    if not valor:
        return None
    try:
        parsed = datetime.fromisoformat(str(valor))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _purgar_quizzes_memoria(now: datetime) -> int:
    """Elimina quizzes vencidos del almacén en memoria del agente y devuelve cuántos quitó."""
    try:
        from app.agents.quiz_agent import _QUIZ_STORE
    except Exception:
        return 0
    activo = timedelta(hours=settings.RETENCION_QUIZ_ACTIVO_HORAS)
    evaluado = timedelta(hours=settings.RETENCION_QUIZ_EVALUADO_HORAS)
    stale: list[str] = []
    for quiz_id, doc in list(_QUIZ_STORE.items()):
        if not isinstance(doc, dict):
            stale.append(quiz_id)
            continue
        if doc.get("estado") == "evaluado":
            marca = _parse_fecha(doc.get("evaluado_en") or doc.get("creado_en"))
            limite = now - evaluado
        else:
            marca = _parse_fecha(doc.get("creado_en"))
            limite = now - activo
        if marca is None or marca < limite:
            stale.append(quiz_id)
    for quiz_id in stale:
        _QUIZ_STORE.pop(quiz_id, None)
    return len(stale)


async def purgar_datos_efimeros() -> dict[str, int]:
    """Borra chats, quizzes, alertas, planes y RPE vencidos; no toca catálogos ni competencia."""
    now = _ahora()
    quizzes_memoria = _purgar_quizzes_memoria(now)
    if get_db() is None:
        return {
            "conversaciones": 0,
            "quizzes": 0,
            "quizzes_memoria": quizzes_memoria,
            "alertas": 0,
            "planes": 0,
            "sesiones_rpe": 0,
        }

    chat_cutoff = now - timedelta(hours=settings.RETENCION_CHAT_HORAS)
    quiz_activo = now - timedelta(hours=settings.RETENCION_QUIZ_ACTIVO_HORAS)
    quiz_eval = now - timedelta(hours=settings.RETENCION_QUIZ_EVALUADO_HORAS)
    alertas_cutoff = now - timedelta(hours=settings.RETENCION_ALERTAS_HORAS)
    planes_cutoff = now - timedelta(hours=settings.RETENCION_PLANES_HORAS)
    rpe_cutoff = now - timedelta(hours=settings.RETENCION_RPE_HORAS)

    quizzes_activos = await _borrar(
        COL_QUIZZES,
        {"$and": [{"estado": {"$ne": "evaluado"}}, filtro_anterior("creado_en", quiz_activo)]},
    )
    quizzes_eval = await _borrar(
        COL_QUIZZES,
        {"$and": [{"estado": "evaluado"}, filtro_anterior("evaluado_en", quiz_eval)]},
    )
    quizzes_eval_legacy = await _borrar(
        COL_QUIZZES,
        {
            "$and": [
                {"estado": "evaluado"},
                {"evaluado_en": {"$exists": False}},
                filtro_anterior("creado_en", quiz_eval),
            ]
        },
    )
    chats_inactivas = await _borrar(
        COL_CONVERSACIONES, filtro_anterior("ultima_interaccion", chat_cutoff)
    )
    chats_sin_actividad = await _borrar(
        COL_CONVERSACIONES,
        {
            "$and": [
                {"ultima_interaccion": {"$exists": False}},
                filtro_anterior("creada_en", chat_cutoff),
            ]
        },
    )
    return {
        "conversaciones": chats_inactivas + chats_sin_actividad,
        "quizzes": quizzes_activos + quizzes_eval + quizzes_eval_legacy,
        "quizzes_memoria": quizzes_memoria,
        "alertas": await _borrar(COL_ALERTAS, filtro_anterior("creado_en", alertas_cutoff)),
        "planes": await _borrar(COL_PLANES, filtro_anterior("creado_en", planes_cutoff)),
        "sesiones_rpe": await _borrar(COL_SESIONES_RPE, filtro_anterior("fecha", rpe_cutoff)),
    }


async def bucle_retencion() -> None:
    """Tarea infinita que ejecuta la purga cada `RETENCION_INTERVALO_SEGUNDOS`."""
    intervalo = max(60, settings.RETENCION_INTERVALO_SEGUNDOS)
    await asyncio.sleep(20)
    while True:
        try:
            resumen = await purgar_datos_efimeros()
            borrados = {clave: valor for clave, valor in resumen.items() if valor}
            if borrados:
                print(f"Retención AI: {borrados}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"Error en retención AI: {exc}")
        await asyncio.sleep(intervalo)
