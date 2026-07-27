import httpx
from typing import Any, Optional
from app.config import settings


class UserService:
    def __init__(self):
        self.base_url = settings.USERS_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        if not authorization:
            return {}
        token = authorization if authorization.startswith("Bearer ") else f"Bearer {authorization}"
        return {"Authorization": token}

    async def get_user_profile(self, user_id: str, authorization: Optional[str] = None) -> dict[str, Any]:
        """
        Obtiene el perfil desde ink-ms-users.
        Intenta endpoint interno (servicio a servicio) y luego GET /api/users/{id}.
        """
        headers = self._headers(authorization)
        paths = [
            f"/api/internal/users/{user_id}",
            f"/api/users/{user_id}",
        ]

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for path in paths:
                    response = await client.get(
                        f"{self.base_url}{path}",
                        headers=headers or None,
                    )
                    if response.status_code == 200:
                        data = response.json()
                        if isinstance(data, dict) and (data.get("id") or data.get("email") or data.get("fullName")):
                            return data
                return {}
        except Exception as e:
            print(f"Error obteniendo perfil de usuario {user_id}: {e}")
            return {}

    async def save_organizer_quiz_score(
        self, user_id: str, score: float, authorization: Optional[str] = None
    ) -> bool:
        """POST /api/users/verify/quiz/organizer/{userId}?score="""
        return await self._save_quiz_score("organizer", user_id, score, authorization)

    async def save_trainer_quiz_score(
        self, user_id: str, score: float, authorization: Optional[str] = None
    ) -> bool:
        """POST /api/users/verify/quiz/trainer/{userId}?score="""
        return await self._save_quiz_score("trainer", user_id, score, authorization)

    async def _save_quiz_score(
        self,
        role_path: str,
        user_id: str,
        score: float,
        authorization: Optional[str] = None,
    ) -> bool:
        headers = self._headers(authorization)
        url = f"{self.base_url}/api/users/verify/quiz/{role_path}/{user_id}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(
                    url,
                    params={"score": score},
                    headers=headers or None,
                )
                if response.status_code < 300:
                    return True
                print(f"Error registrando quiz score ({response.status_code}): {response.text[:200]}")
                return False
        except Exception as e:
            print(f"Error llamando verify quiz score: {e}")
            return False
