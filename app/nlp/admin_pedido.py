"""Detecta pedidos admin (PDF, usuarios inactivos) sin depender del LLM."""

from __future__ import annotations

import re

from app.nlp.texto import normalizar

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_DESTINO_BLOQUEO = re.compile(
    r"(?:bloquear|desactivar|banear|suspender|desbloquear|activar)\s+"
    r"(?:el\s+usuario\s+|al\s+usuario\s+|usuario\s+|a\s+|al\s+)?(.+)",
    re.IGNORECASE,
)
_DESBLOQUEO = (
    "desbloquear",
    "activar usuario",
    "activar a",
    "reactivar usuario",
)

_INACTIVOS = (
    "inactivo",
    "inactivos",
    "desactivado",
    "desactivados",
    "no activos",
    "sin actividad",
)
_ACTIVOS = (
    "usuarios activos",
    "solo activos",
    "cuentas activas",
    "listar activos",
    "lista de activos",
)
_AUDIT = (
    "audit",
    "auditoria",
    "auditorias",
    "bitacora",
    "bitacoras",
    "logs",
)
_PDF = (
    "pdf",
    "exportar pdf",
    "exporta el dashboard",
    "descargar pdf",
    "bajar el pdf",
    "generar pdf",
    "exportar como pdf",
    "exporta como pdf",
)


def pide_desbloqueo(mensaje: str) -> bool:
    """True si pide activar/desbloquear, no bloquear."""
    texto = normalizar(mensaje)
    return any(pieza in texto for pieza in _DESBLOQUEO)


def extraer_destino_bloqueo(mensaje: str) -> str:
    """Email o nombre a bloquear/activar, extraído del mensaje del admin."""
    texto = (mensaje or "").strip()
    mail = _EMAIL.search(texto)
    if mail:
        return mail.group(0).strip()
    m = _DESTINO_BLOQUEO.search(texto)
    if not m:
        return ""
    dest = m.group(1).strip(" .,:;\"'«»")
    dest = re.split(r"\s+(?:porque|por|con motivo)\b", dest, maxsplit=1, flags=re.I)[0]
    dest = re.sub(r"\s+(de forma )?permanente(mente)?$", "", dest, flags=re.I)
    return dest.strip(" .,:;\"'")


def coincidencias_usuario(lista: list, destino: str) -> list[dict]:
    """Usuarios cuyo email o nombre encajan con el destino pedido."""
    clave = (destino or "").strip().lower()
    if not clave:
        return []
    usuarios = [u for u in (lista or []) if isinstance(u, dict)]
    exactos = [u for u in usuarios if str(u.get("email") or "").strip().lower() == clave]
    if exactos:
        return exactos
    if "@" in clave:
        return []
    return [
        u
        for u in usuarios
        if clave in str(u.get("fullName") or "").lower()
        or clave in str(u.get("email") or "").lower()
    ]


def pide_inactivos(mensaje: str) -> bool:
    """Indica si el mensaje pide listar usuarios inactivos o desactivados."""
    texto = normalizar(mensaje)
    return any(pieza in texto for pieza in _INACTIVOS)


def pide_activos(mensaje: str) -> bool:
    """Indica si pide usuarios activos, sin confundirlo con un pedido de inactivos."""
    if pide_inactivos(mensaje):
        return False
    texto = normalizar(mensaje)
    return any(pieza in texto for pieza in _ACTIVOS)


def pide_pdf_auditoria(mensaje: str) -> bool:
    """Indica si pide exportar auditoría, bitácora o logs a PDF."""
    texto = normalizar(mensaje)
    if "pdf" not in texto and "export" not in texto:
        return False
    return any(pieza in texto for pieza in _AUDIT)


def pide_exportar_pdf(mensaje: str) -> bool:
    """Indica si el mensaje pide generar o descargar un PDF (dashboard u otro)."""
    texto = normalizar(mensaje)
    return any(pieza in texto for pieza in _PDF)


def es_verdadero(valor: object) -> bool:
    """Convierte bool, número o cadena tipo true/si/1 en un booleano Python."""
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor != 0
    if isinstance(valor, str):
        return valor.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
    return False


def usuario_esta_activo(usuario: dict) -> bool | None:
    """Lee `isActive` del usuario; None si el campo no es un verdadero/falso reconocible."""
    valor = usuario.get("isActive")
    if valor is False or valor in (0, "0", "false", "False", "FALSE"):
        return False
    if valor is True or valor in (1, "1", "true", "True", "TRUE"):
        return True
    return None


def filtrar_usuarios(
    lista: list,
    *,
    solo_inactivos: bool = False,
    solo_activos: bool = False,
) -> list:
    """Filtra dicts de usuario por estado activo/inactivo.

    `solo_inactivos` incluye también a quienes no tienen `isActive` verdadero.
    `solo_activos` incluye a quienes no están marcados como inactivos.
    """
    usuarios = [u for u in (lista or []) if isinstance(u, dict)]
    if solo_inactivos:
        return [u for u in usuarios if usuario_esta_activo(u) is not True]
    if solo_activos:
        return [u for u in usuarios if usuario_esta_activo(u) is not False]
    return usuarios
