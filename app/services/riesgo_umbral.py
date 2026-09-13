"""Umbral semanal de evaluaciones de riesgo (CP33-HU50)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.database.mongodb import get_db
from app.database.repositorio import COL_EVALUACIONES_RIESGO
from app.services.accessibility_service import AccessibilityService
from app.services.entrenamiento_store import (
    _parse_iso,
    cargar_perfil,
    guardar_perfil,
    marcar_aviso_umbral,
)

UMBRAL_DEFAULT = 3
_accessibility = AccessibilityService()


def _limite_semana(ahora: Optional[datetime] = None) -> datetime:
    ahora = ahora or datetime.now(timezone.utc)
    return ahora - timedelta(days=7)


async def conteo_historial_semana(usuario_id: str, email: Optional[str] = None) -> int:
    """Cuántas evaluaciones hay en el historial de los últimos 7 días."""
    db = get_db()
    if db is None:
        return 0
    limite = _limite_semana()
    ids = [str(usuario_id)]
    if email and str(email) not in ids:
        ids.append(str(email))
    try:
        cursor = (
            db[COL_EVALUACIONES_RIESGO]
            .find({"usuario_id": {"$in": ids}}, {"_id": 0, "fecha": 1})
            .sort("fecha", -1)
            .limit(50)
        )
        docs = await cursor.to_list(length=50)
    except Exception as exc:
        print(f"No se pudo contar evaluaciones de riesgo: {exc}")
        return 0
    total = 0
    for doc in docs:
        fecha = _parse_iso(doc.get("fecha"))
        if fecha and fecha >= limite:
            total += 1
    return total


def estado_umbral(perfil: dict[str, Any], count: int) -> dict[str, Any]:
    """Avisa al cruzar exactamente 3 riesgos. Si bajas de 3, se puede volver a avisar."""
    umbrales = perfil.get("umbrales") if isinstance(perfil.get("umbrales"), dict) else {}
    umbral = int(umbrales.get("alertas_semana") or UMBRAL_DEFAULT)
    silenciado = _parse_iso(perfil.get("silenciado_hasta"))
    en_silencio = bool(silenciado and silenciado > datetime.now(timezone.utc))
    ya_avisado = bool(perfil.get("aviso_umbral_semana_en")) and count >= umbral
    return {
        "count": count,
        "umbral": umbral,
        "debe_avisar": count == umbral and not ya_avisado and not en_silencio,
        "ya_avisado": ya_avisado,
        "en_silencio": en_silencio,
        "canales": ["push", "email"],
        "notificado": False,
    }


async def enviar_aviso_umbral(
    usuario_id: str,
    pack: dict[str, Any],
    *,
    email: Optional[str] = None,
    authorization: Optional[str] = None,
    perfil: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Crea notificación in-app (push) + correo al usuario evaluado."""
    titulo = "3 alertas de riesgo esta semana"
    cuerpo = (
        f"Acumulaste {pack['count']} evaluaciones de riesgo en los últimos 7 días "
        f"(umbral {pack['umbral']}). Revisa carga, dolor y descanso. "
        "Es una estimación orientativa, no un diagnóstico médico."
    )
    destinatario = str(email or usuario_id)
    envio = await _accessibility.crear_notificacion(
        user_id=destinatario,
        tipo="RIESGO_SEMANAL",
        titulo=titulo,
        cuerpo=cuerpo,
        priority="HIGH",
        authorization=authorization,
    )
    if perfil is None:
        perfil = await cargar_perfil(usuario_id)
    marcar_aviso_umbral(perfil)
    registro = {
        "tipo": "RIESGO_SEMANAL",
        "titulo": titulo,
        "cuerpo": cuerpo,
        "canales": ["push", "email"],
        "fecha": datetime.now(timezone.utc).isoformat(),
        "envio": envio,
        "caso": "CP33-HU50",
    }
    perfil.setdefault("notificaciones", []).append(registro)
    await guardar_perfil(perfil)
    return registro


async def revisar_historial_y_avisar(
    usuario_id: str,
    *,
    email: Optional[str] = None,
    authorization: Optional[str] = None,
) -> dict[str, Any]:
    """Tras guardar una evaluación: cuenta el historial y avisa al 3.er riesgo."""
    count = await conteo_historial_semana(usuario_id, email)
    perfil = await cargar_perfil(usuario_id)
    umbrales = perfil.get("umbrales") if isinstance(perfil.get("umbrales"), dict) else {}
    umbral = int(umbrales.get("alertas_semana") or UMBRAL_DEFAULT)
    if count < umbral and perfil.get("aviso_umbral_semana_en"):
        perfil["aviso_umbral_semana_en"] = None
        await guardar_perfil(perfil)
    pack = estado_umbral(perfil, count)
    if pack.get("debe_avisar"):
        pack["notificacion"] = await enviar_aviso_umbral(
            usuario_id,
            pack,
            email=email,
            authorization=authorization,
            perfil=perfil,
        )
        pack["notificado"] = True
    else:
        pack["notificado"] = bool(pack.get("ya_avisado"))
        pack["notificacion"] = None
    return pack


async def resetear_aviso_umbral(usuario_id: str) -> None:
    """Si se vacía el historial, se puede volver a contar."""
    perfil = await cargar_perfil(usuario_id)
    perfil["aviso_umbral_semana_en"] = None
    await guardar_perfil(perfil)


async def resetear_aviso_si_bajo_umbral(usuario_id: str, email: Optional[str] = None) -> None:
    """Si el historial semanal baja de 3, el próximo 3.er riesgo vuelve a avisar."""
    count = await conteo_historial_semana(usuario_id, email)
    perfil = await cargar_perfil(usuario_id)
    umbrales = perfil.get("umbrales") if isinstance(perfil.get("umbrales"), dict) else {}
    umbral = int(umbrales.get("alertas_semana") or UMBRAL_DEFAULT)
    if count < umbral and perfil.get("aviso_umbral_semana_en"):
        perfil["aviso_umbral_semana_en"] = None
        await guardar_perfil(perfil)
