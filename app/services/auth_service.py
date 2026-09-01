"""Cliente de ink-ms-auth para validar JWT de sesión."""

import httpx
from app.config import settings

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
        """
        if not token:
            return None

        # Limpiar token
        if token.startswith("Bearer "):
            token = token.replace("Bearer ", "").strip()

        if not token:
            return None

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    self.auth_url,
                    headers={"Authorization": f"Bearer {token}"}
                )
                if response.status_code == 200:
                    return response.json()
                return None
        except Exception as e:
            print(f"Error validando token: {e}")
            return None