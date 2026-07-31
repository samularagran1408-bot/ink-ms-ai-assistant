"""Comparativa con historial personal (RF48) y métricas atleta (RF47)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Optional

from app.database.mongodb import get_db
from app.database.repositorio import COL_CONVERSACIONES, COL_PLANES, COL_SESIONES_RPE
from app.services.reports_service import ReportsService
from app.services.sports_service import SportsService
from app.services.user_service import UserService


class HistorialAgent:
    def __init__(self):
        self.user_service = UserService()
        self.sports_service = SportsService()
        self.reports_service = ReportsService()

    async def comparar(
        self,
        usuario_id: str,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        perfil = await self.user_service.get_user_profile(usuario_id, authorization)
        inscritos = await self.sports_service.get_eventos_usuario(usuario_id, authorization)
        analytics = await self.reports_service.eventos_usuario(authorization)
        rpe = await self._rpe_usuario(usuario_id)
        planes = await self._planes_usuario(usuario_id)
        chats = await self._chats_usuario(usuario_id)

        hoy = date.today()
        mes_actual_ini = hoy.replace(day=1)
        mes_prev_fin = mes_actual_ini - timedelta(days=1)
        mes_prev_ini = mes_prev_fin.replace(day=1)

        def en_rango(fecha_str: Any, ini: date, fin: date) -> bool:
            f = self._parse_date(fecha_str)
            return f is not None and ini <= f <= fin

        eventos_actual = [
            e for e in inscritos
            if en_rango(e.get("eventDate") or e.get("registrationDate"), mes_actual_ini, hoy)
        ]
        eventos_prev = [
            e for e in inscritos
            if en_rango(e.get("eventDate") or e.get("registrationDate"), mes_prev_ini, mes_prev_fin)
        ]

        rpe_actual = [r for r in rpe if en_rango(r.get("fecha"), mes_actual_ini, hoy)]
        rpe_prev = [r for r in rpe if en_rango(r.get("fecha"), mes_prev_ini, mes_prev_fin)]

        avg = lambda xs: round(sum(xs) / len(xs), 2) if xs else None
        rpe_avg_actual = avg([float(r["rpe"]) for r in rpe_actual if r.get("rpe") is not None])
        rpe_avg_prev = avg([float(r["rpe"]) for r in rpe_prev if r.get("rpe") is not None])

        return {
            "usuario": {
                "id": perfil.get("id") or usuario_id,
                "fullName": perfil.get("fullName") or "Usuario",
                "disability": perfil.get("disability"),
            },
            "periodo_actual": {"desde": mes_actual_ini.isoformat(), "hasta": hoy.isoformat()},
            "periodo_anterior": {
                "desde": mes_prev_ini.isoformat(),
                "hasta": mes_prev_fin.isoformat(),
            },
            "comparativa": {
                "inscripciones_eventos": {
                    "actual": len(eventos_actual),
                    "anterior": len(eventos_prev),
                    "delta": len(eventos_actual) - len(eventos_prev),
                },
                "sesiones_rpe": {
                    "actual": len(rpe_actual),
                    "anterior": len(rpe_prev),
                    "rpe_promedio_actual": rpe_avg_actual,
                    "rpe_promedio_anterior": rpe_avg_prev,
                },
                "planes_guardados": len(planes),
                "mensajes_chat": chats,
                "eventos_analytics": len(analytics) if analytics else 0,
            },
            "tendencia": self._tendencia(len(eventos_actual), len(eventos_prev), rpe_avg_actual, rpe_avg_prev),
            "graficos": {
                "inscripciones_mensuales": [
                    {"periodo": "anterior", "valor": len(eventos_prev)},
                    {"periodo": "actual", "valor": len(eventos_actual)},
                ],
                "rpe_mensual": [
                    {"periodo": "anterior", "valor": rpe_avg_prev or 0},
                    {"periodo": "actual", "valor": rpe_avg_actual or 0},
                ],
            },
            "rf": ["RF47", "RF48"],
        }

    async def metricas(
        self,
        usuario_id: str,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        comparativa = await self.comparar(usuario_id, authorization)
        dashboard = await self.reports_service.dashboard(authorization=authorization)
        return {
            **comparativa,
            "dashboard_plataforma": {
                "total_users": dashboard.get("totalUsers") or dashboard.get("total_users"),
                "active_events": dashboard.get("activeEvents") or dashboard.get("active_events"),
                "disponible": bool(dashboard),
            },
            "rf": ["RF47", "RF48"],
        }

    def _tendencia(
        self,
        ev_act: int,
        ev_prev: int,
        rpe_act: Optional[float],
        rpe_prev: Optional[float],
    ) -> str:
        if ev_act > ev_prev:
            return "alza"
        if ev_act < ev_prev:
            return "baja"
        if rpe_act and rpe_prev and rpe_act < rpe_prev - 0.5:
            return "mejor_recuperacion"
        return "estable"

    async def _rpe_usuario(self, usuario_id: str) -> list[dict]:
        db = get_db()
        if db is None:
            return []
        try:
            return await db[COL_SESIONES_RPE].find(
                {"usuario_id": usuario_id}, {"_id": 0}
            ).to_list(length=200)
        except Exception:
            return []

    async def _planes_usuario(self, usuario_id: str) -> list[dict]:
        db = get_db()
        if db is None:
            return []
        try:
            return await db[COL_PLANES].find(
                {"usuario.id": usuario_id}, {"_id": 0, "plan_id": 1}
            ).to_list(length=50)
        except Exception:
            return []

    async def _chats_usuario(self, usuario_id: str) -> int:
        db = get_db()
        if db is None:
            return 0
        try:
            docs = await db[COL_CONVERSACIONES].find(
                {"usuario_id": usuario_id}, {"mensajes": 1}
            ).to_list(length=20)
            return sum(len(d.get("mensajes") or []) for d in docs)
        except Exception:
            return 0

    @staticmethod
    def _parse_date(valor: Any) -> Optional[date]:
        if not valor:
            return None
        try:
            return date.fromisoformat(str(valor)[:10])
        except ValueError:
            return None
