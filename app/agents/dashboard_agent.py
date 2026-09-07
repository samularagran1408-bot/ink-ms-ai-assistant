"""Dashboard AI (RF47): agrega métricas, comparativa, reports e inscripciones."""

from __future__ import annotations

from typing import Any, Optional

from app.agents.competencia_agent import progreso_plan_desde_doc
from app.agents.historial_agent import HistorialAgent
from app.agents.riesgo_agent import RiesgoAgent
from app.database.mongodb import get_db
from app.services.reports_service import ReportsService
from app.services.sports_service import SportsService
from app.services.user_service import UserService

COL_MODO_COMPETENCIA = "modo_competencia"


class DashboardAgent:
    """Agrega métricas, comparativa, riesgo e inscripciones para el panel AI (RF47)."""

    def __init__(self):
        """Inicializa historial, riesgo y clientes de reports, sports y users."""
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
        """Construye el dashboard del atleta: KPIs, comparativa, riesgo y modo competencia.

        Devuelve tanto los bloques crudos como `vista` lista para pintar en la UI.
        """
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
                persistir=False,
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
            "vista": self._vista(
                perfil=perfil or {},
                usuario_id=usuario_id,
                eventos=eventos,
                rutinas=rutinas,
                comparativa=comparativa or {},
                modo=modo,
                riesgo_snap=riesgo_snap,
                rpe_reciente=rpe_reciente,
                alertas=alertas_sugeridas,
                reportes=reportes or {},
            ),
        }

    async def _ultimo_rpe(self, usuario_id: str) -> Optional[float]:
        """Devuelve el RPE más reciente (sesiones o evaluaciones de riesgo)."""
        filas = await self.historial._rpe_usuario(usuario_id)
        if not filas:
            return None
        filas = sorted(filas, key=lambda row: str(row.get("fecha") or ""), reverse=True)
        try:
            return float(filas[0]["rpe"])
        except (TypeError, ValueError, KeyError):
            return None

    async def _modo_competencia(self, usuario_id: str) -> dict[str, Any]:
        """Lee el modo competencia persistido y adjunta % del plan. `{activo: False}` si no hay."""
        db = get_db()
        if db is None:
            return {"activo": False}
        try:
            doc = await db[COL_MODO_COMPETENCIA].find_one(
                {"$or": [{"usuario_id": usuario_id}, {"email": usuario_id}]},
                {"_id": 0},
            )
            if not doc:
                return {"activo": False}
            plan_prog = progreso_plan_desde_doc(doc)
            return {
                "activo": bool(doc.get("activo")),
                "evento_id": doc.get("evento_id"),
                "objetivo": doc.get("objetivo"),
                "semanas": doc.get("semanas"),
                "semana_actual": plan_prog.get("semana_actual"),
                "plan_pct": plan_prog.get("plan_pct"),
                "evento_objetivo": doc.get("evento_snapshot"),
                "actualizado": doc.get("actualizado"),
                "activado_en": doc.get("activado_en"),
            }
        except Exception:
            return {"activo": False}

    def _vista(
        self,
        *,
        perfil: dict,
        usuario_id: str,
        eventos: list,
        rutinas: list,
        comparativa: dict,
        modo: dict,
        riesgo_snap: dict,
        rpe_reciente: Optional[float],
        alertas: list[str],
        reportes: dict,
    ) -> dict[str, Any]:
        """Bloques listos para pintar (iconos + listas), sin JSON crudo."""
        roles = perfil.get("roles") or []
        if isinstance(roles, str):
            roles = [r.strip() for r in roles.split(",") if r.strip()]
        comp = (comparativa or {}).get("comparativa") or {}
        insc_ev = comp.get("inscripciones_eventos") or {}
        rpe = comp.get("sesiones_rpe") or {}
        nivel = str((riesgo_snap or {}).get("nivel") or (riesgo_snap or {}).get("riesgo") or "bajo")
        confirmados = sum(1 for e in (eventos or []) if e.get("waitlistPosition") is None)
        asistidos = sum(
            1 for e in (eventos or [])
            if e.get("attended") is True and e.get("waitlistPosition") is None
        )
        asistencia_pct = round((asistidos * 100) / confirmados) if confirmados else 0
        return {
            "perfil": {
                "nombre": perfil.get("fullName") or "Usuario",
                "discapacidad": perfil.get("disability") or "Sin indicar",
                "roles": [str(r) for r in roles],
            },
            "kpis": [
                {
                    "clave": "eventos",
                    "icono": "calendar-days",
                    "valor": len(eventos),
                    "label": "Eventos inscritos",
                },
                {
                    "clave": "rutinas",
                    "icono": "heart",
                    "valor": len(rutinas),
                    "label": "Rutinas inscritas",
                },
                {
                    "clave": "rpe",
                    "icono": "bolt",
                    "valor": rpe_reciente if rpe_reciente is not None else "—",
                    "label": "RPE reciente",
                },
                {
                    "clave": "riesgo",
                    "icono": "shield-check",
                    "valor": nivel,
                    "label": "Riesgo de lesión",
                },
            ],
            "comparativa": [
                {
                    "label": "Inscripciones este mes",
                    "actual": insc_ev.get("actual") or 0,
                    "anterior": insc_ev.get("anterior") or 0,
                    "delta": insc_ev.get("delta") or 0,
                    "icono": "chart-bar",
                },
                {
                    "label": "Sesiones con RPE",
                    "actual": (rpe.get("actual") or 0),
                    "anterior": (rpe.get("anterior") or 0),
                    "delta": (rpe.get("actual") or 0) - (rpe.get("anterior") or 0),
                    "icono": "bolt",
                },
                {
                    "label": "RPE promedio",
                    "actual": rpe.get("rpe_promedio_actual") or 0,
                    "anterior": rpe.get("rpe_promedio_anterior") or 0,
                    "delta": round(
                        float(rpe.get("rpe_promedio_actual") or 0)
                        - float(rpe.get("rpe_promedio_anterior") or 0),
                        2,
                    ),
                    "icono": "heart",
                },
                {
                    "label": "Planes guardados",
                    "actual": int(comp.get("planes_guardados") or 0),
                    "anterior": 0,
                    "delta": int(comp.get("planes_guardados") or 0),
                    "icono": "clipboard-document-list",
                },
            ],
            "sesiones_historial": (comparativa or {}).get("sesiones_historial") or [],
            "tendencia": (comparativa or {}).get("tendencia") or "estable",
            "modo_competencia": bool((modo or {}).get("activo")),
            "objetivo_competencia": (modo or {}).get("objetivo"),
            "semana_competencia": (modo or {}).get("semana_actual"),
            "plan_pct": (modo or {}).get("plan_pct"),
            "progreso_panel": {
                "asistencia_pct": asistencia_pct,
                "asistidos": asistidos,
                "confirmados": confirmados,
                "rutinas": len(rutinas or []),
                "lista_espera": len(eventos or []) - confirmados,
            },
            "alertas": alertas,
            "eventos": [
                {
                    "titulo": e.get("eventName") or e.get("name") or "Evento",
                    "subtitulo": e.get("sportName") or "",
                    "meta": [
                        x
                        for x in (
                            e.get("eventDate"),
                            e.get("location"),
                            e.get("status"),
                        )
                        if x
                    ],
                    "id": str(e.get("eventId") or e.get("id") or ""),
                }
                for e in (eventos or [])[:8]
            ],
            "rutinas": [
                {
                    "titulo": r.get("routineName") or r.get("name") or "Rutina",
                    "subtitulo": r.get("sportName") or r.get("level") or "",
                    "meta": [
                        x
                        for x in (
                            f"{r.get('durationMinutes')} min" if r.get("durationMinutes") else None,
                            r.get("disabilityFocus"),
                            r.get("level"),
                        )
                        if x
                    ],
                    "id": str(r.get("routineId") or r.get("id") or ""),
                }
                for r in (rutinas or [])[:8]
            ],
            "plataforma": {
                "usuarios": (reportes or {}).get("totalUsers") or (reportes or {}).get("total_users"),
                "eventos_activos": (reportes or {}).get("activeEvents")
                or (reportes or {}).get("active_events"),
            },
        }

    def resumen_texto(self, dashboard: dict[str, Any]) -> str:
        """Convierte la `vista` del dashboard en un resumen en viñetas para el chat."""
        vista = dashboard.get("vista") or {}
        perfil = vista.get("perfil") or {}
        kpis = {k.get("clave"): k for k in (vista.get("kpis") or []) if isinstance(k, dict)}
        lineas = [
            f"Resumen de {perfil.get('nombre') or 'tu perfil'}:",
            f"- Eventos inscritos: {kpis.get('eventos', {}).get('valor', 0)}",
            f"- Rutinas inscritas: {kpis.get('rutinas', {}).get('valor', 0)}",
        ]
        if kpis.get("rpe", {}).get("valor") not in (None, "—"):
            lineas.append(f"- RPE reciente: {kpis['rpe']['valor']}")
        if vista.get("tendencia"):
            lineas.append(f"- Tendencia: {vista['tendencia']}")
        for ev in (vista.get("eventos") or [])[:3]:
            extra = " · ".join(ev.get("meta") or [])
            lineas.append(f"- Evento: {ev.get('titulo')}" + (f" ({extra})" if extra else ""))
        return "\n".join(lineas)
