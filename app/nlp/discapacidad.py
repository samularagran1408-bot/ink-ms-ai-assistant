"""Normalización del tipo de discapacidad.

El perfil de ink-ms-users y el catálogo de ink-ms-sports usan etiquetas como
"Discapacidad Visual", "fisica" o "Discapacidad Física", mientras que el
chatbot recibe `disability_type` con valores cortos. Todo el servicio trabaja
con estas claves canónicas.
"""

import re

from app.nlp.texto import normalizar

CANONICAS = ("visual", "auditiva", "motriz", "cognitiva", "intelectual", "multiple", "general")

_ALIAS: dict[str, tuple[str, ...]] = {
    "visual": ("visual", "ciego", "ciega", "ceguera", "vision", "invidente", "baja vision"),
    "auditiva": ("auditiva", "auditivo", "sordo", "sorda", "sordera", "audicion", "hipoacusia"),
    "motriz": (
        "motriz", "motora", "motor", "fisica", "fisico", "movilidad", "silla", "ruedas",
        "paraplejia", "cuadriplejia", "hemiplejia", "amputacion", "muscular", "locomotor",
    ),
    "cognitiva": ("cognitiva", "cognitivo", "atencion", "memoria"),
    "intelectual": ("intelectual", "down", "aprendizaje", "mental"),
    "multiple": ("multiple", "multiples", "multidiscapacidad", "varias", "combinada", "sordoceguera"),
}

_NEUTRAS = ("general", "ninguna", "sin discapacidad", "na", "n a", "none", "null", "otra")


def canonizar(texto: str | None) -> str:
    """Devuelve la clave canónica de discapacidad a partir de texto libre."""
    limpio = normalizar(texto or "")
    if not limpio or limpio in _NEUTRAS:
        return "general"

    for clave, alias in _ALIAS.items():
        if any(a in limpio for a in alias):
            return clave
    return "general"


_PATRON_EXPLICITO = re.compile(r"discapacidad(?:es)?\s+([a-z]+(?:\s+[a-z]+)?)")

# Términos que sólo aparecen hablando de una discapacidad concreta. Los alias de
# _ALIAS son demasiado amplios para un mensaje libre ("varias dudas", "gracias
# por tu atención") y etiquetarían mal el turno.
_INEQUIVOCOS: dict[str, tuple[str, ...]] = {
    "visual": ("ciego", "ciega", "ciegos", "ciegas", "ceguera", "invidente", "baja vision"),
    "auditiva": ("sordo", "sorda", "sordos", "sordas", "sordera", "hipoacusia"),
    "motriz": (
        "silla de ruedas", "paraplejia", "cuadriplejia", "hemiplejia",
        "amputacion", "movilidad reducida",
    ),
    "intelectual": ("sindrome de down",),
    "multiple": ("sordoceguera", "multidiscapacidad"),
}


def mencionada(texto: str | None) -> str:
    """Discapacidad que nombra el propio mensaje, o "" si no habla de ninguna.

    Sirve para no responder con la discapacidad del perfil cuando el usuario
    pregunta por otra distinta ("deportes para discapacidad motriz").
    """
    limpio = normalizar(texto or "")
    if not limpio:
        return ""
    for coincidencia in _PATRON_EXPLICITO.finditer(limpio):
        clave = canonizar(coincidencia.group(1))
        if clave != "general":
            return clave
    for clave, terminos in _INEQUIVOCOS.items():
        if any(t in limpio for t in terminos):
            return clave
    return ""


def coincide(discapacidad_usuario: str | None, *candidatos: str | None) -> bool:
    """Indica si alguno de los candidatos corresponde a la discapacidad dada.

    Con discapacidad "general" (o sin dato) se considera que todo es compatible,
    porque no hay criterio por el que descartar.
    """
    usuario = canonizar(discapacidad_usuario)
    if usuario == "general":
        return True
    return any(canonizar(c) == usuario for c in candidatos if c)


def descripcion(clave: str) -> str:
    """Etiqueta legible de la clave canónica (p. ej. motriz → discapacidad física)."""
    etiquetas = {
        "visual": "discapacidad visual",
        "auditiva": "discapacidad auditiva",
        "motriz": "discapacidad física o motriz",
        "cognitiva": "discapacidad cognitiva",
        "intelectual": "discapacidad intelectual",
        "multiple": "discapacidad múltiple",
        "general": "perfil general",
    }
    return etiquetas.get(clave, "perfil general")
