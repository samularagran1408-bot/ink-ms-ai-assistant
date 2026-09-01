"""Cliente de ink-ms-reports para métricas e historial (RF47/RF48)."""

from typing import Any, Optional

import httpx

from app.config import settings


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
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                respuesta = await client.get(
                    f"{self.base_url}{path}",
                    headers=self._headers(authorization) or None,
                    params=params,
                )
                if respuesta.status_code == 200:
                    return respuesta.json()
        except Exception as exc:
            print(f"Error llamando reports {path}: {exc}")
        return None

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
