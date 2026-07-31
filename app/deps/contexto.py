"""Resolución del usuario autenticado a partir del JWT + perfil de ink-ms-users.

El endpoint /api/auth/validate sólo devuelve {valid, email}. La discapacidad,
id y roles reales viven en GET /api/users/perfil. Este módulo evita que los
agentes inventen perfil o usen un usuario_id ajeno del body.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from fastapi import Header, HTTPException

from app.nlp.discapacidad import canonizar
from app.services.auth_service import AuthService
from app.services.user_service import UserService

_auth = AuthService()
_users = UserService()

ROLES_CONSULTA_AJENA = frozenset({"ADMIN", "ENTRENADOR"})


@dataclass
class UserContext:
    id: str
    email: str
    full_name: str = "Usuario"
    disability: str = "general"
    disability_raw: Optional[str] = None
    roles: list[str] = field(default_factory=list)
    authorization: Optional[str] = None
    perfil: dict = field(default_factory=dict)
    autenticado: bool = False
    es_demo: bool = False

    def tiene_rol(self, *roles: str) -> bool:
        propios = {r.upper() for r in self.roles}
        return any(r.upper() in propios for r in roles)

    def puede_consultar_a(self, otro_id: Optional[str]) -> bool:
        if not otro_id or otro_id in (self.id, self.email, "me", "yo"):
            return True
        return self.tiene_rol(*ROLES_CONSULTA_AJENA)


async def resolver_contexto(
    authorization: Optional[str] = None,
    usuario_id_solicitado: Optional[str] = None,
    *,
    require_auth: bool = True,
) -> UserContext:
    """Resuelve el perfil efectivo para la petición.

    - Con token: carga GET /api/users/perfil (fuente de verdad de discapacidad).
    - usuario_id ajeno: sólo ADMIN/ENTRENADOR; el resto se fuerza al propio.
    - Sin token: 401 si require_auth, si no contexto demo.
    """
    header = _normalizar_auth(authorization)

    if not header:
        if require_auth:
            raise HTTPException(
                status_code=401,
                detail="Authorization Bearer obligatorio. Inicia sesión en /api/auth/login.",
            )
        return UserContext(
            id="demo-user",
            email="demo@user.com",
            roles=["USUARIO"],
            disability="general",
            es_demo=True,
            autenticado=False,
        )

    auth_data = await _auth.validate_token(header)
    if not auth_data or auth_data.get("valid") is False or not auth_data.get("email"):
        raise HTTPException(status_code=401, detail="Token inválido o expirado.")

    email = str(auth_data.get("email") or "").strip()

    perfil = await _users.get_my_profile(header)
    if not perfil:
        perfil = await _users.get_profile_by_email(email, header)

    if not perfil:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No hay perfil en ink-ms-users para {email}. "
                "Completa el registro o consulta GET /api/users/perfil."
            ),
        )

    if not perfil.get("roles"):
        roles = await _users.get_roles_by_email(email)
        if roles:
            perfil = {**perfil, "roles": roles}

    ctx = _desde_perfil(perfil, header, email)

    solicitado = (usuario_id_solicitado or "").strip() or None
    if solicitado and solicitado not in (ctx.id, ctx.email, "me", "yo", "demo-user"):
        if not ctx.puede_consultar_a(solicitado):
            # No filtramos en silencio: usamos el perfil del token
            return ctx
        ajeno = await _users.get_user_profile(solicitado, header)
        if not ajeno:
            ajeno = await _users.get_profile_by_email(solicitado, header)
        if ajeno:
            return _desde_perfil(ajeno, header, ajeno.get("email") or solicitado, roles_extra=ctx.roles)

    return ctx


async def require_auth(authorization: Optional[str] = Header(None)) -> UserContext:
    return await resolver_contexto(authorization, require_auth=True)


def discapacidad_efectiva(
    ctx: UserContext,
    override: Optional[str] = None,
    *,
    permitir_override: bool = False,
) -> str:
    """Perfil del token gana; override sólo si el rol lo permite (entrenador/admin)."""
    if override and permitir_override and ctx.tiene_rol("ADMIN", "ENTRENADOR"):
        return canonizar(override)
    return canonizar(ctx.disability_raw or ctx.disability)


def _desde_perfil(
    perfil: dict,
    authorization: Optional[str],
    email_fallback: str,
    roles_extra: Optional[list[str]] = None,
) -> UserContext:
    roles = perfil.get("roles") or roles_extra or []
    if isinstance(roles, str):
        roles = [r.strip() for r in roles.split(",") if r.strip()]
    raw = perfil.get("disability") or perfil.get("disabilityType")
    return UserContext(
        id=str(perfil.get("id") or email_fallback),
        email=str(perfil.get("email") or email_fallback),
        full_name=str(perfil.get("fullName") or perfil.get("full_name") or "Usuario"),
        disability=canonizar(raw),
        disability_raw=raw,
        roles=[str(r) for r in roles],
        authorization=authorization,
        perfil=perfil,
        autenticado=True,
        es_demo=False,
    )


def _normalizar_auth(authorization: Optional[str]) -> Optional[str]:
    if not authorization or not authorization.strip():
        return None
    valor = authorization.strip()
    if not valor.startswith("Bearer "):
        return f"Bearer {valor}"
    if not valor[7:].strip():
        return None
    return valor
