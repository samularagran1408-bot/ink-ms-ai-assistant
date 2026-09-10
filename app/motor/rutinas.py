"""Motor local de generación de rutinas.

Selecciona ejercicios del catálogo filtrando por discapacidad, objetivo, nivel y
posición, y compone una sesión con calentamiento, bloque principal y vuelta a la
calma. La selección se aleatoriza con una semilla, así que dos peticiones no
devuelven la misma rutina.
"""

import random
import re
from typing import Any, Iterable, Optional

from app.data.ejercicios import (
    CATALOGO_EJERCICIOS,
    OBJETIVOS,
    PAUTAS_DISCAPACIDAD,
    PERFILES_DISCAPACIDAD,
)
from app.nlp.discapacidad import canonizar, descripcion
from app.nlp.texto import normalizar, raiz, tokenizar

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
    "fuerza": ("fuerza", "fortalecer", "musculo", "muscular", "tonificar", "hipertrofia"),
    "resistencia": (
        "resistencia", "cardio", "aerobico", "aguante", "fondo",
        "caminar", "caminata", "paseo", "pasear", "marcha", "andar", "trotar",
        "correr", "footing", "bicicleta", "pedalear", "remo",
    ),
    "movilidad": ("movilidad", "amplitud", "articular", "rango articular"),
    "flexibilidad": ("flexibilidad", "estirar", "estiramiento", "elasticidad"),
    "equilibrio": (
        "equilibrio", "estabilidad", "postural", "balance", "propiocepcion",
    ),
    "rehabilitacion": (
        "rehabilitacion", "recuperar", "recuperacion", "lesion", "dolor", "suave", "terapia",
    ),
    "peso": ("peso", "adelgazar", "grasa", "calorias", "quemar"),
    "reflejos": (
        "reflejos", "reflejo", "tiempo de reaccion", "reaccion", "reactivo",
        "estimular reflejos",
    ),
    "velocidad": (
        "velocidad", "rapidez", "rapido", "sprint", "explosivo", "acelerar",
    ),
    "agilidad": (
        "agilidad", "agil", "cambio de direccion", "cambios de direccion", "esquivar",
    ),
    "potencia": ("potencia", "explosividad", "potente"),
    "coordinacion": (
        "coordinacion", "coordinar", "ojo mano", "oculo manual", "oculomanual",
    ),
    "core": ("core", "tronco", "abdomen", "abdominales", "zona media"),
}

_RUIDO_PEDIDO = {
    "rutina", "plan", "sesion", "entrenamiento", "entrenar", "generar", "genera",
    "quiero", "dame", "necesito", "crear", "hazme", "hacer", "objetivo", "tipo",
    "minutos", "nivel", "dia", "semana", "hoy", "adaptada", "adaptado", "inclusiva",
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
    """Devuelve la primera clave cuyo alias aparece en el texto normalizado."""
    limpio = normalizar(texto or "")
    if not limpio:
        return None
    for clave, palabras in alias.items():
        if any(p in limpio for p in palabras):
            return clave
    return None


def _score_alias_en_texto(limpio: str, tokens: set[str], raices_txt: set[str], palabra: str) -> float:
    """Puntúa un alias: coincidencia exacta de token > palabra completa > raíz."""
    alias = normalizar(palabra)
    if not alias:
        return 0.0
    partes = alias.split()
    if len(partes) > 1:
        return 3.2 + 0.2 * len(partes) if alias in limpio else 0.0
    if alias in tokens:
        return 2.8
    if re.search(rf"\b{re.escape(alias)}\b", limpio):
        return 2.4
    if raiz(alias) in raices_txt and len(alias) >= 5:
        return 2.0
    return 0.0


def _objetivos_ranqueados(texto: str, umbral: float = 2.0) -> list[str]:
    """Claves de objetivo ordenadas por qué tan claro las pidió el usuario."""
    limpio = normalizar(texto or "")
    if not limpio:
        return []
    tokens = set(tokenizar(limpio))
    raices_txt = {raiz(t) for t in tokens}
    puntuaciones: dict[str, float] = {}
    for clave, palabras in _ALIAS_OBJETIVO.items():
        score = 0.0
        for palabra in palabras:
            score = max(score, _score_alias_en_texto(limpio, tokens, raices_txt, palabra))
        if clave in tokens:
            score = max(score, 3.0)
        if score >= umbral:
            puntuaciones[clave] = score
    return [k for k, _ in sorted(puntuaciones.items(), key=lambda x: (-x[1], x[0]))]


def interpretar_objetivo(texto: str) -> str:
    """Clave de objetivo (fuerza, reflejos, velocidad…) o «general» si no hay coincidencia."""
    ranked = _objetivos_ranqueados(texto)
    return ranked[0] if ranked else "general"


def interpretar_objetivos(objetivo_texto: str, tipo_texto: str = "") -> tuple[str, Optional[str]]:
    """Objetivo principal + secundario a partir del texto libre del usuario.

    El campo `objetivo` manda; `tipo` aporta un segundo énfasis (p. ej. caminar +
    reflejos → resistencia + reflejos). Si el usuario nombra dos metas en el
    mismo campo, la segunda pasa a secundario.
    """
    de_obj = _objetivos_ranqueados(objetivo_texto)
    de_tipo = _objetivos_ranqueados(tipo_texto)
    if de_obj:
        prim = de_obj[0]
        resto = [c for c in de_obj[1:] + de_tipo if c != prim]
        return prim, (resto[0] if resto else None)
    if de_tipo:
        prim = de_tipo[0]
        resto = [c for c in de_tipo[1:] if c != prim]
        return prim, (resto[0] if resto else None)
    mezclado = _objetivos_ranqueados(f"{objetivo_texto} {tipo_texto}")
    if not mezclado:
        return "general", None
    prim = mezclado[0]
    sec = mezclado[1] if len(mezclado) > 1 else None
    return prim, sec


def _texto_objetivo_visible(objetivo: str, objetivo_texto: str, tipo_texto: str) -> str:
    """Etiqueta humana: canónica si hay clave, o el pedido libre si no encajó en el catálogo."""
    if objetivo != "general":
        return OBJETIVOS.get(objetivo, OBJETIVOS["general"])
    crudo = (objetivo_texto or tipo_texto or "").strip()
    limpio = re.sub(
        r"(?i)^(quiero|necesito|dame|genera|hazme|crea)?\s*"
        r"(una\s+|un\s+)?(rutina|plan|sesion|entrenamiento)?\s*"
        r"(de|para|con)?\s*",
        "",
        crudo,
    ).strip(" .:-")
    return limpio[:80] if limpio else OBJETIVOS["general"]


def interpretar_posicion(texto: str) -> Optional[str]:
    """Posición de trabajo (silla, sentado, de_pie…) o None si no se menciona."""
    return _detectar(texto, _ALIAS_POSICION)


def interpretar_nivel(texto: str) -> Optional[str]:
    """Nivel (principiante/intermedio/avanzado) detectado en el texto, o None."""
    return _detectar(texto, _ALIAS_NIVEL)


def perfil_de(discapacidad: str) -> dict[str, Any]:
    """Criterios de prescripción del perfil; si la clave no existe, usa «general»."""
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
    """False si la posición pedida es incompatible con la del ejercicio (p. ej. silla vs de pie)."""
    if not posicion:
        return True
    return ejercicio.get("posicion") not in _INCOMPATIBLES_POSICION.get(posicion, ())


def _apto_nivel(ejercicio: dict, nivel: str) -> bool:
    """True si el nivel del ejercicio no supera el nivel máximo pedido."""
    return NIVEL_ORDEN.get(ejercicio["nivel"], 2) <= NIVEL_ORDEN.get(nivel, 2)


def adaptacion_de(ejercicio: dict, discapacidad: str) -> str:
    """Texto de adaptación: la específica del ejercicio o la pauta general."""
    especifica = (ejercicio.get("adaptaciones") or {}).get(discapacidad)
    pauta = PAUTAS_DISCAPACIDAD.get(discapacidad, PAUTAS_DISCAPACIDAD["general"])["pauta"]
    if especifica:
        return f"{especifica} {pauta}"
    return pauta


def _afin_pedido(ejercicio: dict, pedido: str) -> float:
    """Suma puntos si el ejercicio habla el mismo idioma que el pedido libre."""
    limpio = normalizar(pedido or "")
    tokens = [t for t in tokenizar(limpio) if t not in _RUIDO_PEDIDO and len(t) >= 4]
    if not tokens:
        return 0.0
    raices_p = {raiz(t) for t in tokens}
    blob = normalizar(
        " ".join(
            [
                str(ejercicio.get("nombre") or ""),
                " ".join(str(x) for x in (ejercicio.get("objetivos") or [])),
                str(ejercicio.get("categoria") or ""),
                " ".join(str(x) for x in (ejercicio.get("musculos") or [])),
                str(ejercicio.get("instrucciones") or ""),
            ]
        )
    )
    raices_ej = {raiz(t) for t in tokenizar(blob)}
    score = 0.0
    for r in raices_p:
        if r in raices_ej or r in blob:
            score += 1.4
    objetivos_ej = set(ejercicio.get("objetivos") or [])
    objetivos_ej.add(ejercicio.get("categoria") or "")
    for clave, palabras in _ALIAS_OBJETIVO.items():
        if clave not in objetivos_ej:
            continue
        if any(_score_alias_en_texto(limpio, set(tokens), raices_p, p) >= 2.0 for p in palabras):
            score += 2.2
            break
    return min(score, 8.0)


def _puntuar(
    ejercicio: dict,
    objetivo: str,
    posicion: Optional[str],
    nivel: str,
    discapacidad: str,
    objetivo_secundario: Optional[str] = None,
    pedido: str = "",
) -> float:
    """Puntúa cuánto encaja el ejercicio con objetivo, posición, nivel y discapacidad."""
    puntaje = 0.0
    objetivos_ej = ejercicio.get("objetivos") or []
    # El objetivo pedido debe pesar más que el sesgo del perfil de discapacidad
    # (p. ej. motriz prioriza "fuerza", pero si pides reflejos no debe ganar).
    if objetivo in objetivos_ej:
        puntaje += 6.5
    if objetivo_secundario and objetivo_secundario in objetivos_ej:
        puntaje += 3.5
    if ejercicio.get("categoria") == objetivo:
        puntaje += 2.0
    if objetivo_secundario and ejercicio.get("categoria") == objetivo_secundario:
        puntaje += 1.5
    if objetivo == "general" and not objetivo_secundario:
        puntaje += 1.0
    if pedido:
        puntaje += _afin_pedido(ejercicio, pedido)
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
    # Solo aplica el sesgo del perfil cuando no hay un objetivo concreto ni un
    # pedido con contenido (si pidió reflejos, no empujamos a fuerza).
    pedido_con_contenido = bool(
        [t for t in tokenizar(normalizar(pedido or "")) if t not in _RUIDO_PEDIDO]
    )
    if (
        objetivo == "general"
        and not objetivo_secundario
        and not pedido_con_contenido
        and categorias
    ):
        if ejercicio.get("categoria") in categorias:
            puntaje += 2.5 - 0.5 * categorias.index(ejercicio["categoria"])

    puntaje -= perfil["posiciones_penalizadas"].get(ejercicio.get("posicion"), 0.0)
    return puntaje


def _sample_ponderado(
    pool: list[dict],
    cantidad: int,
    objetivo: str,
    posicion: Optional[str],
    nivel: str,
    discapacidad: str,
    azar: random.Random,
    objetivo_secundario: Optional[str] = None,
    excluir_ids: Optional[set[str]] = None,
    pedido: str = "",
) -> list[dict]:
    """Elige con peso por puntaje (no siempre el top fijo) para variar rutinas."""
    if not pool or cantidad <= 0:
        return []

    excluir_ids = excluir_ids or set()
    excluir_nombres = {
        (e.get("nombre") or "").strip().lower()
        for e in pool
        if e.get("id") in excluir_ids
    }
    excluir_nombres.update(
        str(x).strip().lower() for x in excluir_ids if isinstance(x, str) and " " in str(x)
    )

    def _fuera(ejercicio: dict) -> bool:
        eid = ejercicio.get("id")
        nombre = (ejercicio.get("nombre") or "").strip().lower()
        return (eid and eid in excluir_ids) or (
            nombre and (nombre in excluir_nombres or nombre in excluir_ids)
        )

    # Ventana de candidatos: top-K tras jitter, luego sample ponderado
    puntuados: list[tuple[float, dict]] = []
    for e in pool:
        if _fuera(e):
            continue
        base = _puntuar(
            e, objetivo, posicion, nivel, discapacidad, objetivo_secundario, pedido
        )
        # Ruido controlado: suficiente para variar, no para elegir basura
        score = max(0.05, base + azar.uniform(-1.2, 1.2))
        puntuados.append((score, e))

    puntuados.sort(key=lambda x: x[0], reverse=True)
    ventana = puntuados[: max(cantidad * 4, min(14, len(puntuados)))]

    elegidos: list[dict] = []
    categorias_usadas: set[str] = set()
    ids_usados: set[str] = set()
    restantes = list(ventana)

    def _tomar(preferir_categoria_nueva: bool) -> Optional[dict]:
        """Saca un ejercicio de la ventana; prioriza categorías aún no usadas si se pide."""
        nonlocal restantes
        candidatos = [
            (s, e) for s, e in restantes
            if e.get("id") not in ids_usados
            and (not preferir_categoria_nueva or e.get("categoria") not in categorias_usadas)
        ]
        if not candidatos and preferir_categoria_nueva:
            candidatos = [(s, e) for s, e in restantes if e.get("id") not in ids_usados]
        if not candidatos:
            return None
        pesos = [max(0.05, s) ** 1.6 for s, _ in candidatos]
        elegido = azar.choices([e for _, e in candidatos], weights=pesos, k=1)[0]
        restantes = [(s, e) for s, e in restantes if e.get("id") != elegido.get("id")]
        return elegido

    # Primera pasada: diversidad de categorías
    while len(elegidos) < cantidad:
        pick = _tomar(preferir_categoria_nueva=True)
        if not pick:
            break
        elegidos.append(pick)
        categorias_usadas.add(pick.get("categoria") or "")
        if pick.get("id"):
            ids_usados.add(pick["id"])

    # Segunda: rellenar desde el resto del pool si hace falta (aún sin repetir)
    if len(elegidos) < cantidad:
        resto = [e for e in pool if e.get("id") not in ids_usados and not _fuera(e)]
        azar.shuffle(resto)
        for e in resto:
            if len(elegidos) >= cantidad:
                break
            nombre = (e.get("nombre") or "").strip().lower()
            if nombre and any(
                (x.get("nombre") or "").strip().lower() == nombre for x in elegidos
            ):
                continue
            elegidos.append(e)
            if e.get("id"):
                ids_usados.add(e["id"])

    return elegidos[:cantidad]


def _seleccionar(
    candidatos: Iterable[dict],
    cantidad: int,
    objetivo: str,
    posicion: Optional[str],
    nivel: str,
    discapacidad: str,
    azar: random.Random,
    objetivo_secundario: Optional[str] = None,
    excluir_ids: Optional[set[str]] = None,
    pedido: str = "",
) -> list[dict]:
    """Elige `cantidad` ejercicios con variedad entre peticiones."""
    pool = list(candidatos)
    if not pool:
        return []
    azar.shuffle(pool)
    return _sample_ponderado(
        pool,
        cantidad,
        objetivo,
        posicion,
        nivel,
        discapacidad,
        azar,
        objetivo_secundario,
        excluir_ids,
        pedido,
    )


def _formatear(ejercicio: dict, discapacidad: str) -> dict[str, Any]:
    """Ajusta volumen y descanso al perfil antes de exponer el ejercicio.

    El mismo ejercicio se prescribe distinto: menos series y más descanso en los
    perfiles que se fatigan antes o necesitan más tiempo entre instrucciones.
    """
    perfil = perfil_de(discapacidad)
    series_base = int(ejercicio.get("series") or 2)
    descanso_base = float(ejercicio.get("descanso") or 45)
    series = max(1, series_base + int(perfil.get("series_delta") or 0))
    descanso = round(descanso_base * float(perfil.get("descanso_factor") or 1.0))
    material = ejercicio.get("material") or []
    if isinstance(material, str):
        material = [material]
    return {
        "id": ejercicio.get("id"),
        "nombre": ejercicio.get("nombre") or "Ejercicio",
        "categoria": ejercicio.get("categoria") or "general",
        "fase": ejercicio.get("fase") or "principal",
        "posicion": ejercicio.get("posicion") or "mixta",
        "nivel": ejercicio.get("nivel") or "principiante",
        "repeticiones": ejercicio.get("repeticiones") or "8-10",
        "series": series,
        "tiempo_estimado": int(ejercicio.get("tiempo_estimado") or 40),
        "descanso": descanso,
        "esfuerzo": ejercicio.get("esfuerzo") or 2,
        "musculos": ejercicio.get("musculos") or [],
        "material": list(material),
        "instrucciones": ejercicio.get("instrucciones") or "Ejecuta con control.",
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
        "reflejos": "La calidad está en reaccionar pronto, no en hacer el gesto más grande.",
        "velocidad": "Cada intervalo rápido dura poco: llega fresco al siguiente y suelta al frenar.",
        "agilidad": "Cambia de dirección con control; primero preciso, después más vivo.",
        "potencia": "El impulso es corto y nítido; la vuelta al inicio, lenta y controlada.",
        "coordinacion": "Si se desordena el gesto, baja el ritmo y vuelve a encadenar los dos lados.",
        "core": "El tronco no se mueve de más: resiste antes de añadir velocidad.",
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
    excluir_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Compone una rutina con calentamiento, bloque principal y vuelta a la calma.

    Filtra el catálogo por discapacidad, objetivo, nivel y posición. `semilla`
    fija la selección; sin ella varía entre peticiones. `excluir_ids` evita
    repetir ejercicios de una rutina reciente del mismo usuario.
    """
    ejercicios_disponibles = catalogo or CATALOGO_EJERCICIOS
    clave_discapacidad = canonizar(discapacidad)
    objetivo, objetivo_secundario = interpretar_objetivos(objetivo_texto, tipo_texto)
    posicion = interpretar_posicion(f"{tipo_texto} {discapacidad}")
    nivel_final = nivel or interpretar_nivel(f"{tipo_texto} {objetivo_texto}") or "principiante"
    if nivel_final not in NIVEL_ORDEN:
        nivel_final = "principiante"

    # Quien se desplaza en silla trabaja por defecto desde la silla o sentado
    if clave_discapacidad in ("motriz", "multiple") and posicion is None:
        posicion = "sentado"

    # Semilla fija → misma rutina siempre. Sin semilla → variación entre peticiones.
    azar = random.Random(semilla)

    # Descarta documentos incompletos (p. ej. catálogo Mongo antiguo).
    ejercicios_disponibles = [
        e for e in ejercicios_disponibles
        if e.get("id") and e.get("nombre") and e.get("fase")
    ]
    if not ejercicios_disponibles:
        ejercicios_disponibles = CATALOGO_EJERCICIOS

    compatibles = [e for e in ejercicios_disponibles if _apto_para(e, clave_discapacidad)]
    aptos = [
        e for e in compatibles
        if _apto_nivel(e, nivel_final) and _apto_posicion(e, posicion)
    ]
    # Solo se relaja el nivel. Posición y discapacidad son seguridad.
    if len(aptos) < 6:
        aptos = [e for e in compatibles if _apto_posicion(e, posicion)]
    if len(aptos) < 3:
        # Último recurso: catálogo en código, aún respetando posición/discapacidad.
        respaldo = [e for e in CATALOGO_EJERCICIOS if _apto_para(e, clave_discapacidad)]
        aptos = [e for e in respaldo if _apto_posicion(e, posicion)] or respaldo

    n_cal, n_prin, n_vuelta = _reparto(duracion_minutos)
    por_fase = {
        "calentamiento": [e for e in aptos if e.get("fase") == "calentamiento"],
        "principal": [e for e in aptos if e.get("fase") == "principal"],
        "vuelta_a_la_calma": [e for e in aptos if e.get("fase") == "vuelta_a_la_calma"],
    }
    # Si falta una fase, rellena desde el pool apto completo.
    for fase, lista in list(por_fase.items()):
        if not lista:
            por_fase[fase] = list(aptos)

    pedido = f"{objetivo_texto} {tipo_texto}".strip()
    excluidos = set(excluir_ids or ())
    seleccion: dict[str, list[dict]] = {}
    for fase, cantidad in (
        ("calentamiento", n_cal),
        ("principal", n_prin),
        ("vuelta_a_la_calma", n_vuelta),
    ):
        elegidos = _seleccionar(
            por_fase[fase],
            cantidad,
            objetivo,
            posicion,
            nivel_final,
            clave_discapacidad,
            azar,
            objetivo_secundario,
            excluidos,
            pedido,
        )
        seleccion[fase] = elegidos
        for e in elegidos:
            if e.get("id"):
                excluidos.add(e["id"])
            nombre = (e.get("nombre") or "").strip().lower()
            if nombre:
                excluidos.add(nombre)

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

    etiqueta_obj = _texto_objetivo_visible(objetivo, objetivo_texto, tipo_texto)
    if objetivo != "general" and objetivo_secundario:
        etiqueta_obj = (
            f"{etiqueta_obj} + {OBJETIVOS.get(objetivo_secundario, objetivo_secundario)}"
        )

    return {
        "nombre": f"Rutina de {etiqueta_obj.lower()} · {descripcion(clave_discapacidad)}",
        "objetivo": etiqueta_obj,
        "objetivo_clave": objetivo,
        "objetivo_secundario": objetivo_secundario,
        "objetivo_pedido": (objetivo_texto or tipo_texto or "").strip() or None,
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
        "interpretacion": {
            "objetivo_texto": objetivo_texto,
            "tipo_texto": tipo_texto,
            "objetivo_detectado": objetivo,
            "objetivo_secundario_detectado": objetivo_secundario,
            "posicion_detectada": posicion,
            "semilla": semilla,
            "nota": (
                "Misma semilla = misma rutina. Omite 'semilla' para variar."
                if semilla is not None
                else "Sin semilla: la seleccion varia en cada peticion."
            ),
        },
    }
