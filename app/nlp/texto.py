"""Normalización de texto en español para la detección de intenciones.

El chatbot recibe mensajes con acentos, signos de interrogación y plurales.
Comparar directamente con palabras clave (como hacía la versión anterior con
`mensaje.lower().split()`) falla en casos tan comunes como "¿Qué rutinas hay?".
"""

import re
import unicodedata

# Palabras sin valor semántico que solo añaden ruido al comparar.
VACIAS = {
    "a", "al", "algo", "algun", "alguna", "algunas", "alguno", "algunos", "ante",
    "aqui", "asi", "aun", "bien", "cada", "casi", "como", "con", "cual", "cuales",
    "cuando", "cuanto", "de", "del", "desde", "donde", "dos", "el", "ella",
    "ellas", "ellos", "en", "entre", "era", "eres", "es", "esa", "esas", "ese",
    "eso", "esos", "esta", "estan", "estas", "este", "esto", "estos", "estoy",
    "hace", "hacer", "hasta", "hay", "he", "la", "las", "le", "les", "lo", "los",
    "mas", "me", "mi", "mis", "mucho", "muy", "nada", "ni", "no", "nos", "o",
    "otra", "otro", "para", "pero", "poco", "por", "porque", "pues", "que",
    "quien", "se", "ser", "si", "sin", "sobre", "solo", "son", "soy", "su",
    "sus", "tambien", "tan", "te", "tengo", "ti", "tiene", "tu", "tus", "un",
    "una", "uno", "unos", "y", "ya", "yo",
}

_SUFIJOS = (
    "amientos", "imientos", "amiento", "imiento", "aciones", "adores", "adoras",
    "ancias", "encias", "idades", "amente", "acion", "ancia", "encia", "idad",
    "ador", "adora", "ando", "endo", "iendo", "ados", "idos", "adas", "idas",
    "ar", "er", "ir", "es", "as", "os", "s",
)


def quitar_acentos(texto: str) -> str:
    descompuesto = unicodedata.normalize("NFD", texto or "")
    return "".join(c for c in descompuesto if unicodedata.category(c) != "Mn")


def normalizar(texto: str) -> str:
    """Minúsculas, sin acentos, sin signos y con espacios colapsados."""
    limpio = quitar_acentos((texto or "").lower())
    limpio = re.sub(r"[^a-z0-9ñ\s]+", " ", limpio)
    return re.sub(r"\s+", " ", limpio).strip()


def raiz(palabra: str) -> str:
    """Raíz aproximada para que 'ejercicios' y 'ejercicio' coincidan.

    No es un stemmer lingüístico completo; basta para emparejar palabras clave
    del dominio sin añadir dependencias externas.
    """
    if len(palabra) <= 4:
        return palabra
    for sufijo in _SUFIJOS:
        if palabra.endswith(sufijo) and len(palabra) - len(sufijo) >= 4:
            return palabra[: -len(sufijo)]
    return palabra


def tokenizar(texto: str, quitar_vacias: bool = True) -> list[str]:
    palabras = normalizar(texto).split()
    if quitar_vacias:
        palabras = [p for p in palabras if p not in VACIAS]
    return palabras


def raices(texto: str) -> set[str]:
    return {raiz(p) for p in tokenizar(texto)}
