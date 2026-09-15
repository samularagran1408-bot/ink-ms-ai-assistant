"""Cliente de ink-ms-users (perfiles, roles, quiz de aptitud y administración)."""

from typing import Any, Optional

import httpx

from app.config import settings
from app.services.http_client import get_client, get_json
from app.utils.cache import CacheTTL, clave_token

# El perfil y los roles cambian poco y se piden en cada endpoint del asistente.
_PERFILES = CacheTTL(30.0)
_PERFILES_POR_ID = CacheTTL(30.0)
_ROLES = CacheTTL(60.0)


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
        Se cachea unos segundos por token.
        """
        if not authorization:
            return {}
        clave = clave_token(authorization)
        cacheado = _PERFILES.get(clave)
        if cacheado is not None:
            return cacheado

        data = await get_json(
            f"{self.base_url}/api/users/perfil",
            headers=self._headers(authorization),
            timeout=3.0,
        )
        if isinstance(data, dict) and (data.get("id") or data.get("email")):
            return _PERFILES.set(clave, data)
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
        perfil = await self.get_my_profile(authorization)
        if not perfil or str(perfil.get("email", "")).lower() != email.lower():
            return {}
        if perfil.get("roles"):
            return perfil
        roles = await self.get_roles_by_email(email)
        return {**perfil, "roles": roles} if roles else perfil

    async def get_roles_by_email(self, email: str) -> list[str]:
        """Roles asociados a un correo.

        Llama ``GET /api/internal/users/roles-by-email?email=…`` (sin JWT).
        Devuelve la lista de roles o ``[]`` si el microservicio falla.
        """
        if not email:
            return []
        clave = email.strip().lower()
        cacheado = _ROLES.get(clave)
        if cacheado is not None:
            return cacheado

        data = await get_json(
            f"{self.base_url}/api/internal/users/roles-by-email",
            params={"email": email},
            timeout=3.0,
        )
        if isinstance(data, list):
            return _ROLES.set(clave, [str(r) for r in data])
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

        clave = str(user_id).strip().lower()
        cacheado = _PERFILES_POR_ID.get(clave)
        if cacheado is not None:
            return cacheado

        headers = self._headers(authorization)
        for path in (f"/api/internal/users/{user_id}", f"/api/users/{user_id}"):
            data = await get_json(
                f"{self.base_url}{path}",
                headers=headers,
                timeout=3.0,
            )
            if isinstance(data, dict) and (
                data.get("id") or data.get("email") or data.get("fullName")
            ):
                return _PERFILES_POR_ID.set(clave, data)
        return {}

    async def get_quiz_prep_status(
        self, role: str, user_id: str, authorization: Optional[str] = None
    ) -> dict[str, Any]:
        """Estado de preparación e intentos del quiz de aptitud.

        Llama ``GET /api/users/verify/quiz/prep/{role_path}/{user_id}``
        (organizer o trainer). Devuelve el dict del microservicio o ``{}``.
        """
        role_path = "organizer" if str(role).upper() in ("ORGANIZADOR", "ORGANIZER") else "trainer"
        data = await get_json(
            f"{self.base_url}/api/users/verify/quiz/prep/{role_path}/{user_id}",
            headers=self._headers(authorization),
            timeout=2.5,
        )
        return data if isinstance(data, dict) else {}

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
            cliente = await get_client()
            response = await cliente.post(
                url,
                params={"score": score},
                headers=headers or None,
                timeout=httpx.Timeout(8.0, connect=1.5),
            )
            if response.status_code < 300:
                # El perfil cacheado ya no refleja el quiz aprobado.
                _PERFILES.invalidar()
                _PERFILES_POR_ID.invalidar(str(user_id).strip().lower())
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
        data = await get_json(
            f"{self.base_url}{path}",
            headers=self._headers(authorization),
            timeout=5.0,
        )
        return data if isinstance(data, list) else []

    async def list_inactive_users(
        self, authorization: Optional[str] = None
    ) -> list[dict[str, Any]]:
        """Usuarios inactivos: ``GET /api/admin/users/inactive``. Requiere JWT. Lista o ``[]``."""
        if not authorization:
            return []
        data = await get_json(
            f"{self.base_url}/api/admin/users/inactive",
            headers=self._headers(authorization),
            timeout=5.0,
        )
        return data if isinstance(data, list) else []

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
        data = await get_json(
            f"{self.base_url}/api/admin/users/search",
            params=params,
            headers=self._headers(authorization),
            timeout=5.0,
        )
        return data if isinstance(data, list) else []
