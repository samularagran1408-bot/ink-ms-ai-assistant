import httpx
from typing import Any, Optional
from app.config import settings


class SportsService:
    def __init__(self):
        self.base_url = settings.SPORTS_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        if not authorization:
            return {}
        token = authorization if authorization.startswith("Bearer ") else f"Bearer {authorization}"
        return {"Authorization": token}

    async def _get_json(self, path: str, authorization: Optional[str] = None, default: Any = None) -> Any:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    f"{self.base_url}{path}",
                    headers=self._headers(authorization) or None,
                )
                if response.status_code == 200:
                    return response.json()
                return default if default is not None else []
        except Exception as e:
            print(f"Error llamando sports {path}: {e}")
            return default if default is not None else []

    async def get_eventos(self, authorization: Optional[str] = None) -> list[dict]:
        """Lista todos los eventos: GET /api/events."""
        data = await self._get_json("/api/events", authorization, default=[])
        return data if isinstance(data, list) else []

    async def get_eventos_activos(self, authorization: Optional[str] = None) -> list[dict]:
        """Eventos recomendables: active/draft (excluye cancelled/finished)."""
        eventos = await self.get_eventos(authorization)
        excluidos = {"cancelled", "finished", "cancelado", "finalizado"}
        recomendables = [
            e for e in eventos
            if str(e.get("status", "")).lower() not in excluidos
        ]
        return recomendables if recomendables else eventos

    async def get_eventos_usuario(self, usuario_id: str, authorization: Optional[str] = None) -> list[dict]:
        """Inscripciones del usuario enriquecidas con datos del evento."""
        registros = await self._get_json(
            f"/api/registrations/user/{usuario_id}",
            authorization,
            default=[],
        )
        if not isinstance(registros, list):
            return []

        eventos_por_id = {
            e.get("id"): e for e in await self.get_eventos(authorization) if e.get("id")
        }

        enriquecidos = []
        for reg in registros:
            evento = eventos_por_id.get(reg.get("eventId"), {})
            enriquecidos.append({
                **reg,
                "eventName": reg.get("eventName") or evento.get("name"),
                "sportId": evento.get("sportId"),
                "sportName": evento.get("sportName"),
                "eventDate": evento.get("eventDate"),
                "eventTime": evento.get("eventTime"),
                "location": evento.get("location"),
                "status": evento.get("status"),
                "description": evento.get("description"),
            })
        return enriquecidos

    async def get_deportes_activos(self, authorization: Optional[str] = None) -> list[dict]:
        data = await self._get_json("/api/sports/active", authorization, default=[])
        return data if isinstance(data, list) else []

    async def get_discapacidades_activas(self, authorization: Optional[str] = None) -> list[dict]:
        data = await self._get_json("/api/disabilities/active", authorization, default=[])
        return data if isinstance(data, list) else []

    async def get_adaptaciones_deporte(self, sport_id: int | str, authorization: Optional[str] = None) -> list[dict]:
        data = await self._get_json(
            f"/api/sport-disabilities/sport/{sport_id}",
            authorization,
            default=[],
        )
        return data if isinstance(data, list) else []
