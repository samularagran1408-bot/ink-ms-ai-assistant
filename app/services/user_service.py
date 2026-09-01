"""Cliente de ink-ms-users (perfiles, roles, quiz de aptitud y administración)."""

from typing import Any, Optional

import httpx

from app.config import settings


class UserService:
    """Consulta y actualiza usuarios en ink-ms-users vía HTTP."""

    def __init__(self):
        """Guarda la URL base de ink-ms-users desde la configuración."""
        self.base_url = settings.USERS_SERVICE_URL.rstrip("/")

    def _headers(self, authorization: Optional[str] = None) -> dict[str, str]:
        """Normaliza el JWT a cabecera ``Authorization: Bearer …``; vacío si no hay token."""
        if not authorization:
            return {}
        token = authorization if authorization.startswith("Bearer ") else f"Bearer {authorization}"
        return {"Authorization": token}

    async def get_my_profile(self, authorization: Optional[str] = None) -> dict[str, Any]:
        """Perfil del usuario autenticado.

        Llama ``GET /api/users/perfil`` con el JWT. Devuelve el dict del perfil
        (id, email, etc.) o ``{}`` si falta token o el microservicio falla.
        """
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
        """Resuelve el perfil si el email coincide con el usuario del token.

        Combina ``GET /api/users/perfil`` con roles de
        ``GET /api/internal/users/roles-by-email``. Si el email no es el de la
        sesión, devuelve ``{}`` (no busca a terceros por correo).
        """
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
        """Roles asociados a un correo.

        Llama ``GET /api/internal/users/roles-by-email?email=…`` (sin JWT).
        Devuelve la lista de roles o ``[]`` si el microservicio falla.
        """
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
        """Obtiene el perfil desde ink-ms-users.

        Si ``user_id`` es ``me``/``yo`` o coincide con el token, usa
        ``GET /api/users/perfil``. Si no, prueba ``GET /api/internal/users/{id}``
        y ``GET /api/users/{id}``. Devuelve el dict del perfil o ``{}``.
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
        """Estado de preparación e intentos del quiz de aptitud.

        Llama ``GET /api/users/verify/quiz/prep/{role_path}/{user_id}``
        (organizer o trainer). Devuelve el dict del microservicio o ``{}``.
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
        """Registra el puntaje del quiz de organizador (POST interno verify/quiz/organizer)."""
        return await self._save_quiz_score("organizer", user_id, score, authorization)

    async def save_trainer_quiz_score(
        self, user_id: str, score: float, authorization: Optional[str] = None
    ) -> bool:
        """Registra el puntaje del quiz de entrenador (POST interno verify/quiz/trainer)."""
        return await self._save_quiz_score("trainer", user_id, score, authorization)

    async def _save_quiz_score(
        self,
        role_path: str,
        user_id: str,
        score: float,
        authorization: Optional[str] = None,
    ) -> bool:
        """Envía el puntaje del quiz a ink-ms-users.

        Llama ``POST /api/users/verify/quiz/{role_path}/{user_id}?score=…``.
        Devuelve True si el microservicio responde 2xx.
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

    async def list_users(
        self, authorization: Optional[str] = None, *, solo_activos: bool = False
    ) -> list[dict[str, Any]]:
        """Lista usuarios para el panel admin.

        Llama ``GET /api/admin/users`` o ``GET /api/admin/users/active`` si
        ``solo_activos``. Requiere JWT. Devuelve la lista o ``[]``.
        """
        if not authorization:
            return []
        path = "/api/admin/users/active" if solo_activos else "/api/admin/users"
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                respuesta = await client.get(
                    f"{self.base_url}{path}",
                    headers=self._headers(authorization),
                )
                if respuesta.status_code == 200:
                    data = respuesta.json()
                    return data if isinstance(data, list) else []
        except Exception as exc:
            print(f"Error listando usuarios: {exc}")
        return []

    async def list_inactive_users(
        self, authorization: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Usuarios inactivos: ``GET /api/admin/users/inactive``. Requiere JWT. Lista o ``[]``."""
        if not authorization:
            return []
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                respuesta = await client.get(
                    f"{self.base_url}/api/admin/users/inactive",
                    headers=self._headers(authorization),
                )
                if respuesta.status_code == 200:
                    data = respuesta.json()
                    return data if isinstance(data, list) else []
        except Exception as exc:
            print(f"Error listando usuarios inactivos: {exc}")
        return []

    async def search_users(
        self,
        nombre: str = "",
        discapacidad: str = "",
        authorization: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        """Busca usuarios por nombre y/o discapacidad.

        Llama ``GET /api/admin/users/search`` con ``name`` y/o ``disability``.
        Sin filtros o sin JWT devuelve ``[]``.
        """
        if not authorization:
            return []
        params: dict[str, str] = {}
        if (nombre or "").strip():
            params["name"] = nombre.strip()
        if (discapacidad or "").strip():
            params["disability"] = discapacidad.strip()
        if not params:
            return []
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                respuesta = await client.get(
                    f"{self.base_url}/api/admin/users/search",
                    params=params,
                    headers=self._headers(authorization),
                )
                if respuesta.status_code == 200:
                    data = respuesta.json()
                    return data if isinstance(data, list) else []
        except Exception as exc:
            print(f"Error buscando usuarios: {exc}")
        return []
