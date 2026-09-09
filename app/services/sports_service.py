"""Cliente de ink-ms-sports (eventos, deportes, discapacidades, rutinas e inscripciones)."""

import asyncio
from typing import Any, Optional

import httpx

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

    async def get_eventos(
        self,
        authorization: Optional[str] = None,
        *,
        available_only: bool = False,
        size: int = 50,
    ) -> list[dict]:
        """Página de eventos: GET /api/events/page (máx. 50). No baja el catálogo entero."""
        cupo = max(1, min(int(size), 50))
        qs = f"/api/events/page?page=0&size={cupo}"
        if available_only:
            qs += "&availableOnly=true"
        data = await self._get_json(qs, authorization, default=None)
        if isinstance(data, dict) and isinstance(data.get("content"), list):
            return [e for e in data["content"] if isinstance(e, dict)]
        lista = await self._get_json("/api/events", authorization, default=[])
        if not isinstance(lista, list):
            return []
        recortada = [e for e in lista if isinstance(e, dict)][:cupo]
        if not available_only:
            return recortada
        excluidos = {"cancelled", "finished", "cancelado", "finalizado"}
        return [
            e for e in recortada
            if str(e.get("status", "")).lower() not in excluidos
        ]

    async def get_eventos_activos(self, authorization: Optional[str] = None) -> list[dict]:
        """Eventos recomendables (draft/active), página de hasta 50."""
        return await self.get_eventos(authorization, available_only=True, size=50)

    async def get_evento(self, event_id: Any, authorization: Optional[str] = None) -> dict:
        """Un evento por id. Dict vacío si no existe o sports no responde."""
        if event_id is None or str(event_id).strip() == "":
            return {}
        data = await self._get_json(f"/api/events/{event_id}", authorization, default=None)
        return data if isinstance(data, dict) else {}

    async def get_eventos_usuario(self, usuario_id: str, authorization: Optional[str] = None) -> list[dict]:
        """Inscripciones del usuario enriquecidas con datos del evento.

        Llama ``GET /api/registrations/user/{usuario_id}``. Si falta nombre o
        deporte, pide como mucho 20 eventos por id (no lista el catálogo entero).
        """
        registros = await self._get_json(
            f"/api/registrations/user/{usuario_id}",
            authorization,
            default=[],
        )
        if not isinstance(registros, list):
            return []

        faltan: list[Any] = []
        vistos: set[str] = set()
        for reg in registros:
            if not isinstance(reg, dict):
                continue
            if reg.get("eventName") and reg.get("sportName"):
                continue
            eid = reg.get("eventId")
            clave = str(eid) if eid is not None else ""
            if clave and clave not in vistos:
                vistos.add(clave)
                faltan.append(eid)
            if len(faltan) >= 20:
                break

        extras = await asyncio.gather(
            *[self.get_evento(eid, authorization) for eid in faltan]
        ) if faltan else []
        eventos_por_id = {e.get("id"): e for e in extras if isinstance(e, dict) and e.get("id")}

        enriquecidos = []
        for reg in registros:
            if not isinstance(reg, dict):
                continue
            evento = eventos_por_id.get(reg.get("eventId"), {})
            enriquecidos.append({
                **reg,
                "eventName": reg.get("eventName") or evento.get("name"),
                "sportId": evento.get("sportId") or reg.get("sportId"),
                "sportName": evento.get("sportName") or reg.get("sportName"),
                "eventDate": evento.get("eventDate") or reg.get("eventDate"),
                "eventTime": evento.get("eventTime") or reg.get("eventTime"),
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
