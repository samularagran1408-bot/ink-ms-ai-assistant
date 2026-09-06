"""Predicción heurística de riesgo de lesión (RF43). Sin valor diagnóstico médico."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.database.mongodb import get_db
from app.database.repositorio import COL_EVALUACIONES_RIESGO
from app.motor.cuerpo import mapa_corporal
from app.nlp.discapacidad import canonizar, descripcion
from app.services.sports_service import SportsService
from app.services.user_service import UserService


class RiesgoAgent:
    """Estima un score heurístico de riesgo de lesión (RF43). No es diagnóstico médico."""

    def __init__(self):
        """Inicializa clientes de users y sports (carga competitiva)."""
        self.user_service = UserService()
        self.sports_service = SportsService()

    async def evaluar(
        self,
        usuario_id: str,
        rpe_reciente: Optional[float] = None,
        dolor_reportado: bool = False,
        dias_sin_descanso: int = 0,
        authorization: Optional[str] = None,
        perfil: Optional[dict[str, Any]] = None,
        limitacion: Optional[str] = None,
    ) -> dict[str, Any]:
        """Calcula score 0–100 y nivel (bajo/moderado/alto) a partir del perfil y la carga.

        Suma puntos por tipo de discapacidad, dolor, RPE, días sin descanso y
        eventos inscritos. Si hay dolor o `limitacion`, incluye el mapa corporal.
        """
        perfil = perfil or await self.user_service.get_user_profile(usuario_id, authorization)
        if not perfil:
            perfil = {}

        discapacidad_raw = perfil.get("disability") or perfil.get("disabilityType")
        discapacidad = canonizar(discapacidad_raw)
        uid = str(perfil.get("id") or usuario_id)
        inscritos = await self.sports_service.get_eventos_usuario(uid, authorization)

        score = 15.0
        factores: list[str] = []

        if discapacidad in ("motriz", "multiple"):
            score += 15
            factores.append("Perfil motriz/múltiple: priorizar control articular y fatiga acumulada.")
        elif discapacidad == "visual":
            score += 8
            factores.append("Perfil visual: riesgo por entorno y pérdida de equilibrio espacial.")
        elif discapacidad == "auditiva":
            score += 5
            factores.append("Perfil auditivo: coordinar señales visuales de fatiga/parada.")
        elif discapacidad in ("cognitiva", "intelectual"):
            score += 8
            factores.append("Perfil cognitivo/intelectual: sesiones cortas y progresión muy gradual.")

        if dolor_reportado:
            score += 35
            factores.append("El usuario reportó dolor o molestia reciente.")
        if (limitacion or "").strip():
            score += 10
            factores.append(f"Limitación reportada: {limitacion.strip()}.")
        if rpe_reciente is not None:
            if rpe_reciente >= 8:
                score += 25
                factores.append(f"RPE reciente alto ({rpe_reciente}/10).")
            elif rpe_reciente >= 6:
                score += 12
                factores.append(f"RPE moderado-alto ({rpe_reciente}/10).")
        if dias_sin_descanso >= 5:
            score += 20
            factores.append(f"{dias_sin_descanso} días seguidos sin descanso registrado.")
        elif dias_sin_descanso >= 3:
            score += 10
            factores.append("Poca recuperación entre sesiones.")

        if len(inscritos) >= 3:
            score += 8
            factores.append("Alta carga competitiva (varios eventos inscritos).")

        score = min(100.0, round(score, 1))
        if score < 30:
            nivel = "bajo"
            alerta = "Riesgo bajo. Mantén técnica y calentamiento."
        elif score < 60:
            nivel = "moderado"
            alerta = "Riesgo moderado. Reduce volumen o añade un día de movilidad."
        else:
            nivel = "alto"
            alerta = "Riesgo alto. Prioriza descanso y consulta a un profesional de la salud."

        resultado = {
            "id": str(uuid.uuid4()),
            "usuario_id": uid,
            "email": perfil.get("email"),
            "fullName": perfil.get("fullName"),
            "roles": perfil.get("roles") or [],
            "discapacidad": discapacidad,
            "discapacidad_origen": discapacidad_raw,
            "discapacidad_descripcion": descripcion(discapacidad),
            "score_riesgo": score,
            "nivel": nivel,
            "alerta": alerta,
            "factores": factores or ["Sin factores de riesgo destacados en los datos disponibles."],
            "recomendaciones": self._recomendaciones(nivel, discapacidad),
            "disclaimer": (
                "Estimación heurística orientativa. No sustituye valoración clínica "
                "ni diagnóstico médico."
            ),
            "eventos_inscritos": len(inscritos),
            "perfil_fuente": "users/perfil" if perfil.get("id") else "incompleto",
            "rf": "RF43",
            "rpe_reciente": rpe_reciente,
            "dolor_reportado": dolor_reportado,
            "dias_sin_descanso": dias_sin_descanso,
            "limitacion": (limitacion or "").strip() or None,
            "fecha": datetime.now(timezone.utc).isoformat(),
            "cuerpo": mapa_corporal("", limitacion)
            if (dolor_reportado or (limitacion or "").strip())
            else None,
        }
        await self._guardar_evaluacion(resultado)
        return resultado

    async def listar_historial(self, usuario_id: str, limite: int = 20) -> list[dict[str, Any]]:
        """Evaluaciones de riesgo guardadas, más reciente primero."""
        db = get_db()
        if db is None:
            return []
        try:
            cursor = (
                db[COL_EVALUACIONES_RIESGO]
                .find({"usuario_id": usuario_id}, {"_id": 0, "cuerpo": 0})
                .sort("fecha", -1)
                .limit(max(1, min(limite, 50)))
            )
            return await cursor.to_list(length=max(1, min(limite, 50)))
        except Exception as exc:
            print(f"No se pudo leer historial de riesgo: {exc}")
            return []

    async def borrar_evaluacion(self, usuario_id: str, evaluacion_id: str) -> bool:
        """Elimina una evaluación del atleta. False si no existe."""
        db = get_db()
        if db is None:
            return False
        try:
            res = await db[COL_EVALUACIONES_RIESGO].delete_one(
                {"usuario_id": usuario_id, "id": evaluacion_id}
            )
            return (res.deleted_count or 0) > 0
        except Exception as exc:
            print(f"No se pudo borrar evaluación de riesgo: {exc}")
            return False

    async def borrar_historial(self, usuario_id: str) -> int:
        """Borra todas las evaluaciones del atleta. Devuelve cuántas se eliminaron."""
        db = get_db()
        if db is None:
            return 0
        try:
            res = await db[COL_EVALUACIONES_RIESGO].delete_many({"usuario_id": usuario_id})
            return int(res.deleted_count or 0)
        except Exception as exc:
            print(f"No se pudo vaciar historial de riesgo: {exc}")
            return 0

    async def _guardar_evaluacion(self, doc: dict[str, Any]) -> None:
        """Persiste la evaluación; no falla la respuesta si Mongo no está."""
        db = get_db()
        if db is None:
            return
        try:
            guardar = {k: v for k, v in doc.items() if k != "cuerpo"}
            await db[COL_EVALUACIONES_RIESGO].insert_one(guardar)
        except Exception as exc:
            print(f"No se pudo guardar evaluación de riesgo: {exc}")

    def _recomendaciones(self, nivel: str, discapacidad: str) -> list[str]:
        """Pautas de seguridad genéricas más ajustes según nivel de riesgo y discapacidad."""
        base = [
            "Calienta 8–10 minutos antes de la parte principal.",
            "Detén el ejercicio si aparece dolor agudo (no fatiga muscular).",
        ]
        if nivel == "alto":
            base.append("Sustituye la sesión intensa por movilidad suave o descanso activo.")
        if discapacidad == "motriz":
            base.append("Trabaja en rango libre de dolor y estabiliza el tronco.")
        if discapacidad == "visual":
            base.append("Despeja el área y usa un punto de apoyo fijo.")
        if discapacidad == "auditiva":
            base.append("Acuerda señales visuales claras para parar o bajar intensidad.")
        return base
