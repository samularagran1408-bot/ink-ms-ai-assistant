"""Cliente de ink-ms-accesibility para notificaciones y voz (RF46/RF55)."""

from typing import Any, Optional

import httpx

from app.config import settings
from app.services.http_client import get_client


class AccessibilityService:
    """Cliente HTTP de ink-ms-accesibility (notificaciones internas y voz)."""

    def __init__(self):
        """Guarda la URL base de ink-ms-accesibility desde la configuración."""
        self.base_url = settings.ACCESSIBILITY_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        """Normaliza el JWT a cabecera ``Authorization: Bearer …``; vacío si no hay token."""
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
        """Crea una notificación en ink-ms-accesibility.

        Llama ``POST /api/notifications/internal/create`` con el usuario, tipo,
        título y cuerpo. Devuelve ``{ok, status, data}`` si el microservicio
        acepta la petición, o ``{ok: False, error/status}`` si falla.
        """
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
            cliente = await get_client()
            respuesta = await cliente.post(
                f"{self.base_url}/api/notifications/internal/create",
                json=payload,
                headers=self._headers(authorization) or None,
                timeout=httpx.Timeout(5.0, connect=1.5),
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
        """Interpreta un comando de voz en ink-ms-accesibility.

        Llama ``POST /api/voice/interpret`` con el texto y el idioma. Devuelve
        el JSON de interpretación (intención/entidades) o ``{ok: False, …}``
        si el microservicio no responde 200.
        """
        try:
            cliente = await get_client()
            respuesta = await cliente.post(
                f"{self.base_url}/api/voice/interpret",
                json={"input": texto, "language": language, "log": True},
                headers=self._headers(authorization) or None,
                timeout=httpx.Timeout(5.0, connect=1.5),
            )
            if respuesta.status_code == 200:
                cuerpo = respuesta.json()
                return cuerpo if isinstance(cuerpo, dict) else {"raw": cuerpo}
            return {"ok": False, "status": respuesta.status_code}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
