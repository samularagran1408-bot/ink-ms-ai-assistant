"""Detecta pedidos admin (PDF, usuarios inactivos) sin depender del LLM."""

from __future__ import annotations

from app.nlp.texto import normalizar

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


def pide_inactivos(mensaje: str) -> bool:
    texto = normalizar(mensaje)
    return any(pieza in texto for pieza in _INACTIVOS)


def pide_activos(mensaje: str) -> bool:
    if pide_inactivos(mensaje):
        return False
    texto = normalizar(mensaje)
    return any(pieza in texto for pieza in _ACTIVOS)


def pide_pdf_auditoria(mensaje: str) -> bool:
    texto = normalizar(mensaje)
    if "pdf" not in texto and "export" not in texto:
        return False
    return any(pieza in texto for pieza in _AUDIT)


def pide_exportar_pdf(mensaje: str) -> bool:
    texto = normalizar(mensaje)
    return any(pieza in texto for pieza in _PDF)


def es_verdadero(valor: object) -> bool:
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return valor != 0
    if isinstance(valor, str):
        return valor.strip().lower() in {"1", "true", "yes", "si", "sí", "on"}
    return False


def usuario_esta_activo(usuario: dict) -> bool | None:
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
    usuarios = [u for u in (lista or []) if isinstance(u, dict)]
    if solo_inactivos:
        return [u for u in usuarios if usuario_esta_activo(u) is not True]
    if solo_activos:
        return [u for u in usuarios if usuario_esta_activo(u) is not False]
    return usuarios
