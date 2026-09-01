"""Mapa corporal para marcar dolor o limitación en un dibujo del cuerpo.

El chat (y los endpoints de riesgo/adaptar) extraen zonas a partir del texto
libre y de un campo `limitacion`. Las zonas detectadas se pintan en rojo
en el SVG del frontend.
"""

from __future__ import annotations

from typing import Any, Optional

from app.nlp.texto import normalizar

# id de zona → (etiqueta, palabras, vista)
_ZONAS: dict[str, tuple[str, tuple[str, ...], str]] = {
    "cabeza": ("Cabeza", ("cabeza", "craneo", "sien", "cara", "mandibula", "frente"), "frente"),
    "cuello": ("Cuello", ("cuello", "cervical", "nuca", "trapecio"), "ambas"),
    "hombro_izq": ("Hombro izquierdo", ("hombro izquierdo", "hombro izq", "deltoides izquierdo"), "frente"),
    "hombro_der": ("Hombro derecho", ("hombro derecho", "hombro der", "deltoides derecho"), "frente"),
    "hombro": ("Hombros", ("hombro", "hombros", "deltoides"), "frente"),
    "pecho": ("Pecho", ("pecho", "pectoral", "torax", "esternon", "costilla"), "frente"),
    "abdomen": ("Abdomen", ("abdomen", "abdominal", "panza", "barriga", "core", "ombligo"), "frente"),
    "brazo_izq": ("Brazo izquierdo", ("brazo izquierdo", "bicep izquierdo", "tricep izquierdo"), "frente"),
    "brazo_der": ("Brazo derecho", ("brazo derecho", "bicep derecho", "tricep derecho"), "frente"),
    "brazo": ("Brazos", ("brazo", "brazos", "bicep", "tricep", "humero"), "frente"),
    "codo_izq": ("Codo izquierdo", ("codo izquierdo", "codo izq"), "frente"),
    "codo_der": ("Codo derecho", ("codo derecho", "codo der"), "frente"),
    "codo": ("Codos", ("codo", "codos"), "frente"),
    "muneca_izq": ("Muñeca/mano izquierda", ("muneca izquierda", "mano izquierda", "muneca izq"), "frente"),
    "muneca_der": ("Muñeca/mano derecha", ("muneca derecha", "mano derecha", "muneca der"), "frente"),
    "muneca": ("Muñecas/manos", ("muneca", "munecas", "mano", "manos", "carpo"), "frente"),
    "espalda_alta": ("Espalda alta", ("espalda alta", "dorsal", "omóplato", "omoplato", "escapula"), "espalda"),
    "lumbar": ("Zona lumbar", ("lumbar", "lumbago", "cintura", "espalda baja"), "espalda"),
    "espalda": ("Espalda", ("espalda", "columna", "vertebral"), "espalda"),
    "cadera_izq": ("Cadera izquierda", ("cadera izquierda", "cadera izq"), "frente"),
    "cadera_der": ("Cadera derecha", ("cadera derecha", "cadera der"), "frente"),
    "cadera": ("Cadera", ("cadera", "caderas", "pelvis", "ingle"), "frente"),
    "gluteo": ("Glúteos", ("gluteo", "gluteos", "nalga"), "espalda"),
    "muslo_izq": ("Muslo izquierdo", ("muslo izquierdo", "cuadricep izquierdo"), "frente"),
    "muslo_der": ("Muslo derecho", ("muslo derecho", "cuadricep derecho"), "frente"),
    "muslo": ("Muslos", ("muslo", "muslos", "cuadricep", "isquio", "femur"), "frente"),
    "rodilla_izq": ("Rodilla izquierda", ("rodilla izquierda", "rodilla izq"), "frente"),
    "rodilla_der": ("Rodilla derecha", ("rodilla derecha", "rodilla der"), "frente"),
    "rodilla": ("Rodillas", ("rodilla", "rodillas", "rotula"), "frente"),
    "pantorrilla_izq": ("Pantorrilla izquierda", ("pantorrilla izquierda", "gemelo izquierdo"), "frente"),
    "pantorrilla_der": ("Pantorrilla derecha", ("pantorrilla derecha", "gemelo derecho"), "frente"),
    "pantorrilla": ("Pantorrillas", ("pantorrilla", "pantorrillas", "gemelo", "tibia", "canilla"), "frente"),
    "pie_izq": ("Pie/tobillo izquierdo", ("pie izquierdo", "tobillo izquierdo", "pie izq"), "frente"),
    "pie_der": ("Pie/tobillo derecho", ("pie derecho", "tobillo derecho", "pie der"), "frente"),
    "pie": ("Pies/tobillos", ("pie", "pies", "tobillo", "tobillos", "planta", "talon"), "frente"),
}

# Zonas genéricas se expanden a izquierda + derecha (o a las partes de espalda).
_EXPANSION: dict[str, tuple[str, ...]] = {
    "hombro": ("hombro_izq", "hombro_der"),
    "brazo": ("brazo_izq", "brazo_der"),
    "codo": ("codo_izq", "codo_der"),
    "muneca": ("muneca_izq", "muneca_der"),
    "cadera": ("cadera_izq", "cadera_der"),
    "muslo": ("muslo_izq", "muslo_der"),
    "rodilla": ("rodilla_izq", "rodilla_der"),
    "pantorrilla": ("pantorrilla_izq", "pantorrilla_der"),
    "pie": ("pie_izq", "pie_der"),
    "espalda": ("espalda_alta", "lumbar"),
    "gluteo": ("gluteo_izq", "gluteo_der"),
}

_DOLOR = (
    "dolor", "duele", "duelen", "molestia", "molesta", "lesion", "lesione",
    "pinchazo", "punzada", "inflam", "rigidez", "limitacion", "limitado",
)

_ETIQUETAS_FINALES: dict[str, str] = {
    "cabeza": "Cabeza",
    "cuello": "Cuello",
    "hombro_izq": "Hombro izquierdo",
    "hombro_der": "Hombro derecho",
    "pecho": "Pecho",
    "abdomen": "Abdomen",
    "brazo_izq": "Brazo izquierdo",
    "brazo_der": "Brazo derecho",
    "codo_izq": "Codo izquierdo",
    "codo_der": "Codo derecho",
    "muneca_izq": "Muñeca/mano izquierda",
    "muneca_der": "Muñeca/mano derecha",
    "espalda_alta": "Espalda alta",
    "lumbar": "Zona lumbar",
    "cadera_izq": "Cadera izquierda",
    "cadera_der": "Cadera derecha",
    "gluteo_izq": "Glúteo izquierdo",
    "gluteo_der": "Glúteo derecho",
    "muslo_izq": "Muslo izquierdo",
    "muslo_der": "Muslo derecho",
    "rodilla_izq": "Rodilla izquierda",
    "rodilla_der": "Rodilla derecha",
    "pantorrilla_izq": "Pantorrilla izquierda",
    "pantorrilla_der": "Pantorrilla derecha",
    "pie_izq": "Pie/tobillo izquierdo",
    "pie_der": "Pie/tobillo derecho",
}


def _texto_conjunto(mensaje: str, limitacion: Optional[str]) -> str:
    """Une mensaje y limitación ya normalizados para buscar zonas corporales."""
    return normalizar(f"{mensaje or ''} {limitacion or ''}")


def extraer_zonas(texto: str) -> list[str]:
    """Ids de zona ya expandidos a izquierda/derecha, en el orden de detección.

    Una mención genérica («rodilla») se parte en `_izq` y `_der`; si el texto
    ya nombra un lado concreto, no se duplica.
    """
    limpio = normalizar(texto or "")
    if not limpio:
        return []

    especificas: list[str] = []
    genericas: list[str] = []
    orden = sorted(_ZONAS.items(), key=lambda item: -max(len(p) for p in item[1][1]))
    for zona_id, (_etiqueta, palabras, _vista) in orden:
        if not any(p in limpio for p in palabras):
            continue
        if zona_id in _EXPANSION:
            genericas.append(zona_id)
        else:
            especificas.append(zona_id)

    concretas: list[str] = []
    vistos: set[str] = set()
    for zona in especificas:
        if zona in vistos:
            continue
        vistos.add(zona)
        concretas.append(zona)
    for zona in genericas:
        partes = _EXPANSION.get(zona, (zona,))
        if any(parte in vistos for parte in partes):
            continue
        for parte in partes:
            if parte in vistos:
                continue
            vistos.add(parte)
            concretas.append(parte)
    return concretas


def hay_dolor(texto: str) -> bool:
    """Indica si el texto menciona dolor, lesión, molestia o limitación."""
    limpio = normalizar(texto or "")
    return any(p in limpio for p in _DOLOR)


def debe_dibujar(
    mensaje: str,
    limitacion: Optional[str] = None,
    intencion: Optional[str] = None,
) -> bool:
    """Decide si el chat debe adjuntar el mapa corporal.

    Dibuja si hay `limitacion`, si la intención es lesiones/salud, o si el
    texto nombra zonas o palabras de dolor.
    """
    fuente = _texto_conjunto(mensaje, limitacion)
    if (limitacion or "").strip():
        return True
    if intencion in ("lesiones", "salud"):
        return True
    if extraer_zonas(fuente):
        return True
    return hay_dolor(fuente)


def mapa_corporal(
    mensaje: str = "",
    limitacion: Optional[str] = None,
) -> dict[str, Any]:
    """Construye el payload del dibujo: zonas en rojo, etiquetas, vista y nota."""
    fuente = _texto_conjunto(mensaje, limitacion)
    zonas = extraer_zonas(fuente)
    etiquetas = [_ETIQUETAS_FINALES.get(z, z) for z in zonas]
    vistas = set()
    for zona in zonas:
        if zona in ("espalda_alta", "lumbar", "gluteo_izq", "gluteo_der"):
            vistas.add("espalda")
        else:
            vistas.add("frente")
    if not vistas:
        vistas = {"frente", "espalda"}

    if zonas:
        nota = (
            "Las zonas en rojo marcan el dolor o la limitación que reportaste. "
            "No es un diagnóstico: si el dolor es agudo o persiste, consulta a un profesional."
        )
    else:
        nota = (
            "Dibujo del cuerpo listo. Indica la zona (por ejemplo «rodilla izquierda») "
            "para resaltarla en rojo."
        )

    return {
        "limitacion": (limitacion or "").strip() or None,
        "zonas_dolor": zonas,
        "etiquetas": etiquetas,
        "vista": "ambas" if len(vistas) > 1 else next(iter(vistas)),
        "nota": nota,
        "rf": "mapa_corporal",
    }
