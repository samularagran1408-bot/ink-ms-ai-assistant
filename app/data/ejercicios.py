"""Catálogo de ejercicios adaptados para el motor de rutinas.

Es la fuente de verdad del servicio: se siembra en MongoDB al arrancar y el
motor de rutinas selecciona de aquí filtrando por discapacidad, objetivo,
posición y nivel. Sustituye a los tres ejercicios fijos que devolvía el
fallback anterior.

Fases: calentamiento | principal | vuelta_a_la_calma
Categorías: movilidad | fuerza | resistencia | equilibrio | core | flexibilidad | agilidad
Discapacidades: visual | auditiva | motriz | cognitiva | intelectual | multiple
  (una lista vacía significa "apta para cualquier discapacidad")
"""

from typing import Any

# Pautas transversales por tipo de discapacidad. El motor las combina con la
# adaptación específica del ejercicio para no repetir el mismo texto 40 veces.
PAUTAS_DISCAPACIDAD: dict[str, dict[str, str]] = {
    "visual": {
        "descripcion": "Discapacidad visual",
        "pauta": (
            "Describe cada movimiento en voz alta y por pasos. Trabaja con un punto "
            "de apoyo fijo (pared, respaldo o barra) y despeja la zona de obstáculos."
        ),
        "referencia": "Usa referencias táctiles y auditivas en lugar de visuales.",
    },
    "auditiva": {
        "descripcion": "Discapacidad auditiva",
        "pauta": (
            "Muestra el movimiento antes de ejecutarlo y usa señales visuales o "
            "vibración para marcar inicio, cambio y final de cada serie."
        ),
        "referencia": "Acuerda señas simples para 'parar', 'seguir' y 'descansar'.",
    },
    "motriz": {
        "descripcion": "Discapacidad física o motriz",
        "pauta": (
            "Ejecuta en el rango de movimiento libre de dolor. Estabiliza el tronco "
            "y usa la silla, apoyos o asistencia parcial cuando haga falta."
        ),
        "referencia": "Prioriza control y postura sobre amplitud o carga.",
    },
    "cognitiva": {
        "descripcion": "Discapacidad cognitiva",
        "pauta": (
            "Divide el ejercicio en 2 o 3 pasos cortos, repite la misma instrucción "
            "y refuerza cada repetición conseguida."
        ),
        "referencia": "Mantén un orden estable de ejercicios entre sesiones.",
    },
    "intelectual": {
        "descripcion": "Discapacidad intelectual",
        "pauta": (
            "Usa instrucciones concretas de una sola acción, demuestra primero y "
            "acompaña con conteo en voz alta."
        ),
        "referencia": "Refuerza logros y evita cambios bruscos de rutina.",
    },
    "multiple": {
        "descripcion": "Discapacidad múltiple",
        "pauta": (
            "Combina apoyo verbal, visual y táctil. Reduce series y amplía descansos "
            "según la respuesta de la sesión."
        ),
        "referencia": "Ajusta el ejercicio a la capacidad del día, no al plan escrito.",
    },
    "general": {
        "descripcion": "Sin discapacidad registrada",
        "pauta": (
            "Progresa de menor a mayor exigencia y mantén una técnica controlada en "
            "todo el recorrido."
        ),
        "referencia": "Detén el ejercicio ante dolor, mareo o falta de aire.",
    },
}

# Criterios de prescripción por discapacidad. El motor los usa para descartar
# ejercicios inviables, priorizar los que aportan más a ese perfil y ajustar el
# volumen. Sin esto, los perfiles sin restricción explícita (visual, auditiva,
# cognitiva, intelectual) recibirían todos la misma rutina.
PERFILES_DISCAPACIDAD: dict[str, dict[str, Any]] = {
    "visual": {
        # De pie es viable, pero solo con un punto de apoyo fijo, así que pesa menos.
        "posiciones_excluidas": (),
        "posiciones_penalizadas": {"de_pie": 1.5},
        # Sin referencia visual, el control postural y propioceptivo es la prioridad.
        "categorias_prioritarias": ("equilibrio", "movilidad", "fuerza"),
        "esfuerzo_maximo": 4,
        "nivel_maximo": "avanzado",
        "series_delta": 0,
        "descanso_factor": 1.0,
        "claves": (
            "Recorre y despeja la zona antes de empezar; deja el material siempre en el mismo sitio.",
            "Cuenta las repeticiones en voz alta para no perder la serie.",
        ),
    },
    "auditiva": {
        # No hay limitación motora: el catálogo entra completo.
        "posiciones_excluidas": (),
        "posiciones_penalizadas": {},
        # Se prioriza el trabajo continuo, que no depende de correcciones habladas.
        "categorias_prioritarias": ("resistencia", "fuerza", "core"),
        "esfuerzo_maximo": 4,
        "nivel_maximo": "avanzado",
        "series_delta": 0,
        "descanso_factor": 1.0,
        "claves": (
            "Coloca un reloj o temporizador a la vista para controlar series y descansos.",
            "Revisa la técnica frente a un espejo en lugar de esperar corrección hablada.",
        ),
    },
    "motriz": {
        # Bipedestación descartada; la colchoneta exige una transferencia al suelo.
        "posiciones_excluidas": ("de_pie",),
        "posiciones_penalizadas": {"colchoneta": 2.0},
        "categorias_prioritarias": ("fuerza", "resistencia", "core"),
        "esfuerzo_maximo": 4,
        "nivel_maximo": "avanzado",
        "series_delta": 0,
        # El hombro carga con la propulsión diaria: se alargan los descansos.
        "descanso_factor": 1.2,
        "claves": (
            "Frena la silla y comprueba la estabilidad del asiento antes de cada serie.",
            "Reparte la carga del hombro: si notas molestia, cambia a trabajo de tronco.",
        ),
    },
    "cognitiva": {
        "posiciones_excluidas": (),
        "posiciones_penalizadas": {"colchoneta": 1.0},
        # Movimientos cíclicos y predecibles, fáciles de encadenar sin recordar pasos.
        "categorias_prioritarias": ("movilidad", "resistencia", "equilibrio"),
        "esfuerzo_maximo": 3,
        "nivel_maximo": "intermedio",
        "series_delta": -1,
        "descanso_factor": 1.15,
        "claves": (
            "Mantén el mismo orden de ejercicios en todas las sesiones.",
            "Ten a mano una lista con los ejercicios del día y ve tachándolos.",
        ),
    },
    "intelectual": {
        "posiciones_excluidas": (),
        "posiciones_penalizadas": {"colchoneta": 1.5},
        "categorias_prioritarias": ("movilidad", "resistencia", "flexibilidad"),
        "esfuerzo_maximo": 3,
        "nivel_maximo": "principiante",
        "series_delta": -1,
        "descanso_factor": 1.2,
        "claves": (
            "Haz primero una repetición de muestra y luego acompaña contando en voz alta.",
            "Celebra cada bloque terminado antes de pasar al siguiente.",
        ),
    },
    "multiple": {
        # Perfil más conservador: se combinan las restricciones de los anteriores.
        "posiciones_excluidas": ("de_pie", "colchoneta"),
        "posiciones_penalizadas": {},
        "categorias_prioritarias": ("movilidad", "flexibilidad", "resistencia"),
        "esfuerzo_maximo": 3,
        "nivel_maximo": "principiante",
        "series_delta": -1,
        "descanso_factor": 1.3,
        "claves": (
            "Trabaja siempre acompañado y con la silla o el asiento frenado.",
            "Si el día viene flojo, quédate en el calentamiento y la vuelta a la calma.",
        ),
    },
    "general": {
        "posiciones_excluidas": (),
        "posiciones_penalizadas": {},
        "categorias_prioritarias": (),
        "esfuerzo_maximo": 5,
        "nivel_maximo": "avanzado",
        "series_delta": 0,
        "descanso_factor": 1.0,
        "claves": (
            "Sube la carga solo cuando completes todas las series con técnica limpia.",
        ),
    },
}

OBJETIVOS = {
    "fuerza": "Ganar fuerza y masa muscular",
    "movilidad": "Mejorar movilidad y amplitud articular",
    "resistencia": "Aumentar resistencia cardiovascular",
    "equilibrio": "Mejorar equilibrio y control postural",
    "flexibilidad": "Ganar flexibilidad",
    "rehabilitacion": "Recuperación progresiva y control del dolor",
    "peso": "Control de peso y gasto calórico",
    "reflejos": "Estimular reflejos y tiempo de reacción",
    "velocidad": "Mejorar velocidad de movimiento",
    "agilidad": "Mejorar agilidad y cambios de dirección",
    "potencia": "Desarrollar potencia explosiva",
    "coordinacion": "Mejorar coordinación óculo-manual y segmentaria",
    "core": "Fortalecer el tronco y la estabilidad central",
    "general": "Acondicionamiento físico general",
}

NIVELES = ("principiante", "intermedio", "avanzado")


def _ej(
    id: str,
    nombre: str,
    categoria: str,
    fase: str,
    objetivos: list[str],
    posicion: str,
    nivel: str,
    musculos: list[str],
    repeticiones: int,
    series: int,
    tiempo_estimado: int,
    descanso: int,
    esfuerzo: int,
    instrucciones: str,
    material: list[str] | None = None,
    discapacidades: list[str] | None = None,
    adaptaciones: dict[str, str] | None = None,
    seguridad: str = "",
) -> dict[str, Any]:
    """Construye un ejercicio del catálogo con defaults de material, discapacidades y seguridad."""
    return {
        "id": id,
        "nombre": nombre,
        "categoria": categoria,
        "fase": fase,
        "objetivos": objetivos,
        "posicion": posicion,
        "nivel": nivel,
        "musculos": musculos,
        "repeticiones": repeticiones,
        "series": series,
        "tiempo_estimado": tiempo_estimado,
        "descanso": descanso,
        "esfuerzo": esfuerzo,
        "instrucciones": instrucciones,
        "material": material or [],
        "discapacidades": discapacidades or [],
        "adaptaciones": adaptaciones or {},
        "seguridad": seguridad,
    }


CATALOGO_EJERCICIOS: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- calentamiento
    _ej(
        "cal-01", "Movilidad de cuello y hombros", "movilidad", "calentamiento",
        ["movilidad", "general", "rehabilitacion"], "sentado", "principiante",
        ["cuello", "trapecio", "hombros"], 10, 2, 60, 30, 1,
        "Gira los hombros hacia atrás en círculos amplios y lleva la oreja hacia cada hombro sin forzar.",
        adaptaciones={"motriz": "Si el tronco no se estabiliza, apoya la espalda en el respaldo y sujeta el asiento."},
        seguridad="No hagas círculos completos con el cuello ni lleves la cabeza hacia atrás.",
    ),
    _ej(
        "cal-02", "Apertura y cierre de brazos", "movilidad", "calentamiento",
        ["movilidad", "general"], "sentado", "principiante",
        ["pectoral", "espalda alta", "hombros"], 12, 2, 60, 30, 2,
        "Abre los brazos en cruz llevando los omóplatos hacia atrás y ciérralos al frente sin cruzarlos.",
        adaptaciones={"visual": "Cuenta en voz alta cada apertura para mantener el ritmo."},
    ),
    _ej(
        "cal-03", "Marcha sentada", "resistencia", "calentamiento",
        ["resistencia", "peso", "general", "velocidad", "agilidad"], "sentado", "principiante",
        ["cuádriceps", "flexor de cadera"], 20, 2, 60, 40, 2,
        "Eleva alternadamente las rodillas simulando una marcha, acompañando con el movimiento de brazos.",
        adaptaciones={"motriz": "Si no hay movilidad de piernas, realiza solo el braceo a mayor velocidad."},
    ),
    _ej(
        "cal-04", "Círculos de tobillo y muñeca", "movilidad", "calentamiento",
        ["movilidad", "rehabilitacion"], "sentado", "principiante",
        ["tobillo", "muñeca"], 10, 2, 45, 20, 1,
        "Dibuja círculos lentos con cada tobillo y cada muñeca, en ambos sentidos.",
    ),
    _ej(
        "cal-05", "Activación de glúteos en puente", "fuerza", "calentamiento",
        ["fuerza", "rehabilitacion"], "colchoneta", "principiante",
        ["glúteo", "isquiotibiales"], 12, 2, 60, 40, 2,
        "Tumbado boca arriba con rodillas flexionadas, eleva la pelvis apretando los glúteos y baja con control.",
        adaptaciones={"motriz": "Reduce la altura de la elevación y usa una toalla bajo la zona lumbar."},
        seguridad="Evita arquear la zona lumbar; el movimiento nace de la pelvis.",
    ),
    _ej(
        "cal-06", "Rotación de tronco controlada", "movilidad", "calentamiento",
        ["movilidad", "general"], "sentado", "principiante",
        ["oblicuos", "columna dorsal"], 10, 2, 60, 30, 2,
        "Con las manos en el pecho, gira el tronco a un lado y al otro manteniendo la cadera fija.",
        adaptaciones={"cognitiva": "Marca dos puntos de referencia, uno a cada lado, y gira hacia cada uno."},
    ),
    _ej(
        "cal-07", "Elevaciones de talones y punteras", "equilibrio", "calentamiento",
        ["equilibrio", "movilidad", "reflejos"], "de_pie", "principiante",
        ["gemelos", "tibial"], 15, 2, 50, 30, 2,
        "Sujeto a un apoyo firme, sube sobre las punteras y luego apoya los talones elevando las punteras.",
        discapacidades=["visual", "auditiva", "cognitiva", "intelectual"],
        material=["silla o barra de apoyo"],
        seguridad="Realiza siempre con un punto de apoyo al alcance de la mano.",
    ),
    _ej(
        "cal-08", "Respiración diafragmática", "movilidad", "calentamiento",
        ["rehabilitacion", "general", "resistencia"], "sentado", "principiante",
        ["diafragma"], 8, 2, 60, 20, 1,
        "Inhala por la nariz llevando el aire al abdomen durante 4 segundos y exhala lento en 6 segundos.",
        adaptaciones={"cognitiva": "Cuenta con los dedos cada inhalación para seguir el ritmo."},
    ),
    _ej(
        "cal-09", "Toques rápidos palma-rodilla", "agilidad", "calentamiento",
        ["reflejos", "coordinacion", "agilidad"], "sentado", "principiante",
        ["hombros", "core", "sistema nervioso"], 20, 2, 50, 25, 2,
        "Toca con la palma la rodilla contraria lo más rápido que puedas, alternando lados, sin perder el control del tronco.",
        adaptaciones={
            "motriz": "Si no hay movilidad de piernas, toca muslo, reposabrazos o mesa a distintos puntos.",
            "visual": "Marca cada toque en voz alta: izquierda, derecha.",
        },
    ),
    _ej(
        "cal-10", "Reacción a una seña", "agilidad", "calentamiento",
        ["reflejos", "coordinacion"], "sentado", "principiante",
        ["hombros", "sistema nervioso"], 12, 2, 50, 25, 2,
        "Alguien da una seña (palma, luz o toque) y tú levantas el brazo o giras el tronco lo antes posible. Doce reacciones.",
        adaptaciones={
            "auditiva": "Usa seña visual o vibración, nunca solo la voz.",
            "visual": "Usa un toque en el hombro o un sonido como seña.",
        },
    ),

    # ------------------------------------------------------------- principal: fuerza
    _ej(
        "fue-01", "Press de hombros con banda", "fuerza", "principal",
        ["fuerza", "general"], "sentado", "intermedio",
        ["deltoides", "tríceps"], 12, 3, 70, 60, 3,
        "Sujeta la banda a la altura de los hombros y empuja hacia arriba hasta estirar los brazos; baja con control.",
        material=["banda elástica"],
        adaptaciones={"motriz": "Si un brazo tiene menos fuerza, trabaja de forma unilateral y compensa el número de series."},
        seguridad="No bloquees los codos de golpe al final del recorrido.",
    ),
    _ej(
        "fue-02", "Remo con banda elástica", "fuerza", "principal",
        ["fuerza", "rehabilitacion"], "sentado", "principiante",
        ["dorsal", "romboides", "bíceps"], 12, 3, 70, 60, 3,
        "Con la banda anclada al frente, tira de los codos hacia atrás juntando los omóplatos y vuelve despacio.",
        material=["banda elástica"],
        adaptaciones={"visual": "Ancla la banda a una altura fija y verifica la tensión con las manos antes de empezar."},
    ),
    _ej(
        "fue-03", "Flexión de codo (bíceps)", "fuerza", "principal",
        ["fuerza"], "sentado", "principiante",
        ["bíceps"], 12, 3, 60, 45, 2,
        "Con una mancuerna o botella en cada mano, flexiona los codos sin despegarlos del tronco y baja controlando.",
        material=["mancuernas o botellas de agua"],
    ),
    _ej(
        "fue-04", "Extensión de tríceps sobre la cabeza", "fuerza", "principal",
        ["fuerza"], "sentado", "intermedio",
        ["tríceps"], 10, 3, 60, 50, 3,
        "Sostén el peso con ambas manos sobre la cabeza y flexiona los codos llevándolo detrás; extiende sin mover los hombros.",
        material=["mancuerna o botella"],
        seguridad="Mantén las costillas abajo para no arquear la espalda.",
    ),
    _ej(
        "fue-05", "Sentadilla asistida a silla", "fuerza", "principal",
        ["fuerza", "equilibrio", "peso"], "de_pie", "intermedio",
        ["cuádriceps", "glúteo"], 10, 3, 70, 60, 3,
        "De pie frente a una silla, baja la cadera hacia atrás hasta tocar el asiento y sube apretando los glúteos.",
        discapacidades=["visual", "auditiva", "cognitiva", "intelectual"],
        material=["silla estable"],
        adaptaciones={"visual": "Toca el borde del asiento con la parte de atrás de las piernas antes de iniciar cada bajada."},
        seguridad="Las rodillas siguen la dirección de los pies; no las lleves hacia dentro.",
    ),
    _ej(
        "fue-06", "Empuje de pared", "fuerza", "principal",
        ["fuerza", "rehabilitacion"], "de_pie", "principiante",
        ["pectoral", "tríceps", "hombros"], 12, 3, 60, 45, 2,
        "Apoya las manos en la pared a la altura del pecho y flexiona los codos acercando el cuerpo; empuja para volver.",
        discapacidades=["visual", "auditiva", "cognitiva", "intelectual"],
        adaptaciones={"motriz": "Realiza el mismo empuje desde la silla contra una mesa firme."},
    ),
    _ej(
        "fue-07", "Elevaciones laterales", "fuerza", "principal",
        ["fuerza"], "sentado", "intermedio",
        ["deltoides lateral"], 12, 3, 60, 50, 3,
        "Eleva los brazos a los lados hasta la altura de los hombros con los codos ligeramente flexionados y baja despacio.",
        material=["mancuernas ligeras"],
        seguridad="Si aparece pinzamiento en el hombro, no pases de la altura del pecho.",
    ),
    _ej(
        "fue-08", "Puente de glúteo a una pierna", "fuerza", "principal",
        ["fuerza", "equilibrio"], "colchoneta", "avanzado",
        ["glúteo", "isquiotibiales", "core"], 8, 3, 70, 60, 4,
        "Desde el puente, extiende una pierna y mantén la pelvis nivelada mientras subes y bajas.",
        discapacidades=["visual", "auditiva", "cognitiva"],
        seguridad="Detén el ejercicio si la pelvis se inclina; vuelve a la versión con dos pies.",
    ),
    _ej(
        "fue-09", "Prensa de piernas con banda", "fuerza", "principal",
        ["fuerza", "rehabilitacion"], "silla", "intermedio",
        ["cuádriceps", "glúteo"], 12, 3, 70, 60, 3,
        "Pasa la banda por la planta del pie y extiende la rodilla contra la resistencia; regresa con control.",
        material=["banda elástica"],
        adaptaciones={"motriz": "Trabaja el rango disponible aunque sea corto; la tensión constante ya genera estímulo."},
    ),
    _ej(
        "fue-10", "Apertura de hombros con banda (rotación externa)", "fuerza", "principal",
        ["fuerza", "rehabilitacion", "movilidad"], "sentado", "principiante",
        ["rotadores del hombro"], 14, 3, 60, 45, 2,
        "Con los codos pegados al cuerpo a 90 grados, separa las manos abriendo contra la banda y vuelve lento.",
        material=["banda elástica"],
    ),
    _ej(
        "fue-11", "Propulsión de silla en recta", "fuerza", "principal",
        ["fuerza", "resistencia", "potencia", "velocidad"], "silla", "intermedio",
        ["dorsal", "tríceps", "hombros"], 15, 3, 90, 75, 4,
        "Realiza empujes largos y completos del aro de la silla en un tramo recto y despejado.",
        discapacidades=["motriz"],
        material=["silla de ruedas"],
        adaptaciones={"motriz": "Alterna tramos de empuje intenso con tramos suaves para controlar la fatiga del hombro."},
        seguridad="Cuida la técnica del hombro: empuje largo, retorno relajado.",
    ),
    _ej(
        "fue-12", "Peso muerto rumano con banda", "fuerza", "principal",
        ["fuerza", "movilidad"], "de_pie", "avanzado",
        ["isquiotibiales", "glúteo", "lumbar"], 10, 3, 70, 60, 4,
        "Con la banda bajo los pies, lleva la cadera hacia atrás manteniendo la espalda recta y sube apretando glúteos.",
        discapacidades=["visual", "auditiva", "cognitiva"],
        material=["banda elástica"],
        seguridad="La espalda permanece recta en todo el recorrido; si se redondea, reduce el rango.",
    ),

    # -------------------------------------------------------- principal: resistencia
    _ej(
        "res-01", "Braceo continuo", "resistencia", "principal",
        ["resistencia", "peso", "velocidad"], "sentado", "principiante",
        ["hombros", "brazos", "sistema cardiovascular"], 1, 3, 120, 60, 3,
        "Mueve los brazos de forma continua al frente y arriba durante 2 minutos manteniendo un ritmo sostenido.",
        adaptaciones={"auditiva": "Marca el ritmo con un metrónomo visual o con luces."},
    ),
    _ej(
        "res-02", "Intervalos de propulsión", "resistencia", "principal",
        ["resistencia", "peso", "velocidad", "potencia"], "silla", "intermedio",
        ["hombros", "dorsal", "sistema cardiovascular"], 6, 1, 300, 90, 4,
        "Alterna 30 segundos de propulsión rápida con 60 segundos suaves, repitiendo 6 veces.",
        discapacidades=["motriz"],
        material=["silla de ruedas", "espacio despejado"],
        seguridad="Interrumpe si aparece dolor en el hombro o mareo.",
    ),
    _ej(
        "res-03", "Caminata guiada", "resistencia", "principal",
        ["resistencia", "peso", "equilibrio"], "de_pie", "principiante",
        ["piernas", "sistema cardiovascular"], 1, 1, 600, 60, 3,
        "Camina 10 minutos a ritmo cómodo por un recorrido conocido y sin obstáculos.",
        discapacidades=["visual", "auditiva", "cognitiva", "intelectual"],
        adaptaciones={"visual": "Realiza el recorrido con guía videncia o siguiendo una cuerda guía las primeras sesiones."},
    ),
    _ej(
        "res-04", "Natación adaptada por tramos", "resistencia", "principal",
        ["resistencia", "movilidad", "rehabilitacion"], "piscina", "intermedio",
        ["cuerpo completo", "sistema cardiovascular"], 8, 1, 480, 60, 3,
        "Nada 8 tramos cortos con descanso en el borde entre cada uno, cuidando la respiración.",
        material=["piscina", "flotador o tabla"],
        adaptaciones={
            "visual": "Usa cuerdas guía en los carriles y aviso táctil al aproximarte al borde.",
            "motriz": "Apóyate en flotador y prioriza el trabajo del tren superior.",
        },
        seguridad="Nunca entrenes en agua sin supervisión.",
    ),
    _ej(
        "res-05", "Circuito de tres estaciones", "resistencia", "principal",
        ["resistencia", "fuerza", "peso", "agilidad"], "sentado", "intermedio",
        ["cuerpo completo"], 3, 3, 300, 90, 4,
        "Encadena 40 segundos de braceo, 40 de marcha sentada y 40 de empuje contra la mesa; descansa y repite.",
        adaptaciones={"cognitiva": "Coloca una tarjeta con el dibujo de cada estación y ve pasándolas en orden."},
    ),
    _ej(
        "res-06", "Bicicleta de brazos", "resistencia", "principal",
        ["resistencia", "peso", "rehabilitacion"], "sentado", "principiante",
        ["brazos", "sistema cardiovascular"], 1, 1, 480, 60, 3,
        "Pedalea con los brazos a resistencia baja durante 8 minutos manteniendo la respiración controlada.",
        material=["ergómetro de brazos"],
    ),
    _ej(
        "res-07", "Baile o movimiento libre guiado", "resistencia", "principal",
        ["resistencia", "peso", "movilidad", "coordinacion", "agilidad"], "de_pie", "principiante",
        ["cuerpo completo"], 1, 1, 300, 60, 3,
        "Cinco minutos de movimiento libre siguiendo un pulso constante, ampliando poco a poco el rango.",
        adaptaciones={
            "auditiva": "Sigue el pulso con vibración del altavoz o con señales visuales del monitor.",
            "motriz": "Realiza la secuencia sentado, moviendo brazos y tronco.",
        },
    ),

    # ---------------------------------------------------- principal: equilibrio/core
    _ej(
        "equ-01", "Sedestación activa sin apoyo", "equilibrio", "principal",
        ["equilibrio", "rehabilitacion", "core"], "sentado", "principiante",
        ["core", "espalda"], 6, 3, 60, 45, 2,
        "Siéntate sin apoyar la espalda, activa el abdomen y mantén la postura 20 segundos.",
        adaptaciones={"motriz": "Comienza con 5 segundos y un cinturón de seguridad; progresa según control."},
        seguridad="Trabaja siempre con alguien cerca al retirar los apoyos.",
    ),
    _ej(
        "equ-02", "Apoyo unipodal asistido", "equilibrio", "principal",
        ["equilibrio"], "de_pie", "intermedio",
        ["tobillo", "glúteo", "core"], 5, 3, 60, 45, 3,
        "Sujeto a un apoyo, mantén el peso en una pierna durante 15 segundos y cambia de lado.",
        discapacidades=["visual", "auditiva", "cognitiva", "intelectual"],
        material=["barra o silla de apoyo"],
        adaptaciones={"visual": "Mantén una mano en el apoyo de forma permanente y usa referencias sonoras del entrenador."},
    ),
    _ej(
        "equ-03", "Plancha frontal adaptada", "core", "principal",
        ["fuerza", "equilibrio", "core"], "colchoneta", "intermedio",
        ["core", "hombros"], 4, 3, 60, 60, 4,
        "Apoya antebrazos y rodillas manteniendo el tronco alineado; sostén 20 segundos por serie.",
        discapacidades=["visual", "auditiva", "cognitiva"],
        seguridad="Si la zona lumbar se hunde, reduce el tiempo de sostén.",
    ),
    _ej(
        "equ-04", "Antirrotación con banda", "core", "principal",
        ["fuerza", "equilibrio", "rehabilitacion", "core"], "sentado", "intermedio",
        ["oblicuos", "core"], 10, 3, 60, 50, 3,
        "Con la banda anclada al lado, extiende los brazos al frente y resiste la rotación del tronco.",
        material=["banda elástica"],
    ),
    _ej(
        "equ-05", "Elevación de rodillas alterna con control", "core", "principal",
        ["fuerza", "equilibrio", "reflejos", "coordinacion"], "sentado", "principiante",
        ["abdomen", "flexor de cadera"], 12, 3, 60, 45, 3,
        "Sin apoyar la espalda, eleva una rodilla y bájala con control antes de cambiar de lado.",
        adaptaciones={"motriz": "Si no hay control de piernas, sustituye por elevación alterna de brazos con el mismo control."},
    ),
    _ej(
        "equ-06", "Transferencia de peso lateral", "equilibrio", "principal",
        ["equilibrio", "rehabilitacion", "agilidad"], "sentado", "principiante",
        ["core", "cadera"], 10, 3, 60, 45, 2,
        "Sentado, desplaza el peso hacia un glúteo y luego al otro sin despegar los pies del suelo.",
    ),
    _ej(
        "equ-07", "Marcha en línea con guía", "equilibrio", "principal",
        ["equilibrio"], "de_pie", "avanzado",
        ["piernas", "core"], 10, 3, 70, 60, 4,
        "Camina 10 pasos siguiendo una línea recta marcada, con los brazos separados para estabilizar.",
        discapacidades=["auditiva", "cognitiva", "intelectual"],
        material=["cinta en el suelo"],
        seguridad="Realiza junto a una pared para poder apoyarse.",
    ),
    _ej(
        "ref-01", "Toques cruzados a máxima velocidad", "agilidad", "principal",
        ["reflejos", "coordinacion", "agilidad"], "sentado", "principiante",
        ["hombros", "core", "sistema nervioso"], 20, 4, 50, 35, 3,
        "Toca hombro contrario, rodilla contraria y costado en un ciclo rápido. Gana velocidad sin desarmar la postura.",
        adaptaciones={
            "motriz": "Fija tres puntos al alcance (hombro, reposabrazos, muslo) y recórrelos al máximo.",
            "cognitiva": "Empieza lento nombrando cada punto y luego acelera.",
        },
    ),
    _ej(
        "ref-02", "Captura de pelota o globo", "agilidad", "principal",
        ["reflejos", "coordinacion"], "sentado", "intermedio",
        ["manos", "hombros", "sistema nervioso"], 16, 3, 70, 45, 3,
        "Un compañero lanza un globo o pelota blanda a distintas alturas; tú la capturas y la devuelves de inmediato.",
        material=["globo o pelota blanda"],
        adaptaciones={
            "visual": "Usa un globo con cascabel o avisa el lanzamiento en voz alta.",
            "motriz": "Lanza contra una pared cercana y captura el rebote, o pide lanzamientos a las manos.",
            "auditiva": "Acuerda una seña visual justo antes de cada lanzamiento.",
        },
        seguridad="Pelota blanda o globo; nunca objetos duros cerca de la cara.",
    ),
    _ej(
        "ref-03", "Toque de objetivos en el espacio", "agilidad", "principal",
        ["reflejos", "agilidad", "velocidad"], "sentado", "intermedio",
        ["hombros", "tronco", "sistema nervioso"], 20, 3, 60, 40, 3,
        "Marca 4 puntos (arriba, abajo, izquierda, derecha). Alguien nombra o señala uno y tú lo tocas lo antes posible.",
        adaptaciones={
            "visual": "Nombra el punto en voz alta en lugar de señalarlo.",
            "auditiva": "Señala el punto con la mano o con un color, sin voz.",
        },
    ),
    _ej(
        "ref-04", "Freno y arranque en silla", "agilidad", "principal",
        ["reflejos", "agilidad", "velocidad"], "silla", "intermedio",
        ["hombros", "dorsal", "sistema nervioso"], 8, 3, 80, 50, 4,
        "A una seña, impulsa dos metros y frena en seco. Espera la siguiente seña. Ocho repeticiones.",
        discapacidades=["motriz"],
        material=["silla de ruedas", "espacio despejado"],
        seguridad="Zona libre de obstáculos; frena con técnica, no con el hombro bloqueado.",
    ),
    _ej(
        "vel-01", "Braceo explosivo por intervalos", "resistencia", "principal",
        ["velocidad", "potencia", "resistencia"], "sentado", "intermedio",
        ["hombros", "brazos", "sistema cardiovascular"], 8, 3, 80, 50, 4,
        "20 segundos de braceo a máxima velocidad y 20 de braceo suave. Repite el ciclo.",
        adaptaciones={"motriz": "Reduce el rango si el hombro carga; la velocidad manda sobre la amplitud."},
        seguridad="Si aparece pinzamiento, baja la velocidad y el rango.",
    ),
    _ej(
        "vel-02", "Elevación rápida de rodillas", "agilidad", "principal",
        ["velocidad", "agilidad", "resistencia"], "sentado", "principiante",
        ["flexor de cadera", "core"], 20, 3, 50, 40, 3,
        "Eleva las rodillas lo más rápido que puedas durante 20 repeticiones, manteniendo el tronco estable.",
        adaptaciones={
            "motriz": "Si no hay movilidad de piernas, alterna elevaciones explosivas de brazos o de un lado del tronco.",
        },
    ),
    _ej(
        "agi-01", "Cambios de peso laterales rápidos", "agilidad", "principal",
        ["agilidad", "equilibrio", "reflejos"], "sentado", "principiante",
        ["core", "cadera"], 16, 3, 50, 35, 3,
        "Pasa el peso de un glúteo al otro a un ritmo vivo, como si esquivaras un toque, sin despegarte del asiento.",
        adaptaciones={"motriz": "Frena la silla. Si el control es bajo, reduce el rango y aumenta el número de toques."},
    ),
    _ej(
        "agi-02", "Zigzag corto en silla", "agilidad", "principal",
        ["agilidad", "velocidad", "potencia"], "silla", "intermedio",
        ["hombros", "oblicuos"], 6, 3, 90, 60, 4,
        "Recorre un pasillo haciendo tres cambios de dirección suaves a cada lado y vuelve.",
        discapacidades=["motriz"],
        material=["silla de ruedas", "espacio despejado"],
        seguridad="Giros amplios, no giros secos que carguen el hombro.",
    ),
    _ej(
        "agi-03", "Pasos laterales cortos con apoyo", "agilidad", "principal",
        ["agilidad", "equilibrio", "velocidad"], "de_pie", "intermedio",
        ["glúteo", "piernas"], 12, 3, 60, 45, 3,
        "Con una mano en la pared, da cuatro pasos laterales a un lado y cuatro al otro, rápidos y controlados.",
        discapacidades=["visual", "auditiva", "cognitiva", "intelectual"],
        material=["pared o barra de apoyo"],
        seguridad="Nunca sueltes el apoyo si el equilibrio falla.",
    ),
    _ej(
        "coo-01", "Coordinación mano-ojo con objeto", "agilidad", "principal",
        ["coordinacion", "reflejos"], "sentado", "principiante",
        ["manos", "hombros"], 20, 3, 60, 35, 2,
        "Pasa un objeto ligero de una mano a la otra a distintas alturas, luego acelera el ritmo.",
        material=["pelota blanda, calcetín o botella vacía"],
        adaptaciones={
            "visual": "Usa un objeto con textura marcada y nombra izquierda/derecha en cada pase.",
            "cognitiva": "Empieza a un ritmo de un segundo por pase y solo acelera si no se cae.",
        },
    ),
    _ej(
        "pot-01", "Empuje explosivo contra mesa", "fuerza", "principal",
        ["potencia", "fuerza", "velocidad"], "sentado", "intermedio",
        ["pectoral", "tríceps", "hombros"], 8, 4, 50, 50, 4,
        "Manos en el borde de una mesa firme: empuja con un impulso rápido y vuelve lento. Ocho repeticiones.",
        material=["mesa estable"],
        adaptaciones={"motriz": "Frena la silla. Empuja solo el rango libre de dolor."},
        seguridad="La mesa no debe desplazarse; comprueba que esté anclada o contra la pared.",
    ),
    _ej(
        "pot-02", "Propulsión explosiva corta", "fuerza", "principal",
        ["potencia", "velocidad", "fuerza"], "silla", "avanzado",
        ["dorsal", "tríceps", "hombros"], 6, 4, 70, 70, 5,
        "Seis empujes máximos en 8-10 metros, caminando de vuelta. Prioriza la explosión, no la distancia.",
        discapacidades=["motriz"],
        material=["silla de ruedas", "espacio despejado"],
        seguridad="Descansa el hombro entre series; para si hay pinchazo.",
    ),
    _ej(
        "cor-01", "Estabilidad de tronco con seña", "core", "principal",
        ["core", "equilibrio", "reflejos"], "sentado", "principiante",
        ["core", "oblicuos"], 10, 3, 50, 40, 2,
        "Sin apoyar la espalda, resiste un toque suave en un hombro y luego en el otro sin perder la postura.",
        adaptaciones={"motriz": "Empieza con toques muy suaves y el cinturón abrochado."},
        seguridad="Alguien cerca si retiras el respaldo.",
    ),

    # ---------------------------------------------------- vuelta a la calma
    _ej(
        "fle-01", "Estiramiento de pectoral en marco", "flexibilidad", "vuelta_a_la_calma",
        ["flexibilidad", "movilidad"], "de_pie", "principiante",
        ["pectoral"], 3, 2, 60, 20, 1,
        "Apoya el antebrazo en el marco de una puerta y gira suavemente el tronco; mantén 20 segundos.",
        discapacidades=["visual", "auditiva", "cognitiva", "intelectual"],
        adaptaciones={"motriz": "Realiza el mismo estiramiento sentado apoyando el antebrazo en la pared."},
    ),
    _ej(
        "fle-02", "Estiramiento de dorsal sentado", "flexibilidad", "vuelta_a_la_calma",
        ["flexibilidad"], "sentado", "principiante",
        ["dorsal", "costado"], 3, 2, 60, 20, 1,
        "Eleva un brazo e inclina el tronco al lado contrario manteniendo el glúteo apoyado; 20 segundos por lado.",
    ),
    _ej(
        "fle-03", "Estiramiento de isquiotibiales", "flexibilidad", "vuelta_a_la_calma",
        ["flexibilidad", "movilidad"], "sentado", "principiante",
        ["isquiotibiales"], 3, 2, 60, 20, 1,
        "Extiende una pierna al frente con el talón apoyado e inclínate desde la cadera sin redondear la espalda.",
        adaptaciones={"motriz": "Usa una banda alrededor del pie para acercar la pierna sin flexionar el tronco."},
        material=["banda elástica opcional"],
    ),
    _ej(
        "fle-04", "Estiramiento de cuello suave", "flexibilidad", "vuelta_a_la_calma",
        ["flexibilidad", "rehabilitacion"], "sentado", "principiante",
        ["cuello", "trapecio"], 3, 2, 45, 15, 1,
        "Lleva la oreja hacia el hombro con ayuda de la mano y respira profundo 20 segundos por lado.",
        seguridad="Presión mínima; el estiramiento nunca debe generar hormigueo.",
    ),
    _ej(
        "fle-05", "Movilidad de columna gato-camello", "flexibilidad", "vuelta_a_la_calma",
        ["movilidad", "flexibilidad"], "colchoneta", "principiante",
        ["columna", "core"], 10, 2, 60, 30, 2,
        "En cuadrupedia, alterna redondear la espalda y hundirla suavemente al ritmo de la respiración.",
        discapacidades=["visual", "auditiva", "cognitiva"],
        adaptaciones={"motriz": "Versión sentada: redondea y extiende la columna apoyando las manos en las rodillas."},
    ),
    _ej(
        "fle-06", "Estiramiento de flexor de cadera", "flexibilidad", "vuelta_a_la_calma",
        ["flexibilidad", "movilidad"], "colchoneta", "intermedio",
        ["psoas", "cuádriceps"], 3, 2, 60, 25, 2,
        "En posición de zancada apoyada, desplaza la cadera al frente manteniendo el tronco erguido; 20 segundos por lado.",
        discapacidades=["visual", "auditiva", "cognitiva"],
    ),
    _ej(
        "fle-07", "Estiramiento de muñeca y antebrazo", "flexibilidad", "vuelta_a_la_calma",
        ["flexibilidad", "rehabilitacion"], "sentado", "principiante",
        ["antebrazo", "muñeca"], 3, 2, 45, 15, 1,
        "Extiende el brazo y lleva los dedos hacia abajo y luego hacia arriba con la otra mano; 15 segundos cada uno.",
        adaptaciones={"motriz": "Especialmente recomendable tras sesiones de propulsión en silla."},
    ),
    _ej(
        "fle-08", "Relajación guiada final", "flexibilidad", "vuelta_a_la_calma",
        ["rehabilitacion", "general"], "sentado", "principiante",
        ["cuerpo completo"], 1, 1, 180, 0, 1,
        "Tres minutos de respiración lenta relajando de forma progresiva hombros, brazos y piernas.",
        adaptaciones={"cognitiva": "Nombra en voz alta cada parte del cuerpo que se relaja para guiar la atención."},
    ),
]


def ejercicio_por_id(id_ejercicio: str) -> dict[str, Any] | None:
    """Busca un ejercicio del catálogo embebido por su `id`; None si no existe."""
    return next((e for e in CATALOGO_EJERCICIOS if e["id"] == id_ejercicio), None)
