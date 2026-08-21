"""Escrituras del agente: confirmación explícita antes de llamar al MCP."""

from __future__ import annotations

from typing import Any, Optional

WRITE_TOOLS = frozenset(
    {
        "crear_evento",
        "editar_evento",
        "cancelar_evento",
        "inscribirse_evento",
        "registrar_discapacidad",
        "editar_discapacidad",
        "desactivar_discapacidad",
        "reactivar_discapacidad",
        "crear_deporte",
        "editar_deporte",
        "eliminar_deporte",
        "crear_rutina",
        "publicar_rutina",
        "registrar_adaptacion",
        "editar_adaptacion",
        "eliminar_adaptacion",
        "bloquear_usuario",
        "desactivar_usuario",
        "activar_usuario",
        "eliminar_usuario",
        "asignar_rol",
        "reemplazar_roles",
    }
)

_CONFIRMA = frozenset(
    {
        "si",
        "sí",
        "ok",
        "okay",
        "vale",
        "dale",
        "confirmo",
        "confirmado",
        "acepto",
        "adelante",
        "yes",
        "de acuerdo",
    }
)
_CANCELA = frozenset({"no", "nop", "cancelar", "cancela", "mejor no", "olvidalo", "olvídalo"})


def es_write(nombre: str) -> bool:
    return (nombre or "").strip() in WRITE_TOOLS


def es_confirmacion(mensaje: str) -> bool:
    t = " ".join((mensaje or "").strip().lower().split())
    if t in _CONFIRMA or t.startswith("confirmo"):
        return True
    return t in {"si, confirmo", "sí, confirmo", "si confirmo", "sí confirmo"}


def es_cancelacion(mensaje: str) -> bool:
    t = " ".join((mensaje or "").strip().lower().split())
    return t in _CANCELA or t.startswith("cancel")


def resumen_write(nombre: str, args: dict[str, Any]) -> str:
    args = args or {}
    if nombre == "inscribirse_evento":
        return f"Inscribirte al evento {args.get('event_id') or args.get('eventId') or '?'}"
    if nombre == "crear_evento":
        return f"Crear el evento «{args.get('name') or '?'}» el {args.get('event_date') or '?'}"
    if nombre == "editar_evento":
        return f"Editar el evento {args.get('event_id') or '?'}"
    if nombre == "cancelar_evento":
        return f"Cancelar el evento {args.get('event_id') or '?'}"
    if nombre == "registrar_discapacidad":
        return f"Registrar el tipo de discapacidad «{args.get('name') or '?'}»"
    if nombre == "editar_discapacidad":
        return f"Editar la discapacidad id={args.get('disability_id')}"
    if nombre == "desactivar_discapacidad":
        return f"Desactivar la discapacidad id={args.get('disability_id')}"
    if nombre == "reactivar_discapacidad":
        return f"Reactivar la discapacidad id={args.get('disability_id')}"
    if nombre == "crear_deporte":
        return f"Crear el deporte «{args.get('name') or '?'}»"
    if nombre == "crear_rutina":
        return f"Crear la rutina «{args.get('name') or '?'}» en la plataforma"
    if nombre == "publicar_rutina":
        return f"Publicar la rutina {args.get('routine_id') or '?'}"
    if nombre == "editar_deporte":
        return f"Editar el deporte {args.get('sport_id') or args.get('name') or '?'}"
    if nombre == "eliminar_deporte":
        return f"Eliminar el deporte {args.get('sport_id') or '?'}"
    if nombre == "registrar_adaptacion":
        return (
            f"Registrar adaptación deporte {args.get('sport_id')} / "
            f"discapacidad {args.get('disability_id')}"
        )
    if nombre == "editar_adaptacion":
        return (
            f"Editar adaptación deporte {args.get('sport_id')} / "
            f"discapacidad {args.get('disability_id')}"
        )
    if nombre == "eliminar_adaptacion":
        return (
            f"Eliminar adaptación deporte {args.get('sport_id')} / "
            f"discapacidad {args.get('disability_id')}"
        )
    if nombre == "bloquear_usuario":
        return f"Bloquear a {args.get('nombre_o_email') or '?'}"
    if nombre == "desactivar_usuario":
        return f"Desactivar a {args.get('nombre_o_email') or '?'}"
    if nombre == "activar_usuario":
        return f"Activar a {args.get('nombre_o_email') or '?'}"
    if nombre == "eliminar_usuario":
        return f"Eliminar a {args.get('nombre_o_email') or '?'}"
    if nombre == "asignar_rol":
        return (
            f"Asignar el rol {args.get('role_name') or '?'} a "
            f"{args.get('nombre_o_email') or '?'}"
        )
    if nombre == "reemplazar_roles":
        return (
            f"Reemplazar roles de {args.get('nombre_o_email') or '?'} por "
            f"{args.get('roles_csv') or '?'}"
        )
    return f"Ejecutar {nombre}"


def mensaje_pedir_confirmacion(nombre: str, args: dict[str, Any]) -> str:
    return (
        f"Voy a {resumen_write(nombre, args).lower()}. "
        "No lo haré hasta que confirmes. Responde «Confirmo» para ejecutarla "
        "o «Cancelar» para no hacer nada."
    )
