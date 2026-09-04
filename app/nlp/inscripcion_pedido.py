"""Extrae el evento al que el usuario quiere darse de baja."""

from __future__ import annotations

import re

from app.nlp.texto import normalizar

_NOMBRE_EVENTO = (
    re.compile(
        r"(?:al|del|en el|en|de)\s+evento(?:\s+de)?\s+(.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"inscripci[oó]n(?:\s+al|\s+del|\s+en(?:\s+el)?)?\s+"
        r"(?:evento\s+(?:de\s+)?)?(.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:darme de baja|anular|desinscribirme|quitarme)\s+"
        r"(?:del|de|al)\s+(?:evento\s+(?:de\s+)?)?(.+)$",
        re.IGNORECASE,
    ),
)


def extraer_nombre_evento(mensaje: str) -> str:
    """Nombre del evento pedido, o cadena vacía si no viene en el mensaje."""
    texto = (mensaje or "").strip()
    if not texto:
        return ""
    for patron in _NOMBRE_EVENTO:
        m = patron.search(texto)
        if not m:
            continue
        dest = m.group(1).strip(" .,:;«»\"'")
        dest = re.sub(r"^(el|la|los|las)\s+", "", dest, flags=re.I)
        dest = dest.strip(" .,:;«»\"'")
        if dest.lower() in {"evento", "el evento", "un evento"}:
            continue
        return dest
    return ""


def coincidencias_inscripcion(registros: list, nombre: str) -> list[dict]:
    """Inscripciones cuyo evento encaja con el nombre pedido."""
    regs = [r for r in (registros or []) if isinstance(r, dict)]
    clave = normalizar(nombre)
    if not clave:
        return regs
    hits = []
    for reg in regs:
        nom = normalizar(str(reg.get("eventName") or reg.get("name") or ""))
        if clave in nom or (nom and nom in clave):
            hits.append(reg)
    return hits
