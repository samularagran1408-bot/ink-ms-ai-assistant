"""Elige el dominio de crew a partir del mensaje (mismas intenciones del chat).

Si el cliente manda un dominio válido, se respeta. ``auto`` clasifica.
Saludos y soporte no son crew: el front debe usar ``POST /api/ai/chat``.
Los dominios se filtran por rol JWT (misma idea que agents/*.md del MCP).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from app.nlp.intenciones import clasificar
from app.nlp.texto import normalizar
from app.tools.writes import es_confirmacion

DOMINIOS = (
    "investigacion",
    "quiz",
    "competencia",
    "automatizado",
    "consulta",
)
DOMINIOS_SET = frozenset(DOMINIOS)

CATALOGO: tuple[dict[str, str], ...] = (
    {
        "id": "investigacion",
        "via": "mcp",
        "descripcion": "Métricas, dashboard, conteos, auditoría y listados agregados.",
    },
    {
        "id": "quiz",
        "via": "agente",
        "descripcion": "Umbrales y banco de quiz organizador/entrenador.",
    },
    {
        "id": "competencia",
        "via": "agente",
        "descripcion": "Plan competitivo y riesgo/fatiga a nivel de plan.",
    },
    {
        "id": "automatizado",
        "via": "sandbox",
        "descripcion": "CRUD fake. No toca Users ni Sports. Exige Confirmo.",
    },
    {
        "id": "consulta",
        "via": "mcp",
        "descripcion": "Perfil, inscripciones y recomendaciones para esa persona.",
    },
)

# Alineado con ink-mcp-inklusport/agents/*.md y tools/roles.py.
_DOMINIOS_POR_ROL: dict[str, tuple[str, ...]] = {
    "USUARIO": ("consulta", "competencia"),
    "ENTRENADOR": ("quiz", "competencia", "consulta", "automatizado"),
    "ORGANIZADOR": ("quiz", "automatizado", "consulta", "investigacion"),
    "ADMIN": DOMINIOS,
}

_ALIAS_ROL = {
    "ADMINISTRADOR": "ADMIN",
    "ADMIN": "ADMIN",
    "ORGANIZER": "ORGANIZADOR",
    "ORGANIZADOR": "ORGANIZADOR",
    "COACH": "ENTRENADOR",
    "TRAINER": "ENTRENADOR",
    "ENTRENADOR": "ENTRENADOR",
    "USER": "USUARIO",
    "USUARIO": "USUARIO",
}

# Pistas de métricas de plataforma (no «cuántos eventos hay», eso es consulta).
_PISTAS_INVESTIGACION = (
    "cuantos usuarios",
    "cuantas usuarios",
    "dashboard",
    "auditoria",
    "metricas",
    "listar usuarios",
    "audit log",
)

# Intenciones que el chatbot ya resuelve; un crew no aporta.
_SOLO_CHAT = frozenset(
    {
        "saludo",
        "despedida",
        "agradecimiento",
        "ayuda",
        "nutricion",
        "motivacion",
        "navegacion_voz",
        "accesibilidad",
        "soporte",
        "plataforma",
        "salud",
        "respiracion",
        "equipamiento",
    }
)

_INTENCION_A_DOMINIO: dict[str, str] = {
    "quiz": "quiz",
    "verificacion_entrenador": "quiz",
    "verificacion_organizador": "quiz",
    "lesiones": "competencia",
    "descanso": "competencia",
    "crear_evento": "automatizado",
    "crear_deporte": "automatizado",
    "crear_rutina": "automatizado",
    "bloquear_usuario": "automatizado",
    "gestionar_roles": "automatizado",
    "exportar_pdf": "investigacion",
    "listar_usuarios": "investigacion",
    "progreso": "investigacion",
    "eventos": "consulta",
    "inscripcion": "consulta",
    "deportes": "consulta",
    "discapacidades": "consulta",
    "adaptaciones": "consulta",
    "rutinas": "consulta",
    "ejercicios": "consulta",
    "cuenta": "consulta",
    "calentamiento": "consulta",
    "estiramiento": "consulta",
    "objetivos": "consulta",
    "peso": "consulta",
    "frecuencia": "consulta",
    "donde_entrenar": "consulta",
}


@dataclass(frozen=True)
class Enrutado:
    """Resultado del enrutado: dominio listo o aviso de usar el chat."""

    dominio: Optional[str]
    origen: str
    intencion: Optional[str]
    confianza: float
    usar_chat: bool = False
    detalle: str = ""


class EnrutadoAmbiguo(Exception):
    """El mensaje no apunta a un dominio con suficiente confianza."""

    def __init__(self, detalle: str, intencion: Optional[str], confianza: float) -> None:
        super().__init__(detalle)
        self.detalle = detalle
        self.intencion = intencion
        self.confianza = confianza


class EnrutadoAlChat(Exception):
    """Saludo u otra intención que no debe ir a un crew."""

    def __init__(self, detalle: str, intencion: Optional[str], confianza: float) -> None:
        super().__init__(detalle)
        self.detalle = detalle
        self.intencion = intencion
        self.confianza = confianza


class EnrutadoProhibido(Exception):
    """El rol JWT no puede usar ese dominio de crew."""

    def __init__(
        self,
        detalle: str,
        dominio: Optional[str],
        permitidos: Sequence[str],
        intencion: Optional[str] = None,
        confianza: float = 0.0,
    ) -> None:
        super().__init__(detalle)
        self.detalle = detalle
        self.dominio = dominio
        self.permitidos = list(permitidos)
        self.intencion = intencion
        self.confianza = confianza


def canonizar_rol(rol: str) -> Optional[str]:
    """ADMIN | ENTRENADOR | ORGANIZADOR | USUARIO, o None si no se reconoce."""
    clave = (rol or "").strip().upper().replace("ROLE_", "")
    return _ALIAS_ROL.get(clave)


def dominios_permitidos(roles: Optional[Iterable[str]]) -> tuple[str, ...]:
    """Unión de dominios de los roles JWT. Sin rol válido → atleta."""
    unidos: list[str] = []
    vistos: set[str] = set()
    for rol in roles or ():
        canon = canonizar_rol(str(rol))
        if not canon:
            continue
        for dominio in _DOMINIOS_POR_ROL.get(canon, ()):
            if dominio not in vistos:
                vistos.add(dominio)
                unidos.append(dominio)
    if not unidos:
        unidos = list(_DOMINIOS_POR_ROL["USUARIO"])
    return tuple(unidos)


def catalogo_para_roles(roles: Optional[Iterable[str]]) -> list[dict[str, str]]:
    """Subconjunto de CATALOGO visible para esos roles."""
    permitidos = set(dominios_permitidos(roles))
    return [item for item in CATALOGO if item["id"] in permitidos]


def rol_principal(roles: Optional[Iterable[str]]) -> str:
    """Rol con más privilegio (admin > organizador > entrenador > usuario)."""
    prioridad = ("ADMIN", "ORGANIZADOR", "ENTRENADOR", "USUARIO")
    canonicos = {canonizar_rol(str(r)) for r in (roles or ())}
    canonicos.discard(None)
    for rol in prioridad:
        if rol in canonicos:
            return rol
    return "USUARIO"


def _normalizar_pedido(dominio: Optional[str]) -> str:
    texto = normalizar(dominio or "")
    texto = texto.replace(" ", "")
    if texto in {"", "auto", "automatico"}:
        return "auto"
    if texto == "investigacion":
        return "investigacion"
    return texto


def _asegurar_permiso(
    dominio: str,
    roles: Optional[Iterable[str]],
    *,
    intencion: Optional[str] = None,
    confianza: float = 1.0,
) -> None:
    """403 lógico si el rol no cubre el dominio."""
    if roles is None:
        return
    permitidos = dominios_permitidos(roles)
    if dominio in permitidos:
        return
    raise EnrutadoProhibido(
        (
            f"El dominio «{dominio}» no está disponible para tu rol. "
            f"Usa uno de: {', '.join(permitidos)}."
        ),
        dominio,
        permitidos,
        intencion=intencion,
        confianza=confianza,
    )


def resolver_dominio(
    mensaje: str,
    dominio_pedido: Optional[str] = None,
    roles: Optional[Iterable[str]] = None,
) -> Enrutado:
    """Resuelve el dominio. El pedido explícito gana; ``auto`` clasifica.

    ``roles=None`` no filtra (CLI/tests). El router pasa los roles del JWT.
    """
    pedido = _normalizar_pedido(dominio_pedido)
    if pedido != "auto":
        if pedido not in DOMINIOS_SET:
            raise EnrutadoAmbiguo(
                f"dominio debe ser auto o uno de: {', '.join(DOMINIOS)}",
                None,
                0.0,
            )
        _asegurar_permiso(pedido, roles)
        return Enrutado(
            dominio=pedido,
            origen="cliente",
            intencion=None,
            confianza=1.0,
        )

    if es_confirmacion(mensaje):
        _asegurar_permiso("automatizado", roles, confianza=1.0)
        return Enrutado(
            dominio="automatizado",
            origen="confirmo",
            intencion=None,
            confianza=1.0,
            detalle="Confirmo sin dominio: sandbox (el front debería reenviar el dominio).",
        )

    clas = clasificar(mensaje)
    nombre = clas.get("nombre")
    confianza = float(clas.get("confianza") or 0.0)

    if nombre in _SOLO_CHAT:
        raise EnrutadoAlChat(
            "Esa intención la atiende POST /api/ai/chat, no un crew.",
            nombre,
            confianza,
        )

    texto = normalizar(mensaje)
    if any(pista in texto for pista in _PISTAS_INVESTIGACION):
        _asegurar_permiso(
            "investigacion",
            roles,
            intencion=nombre,
            confianza=max(confianza, 0.5),
        )
        return Enrutado(
            dominio="investigacion",
            origen="auto",
            intencion=nombre,
            confianza=max(confianza, 0.5),
        )

    if not nombre:
        raise EnrutadoAmbiguo(
            "No está claro el dominio. Envía dominio o consulta GET /api/ai/crew/dominios.",
            clas.get("mejor_candidato"),
            confianza,
        )

    dominio = _INTENCION_A_DOMINIO.get(nombre)
    if dominio is None:
        raise EnrutadoAmbiguo(
            f"La intención «{nombre}» no tiene crew. Envía dominio o usa el chat.",
            nombre,
            confianza,
        )

    _asegurar_permiso(dominio, roles, intencion=nombre, confianza=confianza)
    return Enrutado(
        dominio=dominio,
        origen="auto",
        intencion=nombre,
        confianza=confianza,
    )


if __name__ == "__main__":
    pruebas = (
        ("¿Cuál es el umbral del quiz de organizador?", "auto"),
        ("Hola", "auto"),
        ("Crea un evento Copa sandbox el 2026-09-15", "auto"),
        ("Confirmo", "auto"),
        ("Recomiéndame eventos", "auto"),
        ("¿Cuántos usuarios hay?", "auto"),
        ("Explícame el quiz", "quiz"),
        ("¿Cuántos eventos hay?", "auto"),
    )
    for texto, pedido in pruebas:
        try:
            r = resolver_dominio(texto, pedido)
            print(f"OK  pedido={pedido!r} → {r.dominio} ({r.origen}) int={r.intencion}")
        except EnrutadoAlChat as exc:
            print(f"CHAT pedido={pedido!r} int={exc.intencion} — {exc.detalle}")
        except EnrutadoAmbiguo as exc:
            print(f"??  pedido={pedido!r} int={exc.intencion} — {exc.detalle}")
        print(f"    {texto!r}")
