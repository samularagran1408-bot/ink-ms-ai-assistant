"""Cliente de ink-ms-sports (eventos, deportes, discapacidades, rutinas e inscripciones)."""

import httpx
from typing import Any, Optional
from app.config import settings


class SportsService:
    """Consulta el catálogo e inscripciones de ink-ms-sports vía HTTP."""

    def __init__(self):
        """Guarda la URL base de ink-ms-sports desde la configuración."""
        self.base_url = settings.SPORTS_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        """Normaliza el JWT a cabecera ``Authorization: Bearer …``; vacío si no hay token."""
        if not authorization:
            return {}
        token = authorization if authorization.startswith("Bearer ") else f"Bearer {authorization}"
        return {"Authorization": token}

    async def _get_json(self, path: str, authorization: Optional[str] = None, default: Any = None) -> Any:
        """GET a ``path`` relativo de ink-ms-sports. Devuelve JSON 200 o ``default`` (lista vacía)."""
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
        """Inscripciones del usuario enriquecidas con datos del evento.

        Llama ``GET /api/registrations/user/{usuario_id}`` y cruza con
        ``GET /api/events`` para añadir nombre, deporte, fecha y ubicación.
        El llamador recibe la lista de inscripciones ya combinadas.
        """
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
        """Catálogo de deportes activos: ``GET /api/sports/active``. Lista o ``[]``."""
        data = await self._get_json("/api/sports/active", authorization, default=[])
        return data if isinstance(data, list) else []

    async def get_discapacidades_activas(self, authorization: Optional[str] = None) -> list[dict]:
        """Tipos de discapacidad activos: ``GET /api/disabilities/active``. Lista o ``[]``."""
        data = await self._get_json("/api/disabilities/active", authorization, default=[])
        return data if isinstance(data, list) else []

    async def get_adaptaciones_deporte(self, sport_id: int | str, authorization: Optional[str] = None) -> list[dict]:
        """Adaptaciones de un deporte: ``GET /api/sport-disabilities/sport/{sport_id}``."""
        data = await self._get_json(
            f"/api/sport-disabilities/sport/{sport_id}",
            authorization,
            default=[],
        )
        return data if isinstance(data, list) else []

    async def get_asociaciones(self, authorization: Optional[str] = None) -> list[dict]:
        """Todas las asociaciones deporte–discapacidad: ``GET /api/sport-disabilities``."""
        data = await self._get_json("/api/sport-disabilities", authorization, default=[])
        return data if isinstance(data, list) else []

    async def get_rutinas_publicadas(self, authorization: Optional[str] = None) -> list[dict]:
        """Rutinas publicadas en la plataforma: ``GET /api/routines``. Lista o ``[]``."""
        data = await self._get_json("/api/routines", authorization, default=[])
        return data if isinstance(data, list) else []

    async def get_rutinas_usuario(self, usuario_id: str, authorization: Optional[str] = None) -> list[dict]:
        """Inscripciones del usuario a rutinas de entrenador.

        Llama ``GET /api/routine-registrations/user/{usuario_id}`` y las enriquece
        con ``GET /api/routines`` (nombre, deporte, nivel, duración).
        """
        registros = await self._get_json(
            f"/api/routine-registrations/user/{usuario_id}",
            authorization,
            default=[],
        )
        if not isinstance(registros, list):
            return []

        rutinas_por_id = {
            r.get("id"): r for r in await self.get_rutinas_publicadas(authorization) if r.get("id")
        }
        # Incluir también rutinas del entrenador listadas por id si hace falta
        enriquecidos = []
        for reg in registros:
            rid = reg.get("routineId")
            rutina = rutinas_por_id.get(rid, {})
            enriquecidos.append({
                **reg,
                "routineName": reg.get("routineName") or rutina.get("name"),
                "sportId": rutina.get("sportId"),
                "sportName": rutina.get("sportName"),
                "level": rutina.get("level"),
                "durationMinutes": rutina.get("durationMinutes"),
                "disabilityFocus": rutina.get("disabilityFocus"),
                "routineStatus": rutina.get("status"),
            })
        return enriquecidos
