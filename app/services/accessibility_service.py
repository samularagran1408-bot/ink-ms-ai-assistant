"""Cliente de ink-ms-accesibility para notificaciones y voz (RF46/RF55)."""

from typing import Any, Optional

import httpx

from app.config import settings


class AccessibilityService:
    def __init__(self):
        self.base_url = settings.ACCESSIBILITY_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        if not authorization:
            return {}
        token = authorization if authorization.startswith("Bearer ") else f"Bearer {authorization}"
        return {"Authorization": token}

    async def crear_notificacion(
        self,
        user_id: str,
        tipo: str,
        titulo: str,
        cuerpo: str,
        priority: str = "HIGH",
        event_id: Optional[str] = None,
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        payload = {
            "userId": user_id,
            "type": tipo,
            "title": titulo,
            "body": cuerpo,
            "priority": priority,
        }
        if event_id:
            payload["eventId"] = event_id
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                respuesta = await client.post(
                    f"{self.base_url}/api/notifications/internal/create",
                    json=payload,
                    headers=self._headers(authorization) or None,
                )
                if respuesta.status_code < 300:
                    return {"ok": True, "status": respuesta.status_code, "data": respuesta.json()}
                return {
                    "ok": False,
                    "status": respuesta.status_code,
                    "error": respuesta.text[:300],
                }
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

    async def interpretar_voz(
        self,
        texto: str,
        language: str = "es",
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                respuesta = await client.post(
                    f"{self.base_url}/api/voice/interpret",
                    json={"input": texto, "language": language, "log": True},
                    headers=self._headers(authorization) or None,
                )
                if respuesta.status_code == 200:
                    return respuesta.json() if isinstance(respuesta.json(), dict) else {"raw": respuesta.json()}
                return {"ok": False, "status": respuesta.status_code}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
