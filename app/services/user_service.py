from typing import Any, Optional

import httpx

from app.config import settings


class UserService:
    def __init__(self):
        self.base_url = settings.USERS_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        if not authorization:
            return {}
        token = authorization if authorization.startswith("Bearer ") else f"Bearer {authorization}"
        return {"Authorization": token}

    async def get_my_profile(self, authorization: Optional[str] = None) -> dict[str, Any]:
        """Perfil del usuario del token: GET /api/users/perfil (fuente de verdad)."""
        if not authorization:
            return {}
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                respuesta = await client.get(
                    f"{self.base_url}/api/users/perfil",
                    headers=self._headers(authorization),
                )
                if respuesta.status_code == 200:
                    data = respuesta.json()
                    if isinstance(data, dict) and (data.get("id") or data.get("email")):
                        return data
        except Exception as exc:
            print(f"Error obteniendo /api/users/perfil: {exc}")
        return {}

    async def get_profile_by_email(
        self, email: str, authorization: Optional[str] = None
    ) -> dict[str, Any]:
        """Intenta resolver perfil por email (roles internos + búsqueda)."""
        if not email:
            return {}
        roles = await self.get_roles_by_email(email)
        # Algunos despliegues exponen admin; el interno por id es lo habitual.
        # Si ya tenemos perfil propio, no hace falta.
        perfil = await self.get_my_profile(authorization)
        if perfil and str(perfil.get("email", "")).lower() == email.lower():
            if roles and not perfil.get("roles"):
                perfil = {**perfil, "roles": roles}
            return perfil
        return {}

    async def get_roles_by_email(self, email: str) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                respuesta = await client.get(
                    f"{self.base_url}/api/internal/users/roles-by-email",
                    params={"email": email},
                )
                if respuesta.status_code == 200:
                    data = respuesta.json()
                    if isinstance(data, list):
                        return [str(r) for r in data]
        except Exception as exc:
            print(f"Error obteniendo roles de {email}: {exc}")
        return []

    async def get_user_profile(
        self, user_id: str, authorization: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Obtiene el perfil desde ink-ms-users.
        Prioriza /perfil si el id/email coincide con el token; si no, interno/público.
        """
        if not user_id:
            return {}

        # Atajo: "me" o petición propia → siempre el perfil autenticado
        if user_id in ("me", "yo") and authorization:
            return await self.get_my_profile(authorization)

        if authorization:
            mio = await self.get_my_profile(authorization)
            if mio and (
                str(mio.get("id")) == str(user_id)
                or str(mio.get("email", "")).lower() == str(user_id).lower()
            ):
                return mio

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
                        if isinstance(data, dict) and (
                            data.get("id") or data.get("email") or data.get("fullName")
                        ):
                            return data
                return {}
        except Exception as e:
            print(f"Error obteniendo perfil de usuario {user_id}: {e}")
            return {}

    async def get_quiz_prep_status(
        self, role: str, user_id: str, authorization: Optional[str] = None
    ) -> dict[str, Any]:
        """
        /**
         * Consulta el estado de prep/intentos del quiz en ink-ms-users.
         */
        """
        role_path = "organizer" if str(role).upper() in ("ORGANIZADOR", "ORGANIZER") else "trainer"
        headers = self._headers(authorization)
        url = f"{self.base_url}/api/users/verify/quiz/prep/{role_path}/{user_id}"
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=headers or None)
                if response.status_code == 200:
                    data = response.json()
                    return data if isinstance(data, dict) else {}
                print(f"Error quiz prep status ({response.status_code}): {response.text[:200]}")
        except Exception as e:
            print(f"Error consultando quiz prep: {e}")
        return {}

    async def save_organizer_quiz_score(
        self, user_id: str, score: float, authorization: Optional[str] = None
    ) -> bool:
        """
        /**
         * Registra el puntaje del quiz de organizador en ink-ms-users.
         */
        """
        return await self._save_quiz_score("organizer", user_id, score, authorization)

    async def save_trainer_quiz_score(
        self, user_id: str, score: float, authorization: Optional[str] = None
    ) -> bool:
        """
        /**
         * Registra el puntaje del quiz de entrenador en ink-ms-users.
         */
        """
        return await self._save_quiz_score("trainer", user_id, score, authorization)

    async def _save_quiz_score(
        self,
        role_path: str,
        user_id: str,
        score: float,
        authorization: Optional[str] = None,
    ) -> bool:
        """
        /**
         * POST interno a /api/users/verify/quiz/{role}/{userId}?score=...
         */
        """
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
