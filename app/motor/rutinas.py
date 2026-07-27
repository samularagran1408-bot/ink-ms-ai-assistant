"""Motor local de generación de rutinas.

Selecciona ejercicios del catálogo filtrando por discapacidad, objetivo, nivel y
posición, y compone una sesión con calentamiento, bloque principal y vuelta a la
calma. La selección se aleatoriza con una semilla, así que dos peticiones no
devuelven la misma rutina.
"""

import random
from typing import Any, Iterable, Optional

from app.data.ejercicios import (
    CATALOGO_EJERCICIOS,
    OBJETIVOS,
    PAUTAS_DISCAPACIDAD,
    PERFILES_DISCAPACIDAD,
)
from app.nlp.discapacidad import canonizar, descripcion
from app.nlp.texto import normalizar

NIVEL_ORDEN = {"principiante": 1, "intermedio": 2, "avanzado": 3}

# Posiciones que quedan descartadas cuando se pide trabajar en una concreta.
# Pedir "en silla de ruedas" no puede devolver ejercicios de pie.
_INCOMPATIBLES_POSICION: dict[str, tuple[str, ...]] = {
    "silla": ("de_pie", "colchoneta"),
    "sentado": ("de_pie", "colchoneta"),
    "de_pie": ("colchoneta", "piscina"),
    "colchoneta": ("de_pie", "piscina"),
    "piscina": ("de_pie", "colchoneta", "silla", "sentado"),
}

_ALIAS_OBJETIVO: dict[str, tuple[str, ...]] = {
    "fuerza": ("fuerza", "fortalecer", "musculo", "muscular", "tonificar", "potencia"),
    "resistencia": ("resistencia", "cardio", "aerobico", "aguante", "fondo", "capacidad"),
    "movilidad": ("movilidad", "amplitud", "articular", "rango"),
    "flexibilidad": ("flexibilidad", "estirar", "estiramiento", "elasticidad"),
    "equilibrio": ("equilibrio", "estabilidad", "postural", "coordinacion"),
    "rehabilitacion": ("rehabilitacion", "recuperar", "recuperacion", "lesion", "dolor", "suave", "terapia"),
    "peso": ("peso", "adelgazar", "grasa", "calorias", "quemar"),
}

_ALIAS_POSICION: dict[str, tuple[str, ...]] = {
    "silla": ("silla de ruedas", "en silla", "silla", "ruedas"),
    "sentado": ("sentado", "sedestacion", "sentada"),
    "de_pie": ("de pie", "parado", "bipedo"),
    "colchoneta": ("colchoneta", "suelo", "piso", "tapete"),
    "piscina": ("piscina", "agua", "natacion", "acuatico"),
}

_ALIAS_NIVEL: dict[str, tuple[str, ...]] = {
    "principiante": ("principiante", "inicial", "basico", "empezar", "novato", "facil"),
    "intermedio": ("intermedio", "medio", "moderado"),
    "avanzado": ("avanzado", "alto", "experto", "intenso", "dificil"),
}


def _detectar(texto: str, alias: dict[str, tuple[str, ...]]) -> Optional[str]:
    limpio = normalizar(texto or "")
    if not limpio:
        return None
    for clave, palabras in alias.items():
        if any(p in limpio for p in palabras):
            return clave
    return None


def interpretar_objetivo(texto: str) -> str:
    return _detectar(texto, _ALIAS_OBJETIVO) or "general"


def interpretar_posicion(texto: str) -> Optional[str]:
    return _detectar(texto, _ALIAS_POSICION)


def interpretar_nivel(texto: str) -> Optional[str]:
    return _detectar(texto, _ALIAS_NIVEL)


def perfil_de(discapacidad: str) -> dict[str, Any]:
    return PERFILES_DISCAPACIDAD.get(discapacidad, PERFILES_DISCAPACIDAD["general"])


def _apto_para(ejercicio: dict, discapacidad: str) -> bool:
    """Comprueba la lista de discapacidades del ejercicio y el perfil de prescripción.

    Una lista vacía significa "sin contraindicación por discapacidad", pero el
    perfil todavía puede descartar el ejercicio por posición, esfuerzo o nivel.
    """
    permitidas = ejercicio.get("discapacidades") or []
    if permitidas and discapacidad != "general" and discapacidad not in permitidas:
        return False

    perfil = perfil_de(discapacidad)
    if ejercicio.get("posicion") in perfil["posiciones_excluidas"]:
        return False
    if (ejercicio.get("esfuerzo") or 0) > perfil["esfuerzo_maximo"]:
        return False
    tope = NIVEL_ORDEN.get(perfil["nivel_maximo"], 3)
    return NIVEL_ORDEN.get(ejercicio.get("nivel"), 2) <= tope


def _apto_posicion(ejercicio: dict, posicion: Optional[str]) -> bool:
    if not posicion:
        return True
    return ejercicio.get("posicion") not in _INCOMPATIBLES_POSICION.get(posicion, ())


def _apto_nivel(ejercicio: dict, nivel: str) -> bool:
    return NIVEL_ORDEN.get(ejercicio["nivel"], 2) <= NIVEL_ORDEN.get(nivel, 2)


def adaptacion_de(ejercicio: dict, discapacidad: str) -> str:
    """Texto de adaptación: la específica del ejercicio o la pauta general."""
    especifica = (ejercicio.get("adaptaciones") or {}).get(discapacidad)
    pauta = PAUTAS_DISCAPACIDAD.get(discapacidad, PAUTAS_DISCAPACIDAD["general"])["pauta"]
    if especifica:
        return f"{especifica} {pauta}"
    return pauta


def _puntuar(
    ejercicio: dict,
    objetivo: str,
    posicion: Optional[str],
    nivel: str,
    discapacidad: str,
) -> float:
    puntaje = 0.0
    if objetivo in (ejercicio.get("objetivos") or []):
        puntaje += 4.0
    if objetivo == "general":
        puntaje += 1.0
    if posicion and ejercicio.get("posicion") == posicion:
        puntaje += 2.5
    if ejercicio.get("nivel") == nivel:
        puntaje += 1.5

    perfil = perfil_de(discapacidad)

    # Un ejercicio con adaptación redactada para esta discapacidad está pensado
    # para ella: es mejor candidato que uno genéricamente compatible.
    if (ejercicio.get("adaptaciones") or {}).get(discapacidad):
        puntaje += 3.0

    # Diseñado en exclusiva para este perfil (p. ej. propulsión en silla).
    permitidas = ejercicio.get("discapacidades") or []
    if discapacidad in permitidas:
        puntaje += 1.5 + (1.5 if len(permitidas) <= 2 else 0.0)

    categorias = perfil["categorias_prioritarias"]
    if ejercicio.get("categoria") in categorias:
        # Se degrada según el orden: la primera categoría del perfil pesa más.
        puntaje += 2.5 - 0.5 * categorias.index(ejercicio["categoria"])

    puntaje -= perfil["posiciones_penalizadas"].get(ejercicio.get("posicion"), 0.0)
    return puntaje


def _seleccionar(
    candidatos: Iterable[dict],
    cantidad: int,
    objetivo: str,
    posicion: Optional[str],
    nivel: str,
    discapacidad: str,
    azar: random.Random,
) -> list[dict]:
    """Elige `cantidad` ejercicios priorizando puntaje y variando categorías."""
    pool = list(candidatos)
    if not pool:
        return []

    azar.shuffle(pool)
    pool.sort(key=lambda e: _puntuar(e, objetivo, posicion, nivel, discapacidad), reverse=True)

    elegidos: list[dict] = []
    categorias_usadas: set[str] = set()

    # Primera pasada: una categoría distinta cada vez, para no repetir estímulo
    for ejercicio in pool:
        if len(elegidos) >= cantidad:
            break
        if ejercicio["categoria"] not in categorias_usadas:
            elegidos.append(ejercicio)
            categorias_usadas.add(ejercicio["categoria"])

    # Segunda pasada: completar con los mejores restantes
    for ejercicio in pool:
        if len(elegidos) >= cantidad:
            break
        if ejercicio not in elegidos:
            elegidos.append(ejercicio)

    return elegidos[:cantidad]


def _formatear(ejercicio: dict, discapacidad: str) -> dict[str, Any]:
    """Ajusta volumen y descanso al perfil antes de exponer el ejercicio.

    El mismo ejercicio se prescribe distinto: menos series y más descanso en los
    perfiles que se fatigan antes o necesitan más tiempo entre instrucciones.
    """
    perfil = perfil_de(discapacidad)
    series = max(1, ejercicio["series"] + perfil["series_delta"])
    descanso = round(ejercicio["descanso"] * perfil["descanso_factor"])
    return {
        "id": ejercicio["id"],
        "nombre": ejercicio["nombre"],
        "categoria": ejercicio["categoria"],
        "fase": ejercicio["fase"],
        "posicion": ejercicio["posicion"],
        "nivel": ejercicio["nivel"],
        "repeticiones": ejercicio["repeticiones"],
        "series": series,
        "tiempo_estimado": ejercicio["tiempo_estimado"],
        "descanso": descanso,
        "esfuerzo": ejercicio["esfuerzo"],
        "musculos": ejercicio["musculos"],
        "material": ejercicio["material"],
        "instrucciones": ejercicio["instrucciones"],
        "adaptaciones": adaptacion_de(ejercicio, discapacidad),
        "seguridad": ejercicio.get("seguridad") or "",
    }


def _recomendaciones(
    discapacidad: str,
    objetivo: str,
    nivel: str,
    posicion: Optional[str],
    material: list[str],
    ejercicios: list[dict],
) -> list[str]:
    """Consejos concretos para esta sesión, no un texto fijo por discapacidad."""
    perfil = perfil_de(discapacidad)
    pauta = PAUTAS_DISCAPACIDAD.get(discapacidad, PAUTAS_DISCAPACIDAD["general"])

    consejos = [pauta["referencia"], *perfil["claves"]]

    if material:
        consejos.append(f"Ten preparado antes de empezar: {', '.join(material)}.")
    else:
        consejos.append("No necesitas material: puedes hacer la sesión completa tal cual.")

    if posicion:
        consejos.append(f"Toda la sesión está planteada para trabajar en posición {posicion.replace('_', ' ')}.")

    por_objetivo = {
        "fuerza": "Deja una o dos repeticiones en reserva en cada serie: la técnica manda sobre la carga.",
        "resistencia": "Busca un ritmo que te permita hablar entrecortado, no quedarte sin aire.",
        "movilidad": "Trabaja hasta notar tensión, nunca dolor, y sostén el final del recorrido.",
        "flexibilidad": "Mantén cada estiramiento de 20 a 30 segundos sin rebotes.",
        "equilibrio": "Ten siempre un apoyo al alcance de la mano antes de retirar la ayuda.",
        "rehabilitacion": "Ve al rango libre de dolor y para en cuanto la molestia suba de intensidad.",
        "peso": "El gasto viene de la constancia semanal, no de exprimir una sola sesión.",
        "general": "Progresa de menos a más y mantén la técnica controlada en todo el recorrido.",
    }
    consejos.append(por_objetivo.get(objetivo, por_objetivo["general"]))

    if nivel == "principiante":
        consejos.append("Al ser nivel principiante, prioriza aprender el movimiento antes que sumar series.")
    elif nivel == "avanzado":
        consejos.append("En nivel avanzado puedes acortar los descansos si mantienes la técnica.")

    esfuerzo_medio = (
        sum(e["esfuerzo"] for e in ejercicios) / len(ejercicios) if ejercicios else 0
    )
    if esfuerzo_medio >= 3.5:
        consejos.append("La sesión es exigente: deja al menos un día de descanso antes de repetirla.")

    return consejos


def _reparto(duracion_minutos: int) -> tuple[int, int, int]:
    """Número de ejercicios por bloque según la duración pedida."""
    if duracion_minutos <= 20:
        return 2, 3, 2
    if duracion_minutos <= 35:
        return 2, 4, 2
    if duracion_minutos <= 50:
        return 3, 5, 3
    return 3, 6, 3


def generar_rutina(
    discapacidad: str,
    objetivo_texto: str = "",
    tipo_texto: str = "",
    nivel: Optional[str] = None,
    duracion_minutos: int = 35,
    semilla: Optional[int] = None,
    catalogo: Optional[list[dict]] = None,
) -> dict[str, Any]:
    """Compone una rutina completa a partir del catálogo de ejercicios."""
    ejercicios_disponibles = catalogo or CATALOGO_EJERCICIOS
    clave_discapacidad = canonizar(discapacidad)
    objetivo = interpretar_objetivo(f"{objetivo_texto} {tipo_texto}")
    posicion = interpretar_posicion(f"{tipo_texto} {discapacidad}")
    nivel_final = nivel or interpretar_nivel(f"{tipo_texto} {objetivo_texto}") or "principiante"
    if nivel_final not in NIVEL_ORDEN:
        nivel_final = "principiante"

    # Quien se desplaza en silla trabaja por defecto desde la silla o sentado
    if clave_discapacidad in ("motriz", "multiple") and posicion is None:
        posicion = "sentado"

    azar = random.Random(semilla)

    compatibles = [e for e in ejercicios_disponibles if _apto_para(e, clave_discapacidad)]
    aptos = [
        e for e in compatibles
        if _apto_nivel(e, nivel_final) and _apto_posicion(e, posicion)
    ]
    # Si la combinación deja el catálogo sin margen se relaja el nivel, nunca la
    # posición ni la discapacidad: esas son restricciones de seguridad.
    if len(aptos) < 6:
        aptos = [e for e in compatibles if _apto_posicion(e, posicion)]
    if len(aptos) < 6:
        aptos = compatibles

    n_cal, n_prin, n_vuelta = _reparto(duracion_minutos)
    por_fase = {
        "calentamiento": [e for e in aptos if e["fase"] == "calentamiento"],
        "principal": [e for e in aptos if e["fase"] == "principal"],
        "vuelta_a_la_calma": [e for e in aptos if e["fase"] == "vuelta_a_la_calma"],
    }

    seleccion = {
        fase: _seleccionar(
            por_fase[fase], cantidad, objetivo, posicion, nivel_final, clave_discapacidad, azar
        )
        for fase, cantidad in (
            ("calentamiento", n_cal),
            ("principal", n_prin),
            ("vuelta_a_la_calma", n_vuelta),
        )
    }

    bloques = []
    ejercicios_planos = []
    etiquetas = {
        "calentamiento": "Calentamiento",
        "principal": "Bloque principal",
        "vuelta_a_la_calma": "Vuelta a la calma",
    }
    for fase, lista in seleccion.items():
        formateados = [_formatear(e, clave_discapacidad) for e in lista]
        ejercicios_planos.extend(formateados)
        if formateados:
            bloques.append({
                "bloque": etiquetas[fase],
                "fase": fase,
                "ejercicios": formateados,
            })

    duracion_estimada = sum(
        e["tiempo_estimado"] * max(1, e["series"]) + e["descanso"] * max(0, e["series"] - 1)
        for e in ejercicios_planos
    )

    material = sorted({m for e in ejercicios_planos for m in e["material"]})
    pauta = PAUTAS_DISCAPACIDAD.get(clave_discapacidad, PAUTAS_DISCAPACIDAD["general"])
    avisos = sorted({e["seguridad"] for e in ejercicios_planos if e["seguridad"]})

    return {
        "nombre": f"Rutina de {OBJETIVOS.get(objetivo, OBJETIVOS['general']).lower()} · {descripcion(clave_discapacidad)}",
        "objetivo": OBJETIVOS.get(objetivo, OBJETIVOS["general"]),
        "objetivo_clave": objetivo,
        "nivel": nivel_final,
        "discapacidad": clave_discapacidad,
        "discapacidad_descripcion": descripcion(clave_discapacidad),
        "pauta_discapacidad": pauta["pauta"],
        "posicion_predominante": posicion or "mixta",
        "duracion_estimada_minutos": round(duracion_estimada / 60),
        "total_ejercicios": len(ejercicios_planos),
        "bloques": bloques,
        "ejercicios": ejercicios_planos,
        "material_necesario": material,
        "recomendaciones": _recomendaciones(
            clave_discapacidad, objetivo, nivel_final, posicion, material, ejercicios_planos
        ),
        "avisos_seguridad": avisos,
        "fuente": "motor_local",
    }
