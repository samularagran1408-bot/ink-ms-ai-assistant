"""Perfil de entrenamiento del atleta (sesión, alertas, preferencias)."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

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


def _parse_iso(valor: Any) -> Optional[datetime]:
    """ISO-8601 a datetime UTC, o None si no se puede leer."""
    if not valor:
        return None
    try:
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def alertas_en_semana(perfil: dict[str, Any], ahora: Optional[datetime] = None) -> list[dict[str, Any]]:
    """Alertas de riesgo del perfil en los últimos 7 días."""
    ahora = ahora or datetime.now(timezone.utc)
    limite = ahora - timedelta(days=7)
    recientes: list[dict[str, Any]] = []
    for item in perfil.get("alertas_riesgo") or []:
        if not isinstance(item, dict):
            continue
        fecha = _parse_iso(item.get("fecha"))
        if fecha and fecha >= limite:
            recientes.append(item)
    return recientes


def registrar_alerta_riesgo(
    perfil: dict[str, Any],
    tipo: str,
    detalle: str = "",
) -> dict[str, Any]:
    """Añade una alerta de riesgo y dice si hay que avisar al usuario (CP33-HU50)."""
    ahora = datetime.now(timezone.utc)
    perfil.setdefault("alertas_riesgo", []).append({
        "tipo": tipo,
        "detalle": detalle,
        "fecha": ahora.isoformat(),
    })
    umbrales = perfil.get("umbrales") if isinstance(perfil.get("umbrales"), dict) else {}
    umbral = int(umbrales.get("alertas_semana") or 3)
    semana = alertas_en_semana(perfil, ahora)
    ultimo = _parse_iso(perfil.get("aviso_umbral_semana_en"))
    ya_avisado = bool(ultimo and ultimo >= ahora - timedelta(days=7))
    silenciado = _parse_iso(perfil.get("silenciado_hasta"))
    en_silencio = bool(silenciado and silenciado > ahora)
    return {
        "count": len(semana),
        "umbral": umbral,
        "debe_avisar": len(semana) >= umbral and not ya_avisado and not en_silencio,
        "ya_avisado": ya_avisado,
        "en_silencio": en_silencio,
    }


def marcar_aviso_umbral(perfil: dict[str, Any]) -> None:
    """Marca que ya se envió el aviso semanal de 3 alertas."""
    perfil["aviso_umbral_semana_en"] = datetime.now(timezone.utc).isoformat()


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
