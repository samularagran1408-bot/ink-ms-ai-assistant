"""Cliente de ink-ms-auth para validar JWT de sesión."""

from app.config import settings
from app.services.http_client import get_json
from app.utils.cache import CacheTTL, clave_token

# El mismo token se valida varias veces por pantalla; 30 s evita repetir el salto
# sin que un cierre de sesión tarde en notarse.
_VALIDACIONES = CacheTTL(30.0)


class AuthService:
    """Valida tokens JWT contra el microservicio de autenticación."""

    def __init__(self):
        """Fija la URL de validación: ``GET /api/auth/validate`` en ink-ms-auth."""
        self.auth_url = f"{settings.AUTH_SERVICE_URL}/api/auth/validate"

    async def validate_token(self, token: str) -> dict:
        """Comprueba un JWT contra ink-ms-auth.

        Llama ``GET /api/auth/validate`` con ``Authorization: Bearer``.
        Devuelve el payload del usuario (id, roles, etc.) si el token es
        válido (HTTP 200), o ``None`` si falta, está vacío o el servicio falla.
        El resultado se cachea unos segundos por token.
        """
        if not token:
            return None

        # Limpiar token
        if token.startswith("Bearer "):
            token = token.replace("Bearer ", "").strip()

        if not token:
            return None

        clave = clave_token(token)
        cacheado = _VALIDACIONES.get(clave)
        if cacheado is not None:
            return cacheado

        data = await get_json(
            self.auth_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=3.0,
        )
        if not isinstance(data, dict):
            return None
        return _VALIDACIONES.set(clave, data)
