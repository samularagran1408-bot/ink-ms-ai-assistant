"""Dashboard AI (RF47): agrega métricas, comparativa, reports e inscripciones."""

from __future__ import annotations

from typing import Any, Optional

from app.agents.historial_agent import HistorialAgent
from app.agents.riesgo_agent import RiesgoAgent
from app.database.mongodb import get_db
from app.database.repositorio import COL_SESIONES_RPE
from app.services.reports_service import ReportsService
from app.services.sports_service import SportsService
from app.services.user_service import UserService

COL_MODO_COMPETENCIA = "modo_competencia"


class DashboardAgent:
    def __init__(self):
        self.historial = HistorialAgent()
        self.riesgo = RiesgoAgent()
        self.reports = ReportsService()
        self.sports = SportsService()
        self.users = UserService()

    async def construir(
        self,
        usuario_id: str,
        authorization: Optional[str] = None,
        perfil: Optional[dict] = None,
    ) -> dict[str, Any]:
        perfil = perfil or await self.users.get_user_profile(usuario_id, authorization)
        metricas = await self.historial.metricas(usuario_id, authorization)
        comparativa = await self.historial.comparar(usuario_id, authorization)
        reportes = await self.reports.dashboard(authorization=authorization)
        eventos = await self.sports.get_eventos_usuario(usuario_id, authorization)
        rutinas = await self.sports.get_rutinas_usuario(usuario_id, authorization)
        modo = await self._modo_competencia(usuario_id)

        rpe_reciente = await self._ultimo_rpe(usuario_id)
        riesgo_snap: dict[str, Any] = {}
        alertas_sugeridas: list[str] = []
        try:
            riesgo_snap = await self.riesgo.evaluar(
                usuario_id=usuario_id,
                rpe_reciente=rpe_reciente,
                dolor_reportado=False,
                dias_sin_descanso=0,
                authorization=authorization,
                perfil=perfil,
            )
            nivel = (riesgo_snap or {}).get("nivel") or (riesgo_snap or {}).get("riesgo")
            if nivel and str(nivel).lower() in ("alto", "high", "critico", "crítico"):
                alertas_sugeridas.append(
                    "Riesgo de lesión elevado: reduce carga y consulta a tu entrenador."
                )
            elif rpe_reciente is not None and rpe_reciente >= 8:
                alertas_sugeridas.append(
                    f"RPE reciente alto ({rpe_reciente}): prioriza recuperación."
                )
        except Exception:
            riesgo_snap = {}

        if modo.get("activo"):
            alertas_sugeridas.append(
                "Modo competencia activo: sigue el plan de preparación del agente."
            )

        return {
            "usuario": {
                "id": (perfil or {}).get("id") or usuario_id,
                "fullName": (perfil or {}).get("fullName") or "Usuario",
                "disability": (perfil or {}).get("disability"),
                "roles": (perfil or {}).get("roles") or [],
            },
            "metricas": {
                "comparativa_resumen": (comparativa or {}).get("comparativa"),
                "tendencia": (comparativa or {}).get("tendencia"),
                "dashboard_plataforma": (metricas or {}).get("dashboard_plataforma"),
            },
            "comparativa": comparativa,
            "reportes": reportes or {},
            "inscripciones": {
                "eventos": eventos,
                "rutinas": rutinas,
                "total_eventos": len(eventos),
                "total_rutinas": len(rutinas),
            },
            "modo_competencia": modo,
            "riesgo": {
                "snapshot": riesgo_snap,
                "rpe_reciente": rpe_reciente,
            },
            "alertas_sugeridas": alertas_sugeridas,
            "rf": "RF47",
        }

    async def _ultimo_rpe(self, usuario_id: str) -> Optional[float]:
        db = get_db()
        if db is None:
            return None
        try:
            docs = await db[COL_SESIONES_RPE].find(
                {"usuario_id": usuario_id}, {"_id": 0, "rpe": 1, "fecha": 1}
            ).sort("fecha", -1).to_list(length=1)
            if docs and docs[0].get("rpe") is not None:
                return float(docs[0]["rpe"])
        except Exception:
            return None
        return None

    async def _modo_competencia(self, usuario_id: str) -> dict[str, Any]:
        db = get_db()
        if db is None:
            return {"activo": False}
        try:
            doc = await db[COL_MODO_COMPETENCIA].find_one(
                {"usuario_id": usuario_id}, {"_id": 0}
            )
            if not doc:
                return {"activo": False}
            return {
                "activo": bool(doc.get("activo")),
                "evento_id": doc.get("evento_id"),
                "objetivo": doc.get("objetivo"),
                "semanas": doc.get("semanas"),
                "actualizado": doc.get("actualizado"),
            }
        except Exception:
            return {"activo": False}
