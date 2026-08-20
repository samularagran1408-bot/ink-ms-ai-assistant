"""Mapeo de roles JWT de Inklusport → tools del servidor MCP."""

from __future__ import annotations

# Misma tabla que ink-mcp-inklusport/src/server.py (TOOLS_POR_ROL).
TOOLS_POR_ROL: dict[str, list[str]] = {
    "usuario": [
        "listar_eventos",
        "listar_eventos_disponibles",
        "consultar_evento",
        "consultar_calendario_eventos",
        "listar_deportes",
        "consultar_usuario",
        "consultar_inscripciones",
        "inscribirse_evento",
        "listar_adaptaciones_deporte",
    ],
    "entrenador": [
        "listar_eventos",
        "listar_eventos_disponibles",
        "consultar_evento",
        "consultar_calendario_eventos",
        "listar_deportes",
        "consultar_usuario",
        "listar_rutinas_publicadas",
        "listar_adaptaciones_deporte",
        "listar_rutinas_entrenador",
        "crear_deporte",
        "crear_rutina",
        "publicar_rutina",
        "recomendar_deporte_nuevo",
        "recomendar_rutina_nueva",
        "listar_discapacidades",
        "consultar_discapacidad",
        "registrar_discapacidad",
        "editar_discapacidad",
        "desactivar_discapacidad",
        "reactivar_discapacidad",
    ],
    "organizador": [
        "listar_eventos",
        "listar_eventos_disponibles",
        "consultar_evento",
        "crear_evento",
        "editar_evento",
        "cancelar_evento",
        "consultar_calendario_eventos",
        "listar_deportes",
        "listar_discapacidades",
        "consultar_discapacidad",
        "consultar_inscripciones",
        "inscribirse_evento",
        "listar_adaptaciones_deporte",
        "recomendar_evento_nuevo",
    ],
    "admin": [
        "listar_eventos",
        "listar_eventos_disponibles",
        "consultar_evento",
        "crear_evento",
        "editar_evento",
        "cancelar_evento",
        "consultar_calendario_eventos",
        "inscribirse_evento",
        "listar_deportes",
        "consultar_usuario",
        "consultar_roles_por_email",
        "listar_usuarios",
        "buscar_usuarios",
        "listar_discapacidades",
        "consultar_discapacidad",
        "registrar_discapacidad",
        "editar_discapacidad",
        "desactivar_discapacidad",
        "reactivar_discapacidad",
        "listar_rutinas_publicadas",
        "listar_adaptaciones_deporte",
        "listar_rutinas_entrenador",
        "crear_deporte",
        "crear_rutina",
        "publicar_rutina",
        "consultar_inscripciones",
        "recomendar_evento_nuevo",
        "recomendar_deporte_nuevo",
        "recomendar_rutina_nueva",
    ],
}

# Tools del motor local disponibles para todos los roles.
TOOLS_LOCALES = (
    "generar_rutina",
    "listar_ejercicios",
    "info_quiz",
    "consultar_mi_perfil",
    "estadisticas_usuario",
)


def _claves_rol(roles_jwt: list[str]) -> set[str]:
    claves: set[str] = set()
    for rol in roles_jwt or []:
        r = str(rol).upper().replace("ROLE_", "")
        if r in ("ADMIN", "ADMINISTRADOR"):
            claves.add("admin")
        elif r in ("ORGANIZER", "ORGANIZADOR"):
            claves.add("organizador")
        elif r in ("TRAINER", "ENTRENADOR", "COACH"):
            claves.add("entrenador")
        elif r in ("USER", "USUARIO"):
            claves.add("usuario")
    if not claves:
        claves.add("usuario")
    return claves


def nombres_permitidos(roles_jwt: list[str]) -> set[str]:
    nombres: set[str] = set(TOOLS_LOCALES)
    for clave in _claves_rol(roles_jwt):
        nombres.update(TOOLS_POR_ROL.get(clave, []))
    return nombres


def filtrar_definiciones(
    definiciones: list[dict],
    roles_jwt: list[str],
) -> list[dict]:
    permitidos = nombres_permitidos(roles_jwt)
    out: list[dict] = []
    for item in definiciones:
        fn = (item.get("function") or {}) if isinstance(item, dict) else {}
        nombre = fn.get("name")
        if nombre in permitidos:
            out.append(item)
    return out
