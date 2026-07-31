"""Cliente de ink-ms-reports para métricas e historial (RF47/RF48)."""

from typing import Any, Optional

import httpx

from app.config import settings


class ReportsService:
    def __init__(self):
        self.base_url = settings.REPORTS_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        if not authorization:
            return {}
        token = authorization if authorization.startswith("Bearer ") else f"Bearer {authorization}"
        return {"Authorization": token}

    async def _get(self, path: str, authorization: Optional[str] = None, params: Optional[dict] = None) -> Any:
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
        datos = await self._get("/api/analytics/events/user", authorization)
        return datos if isinstance(datos, list) else []

    async def metricas_diarias(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> list[dict]:
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
        params = {}
        if start_date:
            params["startDate"] = start_date
        if end_date:
            params["endDate"] = end_date
        datos = await self._get("/api/dashboard", authorization, params or None)
        return datos if isinstance(datos, dict) else {}
