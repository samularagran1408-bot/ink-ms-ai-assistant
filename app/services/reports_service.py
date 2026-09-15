"""Cliente de ink-ms-reports para métricas e historial (RF47/RF48)."""

from typing import Any, Optional

from app.config import settings
from app.services.http_client import get_json


class ReportsService:
    """Cliente HTTP de ink-ms-reports (analítica de eventos, métricas y dashboard)."""

    def __init__(self):
        """Guarda la URL base de ink-ms-reports desde la configuración."""
        self.base_url = settings.REPORTS_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        """Normaliza el JWT a cabecera ``Authorization: Bearer …``; vacío si no hay token."""
        if not authorization:
            return {}
        token = authorization if authorization.startswith("Bearer ") else f"Bearer {authorization}"
        return {"Authorization": token}

    async def _get(self, path: str, authorization: Optional[str] = None, params: Optional[dict] = None) -> Any:
        """GET a ``path`` relativo de ink-ms-reports. Devuelve el JSON o ``None`` si falla."""
        return await get_json(
            f"{self.base_url}{path}",
            headers=self._headers(authorization),
            params=params,
            timeout=4.0,
        )

    async def eventos_usuario(self, authorization: Optional[str] = None) -> list[dict]:
        """Eventos analíticos del usuario autenticado.

        Llama ``GET /api/analytics/events/user``. Devuelve la lista JSON o ``[]``
        si el microservicio no responde o el cuerpo no es una lista.
        """
        datos = await self._get("/api/analytics/events/user", authorization)
        return datos if isinstance(datos, list) else []

    async def metricas_diarias(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> list[dict]:
        """Métricas diarias agregadas en un rango de fechas.

        Llama ``GET /api/analytics/metrics/daily`` con ``startDate``/``endDate``
        opcionales. Devuelve la lista JSON o ``[]``.
        """
        params = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        datos = await self._get("/api/analytics/metrics/daily", authorization, params or None)
        return datos if isinstance(datos, list) else []

    async def dashboard(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict:
        """KPIs del dashboard de reportes.

        Llama ``GET /api/dashboard`` con ``startDate``/``endDate`` opcionales.
        Devuelve el objeto JSON o ``{}`` si falla.
        """
        params = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        datos = await self._get("/api/dashboard", authorization, params or None)
        return datos if isinstance(datos, dict) else {}

    async def _panel(
        self,
        suffix: str,
        authorization: Optional[str] = None,
        params: Optional[dict] = None,
    ) -> dict:
        """GET ``/api/dashboard{suffix}``. Dict o ``{}``."""
        datos = await self._get(f"/api/dashboard{suffix}", authorization, params)
        return datos if isinstance(datos, dict) else {}

    async def dashboard_asociaciones(self, authorization: Optional[str] = None) -> dict:
        """Panel asociaciones: ``GET /api/dashboard/associations`` (admin/entrenador)."""
        return await self._panel("/associations", authorization)

    async def dashboard_organizador(
        self,
        organizer_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict:
        """Panel organizador: ``GET /api/dashboard/organizer``."""
        params = {"organizerId": organizer_id} if organizer_id else None
        return await self._panel("/organizer", authorization, params)

    async def dashboard_entrenador(
        self,
        trainer_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict:
        """Panel entrenador: ``GET /api/dashboard/trainer``."""
        params = {"trainerId": trainer_id} if trainer_id else None
        return await self._panel("/trainer", authorization, params)

    async def dashboard_atletas(
        self,
        authorization: Optional[str] = None,
        organizer_id: Optional[str] = None,
        all_events: bool = False,
    ) -> dict:
        """Panel atletas: ``GET /api/dashboard/athletes``."""
        params: dict[str, str] = {"allEvents": "true" if all_events else "false"}
        if organizer_id:
            params["organizerId"] = organizer_id
        return await self._panel("/athletes", authorization, params)
