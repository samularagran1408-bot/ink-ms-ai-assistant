"""Alertas inteligentes para entrenadores (RF55)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.riesgo_agent import RiesgoAgent
from app.database.mongodb import get_db
from app.database.repositorio import COL_ALERTAS
from app.services.accessibility_service import AccessibilityService
from app.services.user_service import UserService


class AlertasAgent:
    def __init__(self):
        self.user_service = UserService()
        self.accessibility = AccessibilityService()
        self.riesgo = RiesgoAgent()

    async def evaluar_y_notificar(
        self,
        usuario_id: str,
        entrenador_ids: Optional[list[str]] = None,
        rpe_reciente: Optional[float] = None,
        dolor_reportado: bool = False,
        dias_sin_descanso: int = 0,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        perfil = await self.user_service.get_user_profile(usuario_id, authorization)
        evaluacion = await self.riesgo.evaluar(
            usuario_id,
            rpe_reciente=rpe_reciente,
            dolor_reportado=dolor_reportado,
            dias_sin_descanso=dias_sin_descanso,
            authorization=authorization,
        )

        alertas: list[dict[str, Any]] = []
        if evaluacion["nivel"] == "alto":
            alertas.append({
                "tipo": "RIESGO_LESION",
                "prioridad": "HIGH",
                "titulo": f"Riesgo alto: {perfil.get('fullName') or usuario_id}",
                "cuerpo": (
                    f"Score {evaluacion['score_riesgo']}/100. {evaluacion['alerta']} "
                    f"Factores: {'; '.join(evaluacion['factores'][:3])}"
                ),
            })
        elif evaluacion["nivel"] == "moderado" and (dolor_reportado or (rpe_reciente or 0) >= 8):
            alertas.append({
                "tipo": "FATIGA_O_DOLOR",
                "prioridad": "MEDIUM",
                "titulo": f"Seguimiento recomendado: {perfil.get('fullName') or usuario_id}",
                "cuerpo": evaluacion["alerta"],
            })

        # Progreso destacado: RPE bajo con actividad
        if rpe_reciente is not None and rpe_reciente <= 4 and not dolor_reportado:
            alertas.append({
                "tipo": "PROGRESO_DESTACADO",
                "prioridad": "LOW",
                "titulo": f"Buen control de carga: {perfil.get('fullName') or usuario_id}",
                "cuerpo": (
                    f"RPE reciente {rpe_reciente}/10 sin dolor reportado. "
                    "Buen momento para progresar con técnica."
                ),
            })

        destinatarios = entrenador_ids or []
        notificaciones = []
        for alerta in alertas:
            for entrenador_id in destinatarios:
                resultado = await self.accessibility.crear_notificacion(
                    user_id=entrenador_id,
                    tipo=alerta["tipo"],
                    titulo=alerta["titulo"],
                    cuerpo=alerta["cuerpo"],
                    priority=alerta["prioridad"],
                    authorization=authorization,
                )
                notificaciones.append({
                    "entrenador_id": entrenador_id,
                    "alerta": alerta["tipo"],
                    **resultado,
                })

        registro = {
            "usuario_id": perfil.get("id") or usuario_id,
            "evaluacion": evaluacion,
            "alertas": alertas,
            "destinatarios": destinatarios,
            "notificaciones": notificaciones,
            "creado_en": datetime.now(timezone.utc).isoformat(),
            "rf": "RF55",
        }
        await self._guardar(registro)
        return {
            "usuario_id": registro["usuario_id"],
            "nivel_riesgo": evaluacion["nivel"],
            "score_riesgo": evaluacion["score_riesgo"],
            "alertas_generadas": alertas,
            "notificaciones": notificaciones,
            "nota": (
                "Si no envías entrenador_ids, se generan alertas pero no se notifican. "
                "Pasa IDs de entrenadores verificados para RF55 completo."
            ),
            "rf": "RF55",
        }

    async def _guardar(self, registro: dict) -> None:
        db = get_db()
        if db is None:
            return
        try:
            await db[COL_ALERTAS].insert_one(dict(registro))
        except Exception as exc:
            print(f"No se pudo guardar alerta: {exc}")
