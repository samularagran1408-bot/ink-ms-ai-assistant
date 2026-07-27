import httpx
from app.config import settings

class AuthService:
    def __init__(self):
        self.auth_url = f"{settings.AUTH_SERVICE_URL}/api/auth/validate"

    async def validate_token(self, token: str) -> dict:
        """Valida el token JWT contra el Auth Service"""
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