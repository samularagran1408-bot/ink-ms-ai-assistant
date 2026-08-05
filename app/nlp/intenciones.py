"""Clasificador de intenciones por coincidencia ponderada de frases y palabras.

Sustituye la detección anterior (una consulta a Mongo con `$in` sobre las
palabras crudas del mensaje), que fallaba con acentos, signos y plurales y solo
cubría tres intenciones.
"""

from dataclasses import dataclass, field

from app.nlp.texto import normalizar, raiz, tokenizar

PESO_FRASE = 3.0
PESO_PALABRA = 1.0
# Un poco más permisivo: si no hay match fuerte, el chat usa el LLM conversacional
UMBRAL_CONFIANZA = 0.38


@dataclass(frozen=True)
class Intencion:
    nombre: str
    descripcion: str
    frases: tuple[str, ...] = ()
    palabras: tuple[str, ...] = ()
    # Palabras que se comparan literalmente, sin reducir a su raíz. Necesario
    # cuando la raíz choca con otra del dominio: "entrenador" y "entrenar"
    # comparten raíz, y sin esto "puedo entrenar" activaría la verificación de
    # entrenador.
    palabras_exactas: tuple[str, ...] = ()
    # Multiplicador para que las intenciones específicas ganen a las genéricas
    prioridad: float = 1.0
    # Cortesía (saludo, gracias, despedida). Si aparece incrustada en una
    # petición más larga es un prefijo educado, no lo que el usuario pide.
    social: bool = False
    raices: frozenset = field(default=frozenset(), compare=False)
    exactas: frozenset = field(default=frozenset(), compare=False)


def _construir(intencion: Intencion) -> Intencion:
    return Intencion(
        nombre=intencion.nombre,
        descripcion=intencion.descripcion,
        frases=tuple(normalizar(f) for f in intencion.frases),
        palabras=intencion.palabras,
        palabras_exactas=intencion.palabras_exactas,
        prioridad=intencion.prioridad,
        social=intencion.social,
        raices=frozenset(raiz(normalizar(p)) for p in intencion.palabras if p),
        exactas=frozenset(normalizar(p) for p in intencion.palabras_exactas if p),
    )


_DEFINICIONES = [
    Intencion(
        nombre="saludo",
        descripcion="Saludo inicial",
        frases=("buenos dias", "buenas tardes", "buenas noches", "que tal", "como estas"),
        palabras=("hola", "holi", "hey", "saludos", "buenas", "alo", "ola"),
        social=True,
    ),
    Intencion(
        nombre="despedida",
        descripcion="Cierre de la conversación",
        frases=("hasta luego", "nos vemos", "hasta pronto", "me voy"),
        palabras=("adios", "chao", "bye", "despedida"),
        social=True,
    ),
    Intencion(
        nombre="agradecimiento",
        descripcion="Agradecimiento",
        frases=("muchas gracias", "te lo agradezco", "muy amable"),
        palabras=("gracias", "genial", "excelente", "perfecto"),
        social=True,
    ),
    Intencion(
        nombre="ayuda",
        descripcion="Qué puede hacer el asistente",
        frases=(
            "que puedes hacer", "en que me puedes ayudar", "que sabes hacer",
            "cuales son tus funciones", "necesito ayuda", "como funcionas",
            "que opciones tengo", "menu de opciones",
        ),
        palabras=("ayuda", "ayudar", "funciones", "opciones", "puedes", "sirves", "capacidades"),
    ),
    Intencion(
        nombre="rutinas",
        descripcion="Generar una rutina de entrenamiento",
        frases=(
            "generar rutina", "crear rutina", "necesito una rutina", "quiero una rutina",
            "plan de entrenamiento", "rutina de entrenamiento", "rutina adaptada",
            "programa de ejercicios", "quiero entrenar", "plan semanal",
        ),
        palabras=("rutina", "rutinas", "entrenamiento", "entrenar", "plan", "programa", "sesion"),
        prioridad=1.2,
    ),
    Intencion(
        nombre="ejercicios",
        descripcion="Ejercicios concretos y cómo hacerlos",
        frases=(
            "que ejercicios", "ejercicios para", "como hago el ejercicio",
            "ejercicios de fuerza", "ejercicios de movilidad", "ejercicios en silla",
            "ejercicios de resistencia", "ejercicios de equilibrio",
        ),
        palabras=(
            "ejercicio", "ejercicios", "repeticiones", "series", "fuerza", "movilidad",
            "resistencia", "equilibrio", "cardio", "abdominales", "brazos", "piernas",
            "core", "tronco", "hombros", "espalda",
        ),
        prioridad=1.1,
    ),
    Intencion(
        nombre="calentamiento",
        descripcion="Calentamiento previo",
        frases=("como calentar", "antes de entrenar", "calentamiento previo"),
        palabras=("calentamiento", "calentar", "activacion"),
        prioridad=1.3,
    ),
    Intencion(
        nombre="estiramiento",
        descripcion="Estiramiento y vuelta a la calma",
        frases=("como estirar", "despues de entrenar", "vuelta a la calma"),
        palabras=("estiramiento", "estirar", "flexibilidad", "elongacion"),
        prioridad=1.3,
    ),
    Intencion(
        nombre="frecuencia",
        descripcion="Cuántas veces entrenar",
        frases=(
            "cuantas veces", "cuantos dias", "con que frecuencia", "cada cuanto",
            "cuanto tiempo debo entrenar", "cuanto dura",
        ),
        palabras=("frecuencia", "veces", "dias", "semana", "duracion"),
        prioridad=1.25,
    ),
    Intencion(
        nombre="eventos",
        descripcion="Eventos y competencias disponibles",
        frases=(
            "que eventos hay", "eventos disponibles", "proximos eventos",
            "recomiendame eventos", "eventos cerca", "hay competencias",
            "calendario de eventos", "eventos para mi",
        ),
        palabras=("evento", "eventos", "competencia", "competencias", "torneo", "torneos", "calendario"),
        prioridad=1.2,
    ),
    Intencion(
        nombre="inscripcion",
        descripcion="Cómo inscribirse a un evento",
        frases=(
            "como me inscribo", "quiero inscribirme", "como participar",
            "como me registro en el evento", "lista de espera", "cancelar inscripcion",
        ),
        palabras=("inscribir", "inscripcion", "inscribirme", "participar", "cupo", "cupos", "anotarme"),
        prioridad=1.35,
    ),
    Intencion(
        nombre="deportes",
        descripcion="Catálogo de deportes disponibles",
        frases=(
            "que deportes hay", "deportes disponibles", "que deportes puedo practicar",
            "lista de deportes", "deportes inclusivos",
        ),
        palabras=("deporte", "deportes", "disciplina", "disciplinas", "modalidad"),
        prioridad=1.2,
    ),
    Intencion(
        nombre="discapacidades",
        descripcion="Tipos de discapacidad soportados",
        frases=(
            "que discapacidades", "tipos de discapacidad", "categorias de discapacidad",
        ),
        palabras=("discapacidad", "discapacidades", "limitacion", "condicion"),
        prioridad=1.15,
    ),
    Intencion(
        nombre="adaptaciones",
        descripcion="Adaptaciones de un deporte a una discapacidad",
        frases=(
            "que adaptaciones", "como se adapta", "adaptaciones del deporte",
            "como adaptar el ejercicio", "material adaptado",
        ),
        palabras=("adaptacion", "adaptaciones", "adaptado", "adaptar", "ajuste", "ajustes"),
        prioridad=1.3,
    ),
    Intencion(
        nombre="navegacion_voz",
        descripcion="Navegar por la app con comandos de voz",
        frases=(
            "ir a inicio", "ir a eventos", "abrir calendario", "mi progreso",
            "abrir perfil", "abrir accesibilidad", "comandos de voz",
            "activar microfono",
        ),
        palabras=("voz", "microfono", "navegar", "comando", "comandos"),
        prioridad=1.35,
    ),
    Intencion(
        nombre="accesibilidad",
        descripcion="Accesibilidad de instalaciones y de la app",
        frases=(
            "es accesible", "lector de pantalla", "alto contraste",
            "rampa de acceso", "silla de ruedas acceso", "subtitulos",
            "comandos por voz",
        ),
        palabras=("accesibilidad", "accesible", "rampa", "braille", "subtitulo", "contraste", "voz"),
        prioridad=1.3,
    ),
    Intencion(
        nombre="verificacion_entrenador",
        descripcion="Cómo ser entrenador verificado",
        frases=(
            "ser entrenador", "quiero ser entrenador", "entrenador verificado",
            "verificacion de entrenador", "certificarme como entrenador",
        ),
        palabras=("coach", "certificacion"),
        palabras_exactas=("entrenador", "entrenadora", "entrenadores"),
        prioridad=1.4,
    ),
    Intencion(
        nombre="verificacion_organizador",
        descripcion="Cómo ser organizador verificado",
        frases=(
            "ser organizador", "quiero ser organizador", "organizador verificado",
            "verificacion de organizador", "quiero crear eventos", "como creo un evento",
            "organizar un evento",
        ),
        palabras=("organizador", "organizar"),
        prioridad=1.4,
    ),
    Intencion(
        nombre="quiz",
        descripcion="Quiz de aptitud para roles",
        frases=(
            "quiz de aptitud", "hacer el quiz", "generar quiz", "examen de aptitud",
            "prueba de conocimientos", "cuantas preguntas tiene el quiz",
            "nota minima del quiz",
        ),
        palabras=("quiz", "quices", "quizes", "examen", "cuestionario", "evaluacion", "preguntas", "puntaje"),
        prioridad=1.5,
    ),
    Intencion(
        nombre="progreso",
        descripcion="Progreso, estadísticas y reportes",
        frases=(
            "mi progreso", "mis estadisticas", "como voy", "mi rendimiento",
            "ver mis reportes", "mi historial",
        ),
        palabras=("progreso", "estadistica", "estadisticas", "rendimiento", "reporte", "reportes", "historial", "avance"),
        prioridad=1.25,
    ),
    Intencion(
        nombre="nutricion",
        descripcion="Alimentación e hidratación",
        frases=("que debo comer", "antes de entrenar comer", "cuanta agua"),
        palabras=("nutricion", "alimentacion", "comer", "dieta", "hidratacion", "agua", "proteina"),
        prioridad=1.3,
    ),
    Intencion(
        nombre="lesiones",
        descripcion="Dolor, lesiones y seguridad",
        frases=(
            "me duele", "tengo dolor", "me lesione", "es seguro", "puedo lastimarme",
            "que hago si me duele",
        ),
        palabras=("dolor", "duele", "lesion", "lesiones", "molestia", "seguridad", "riesgo", "fatiga"),
        prioridad=1.4,
    ),
    Intencion(
        nombre="motivacion",
        descripcion="Motivación y constancia",
        frases=(
            "no tengo ganas", "estoy desmotivado", "me cuesta seguir",
            "como mantener la constancia", "quiero rendirme",
        ),
        palabras=("motivacion", "desanimado", "desmotivado", "constancia", "animo", "rendirme", "pereza"),
        prioridad=1.3,
    ),
    Intencion(
        nombre="equipamiento",
        descripcion="Material y equipamiento necesario",
        frases=("que material necesito", "que necesito para", "que equipo hace falta"),
        palabras=("material", "materiales", "equipamiento", "equipo", "implemento", "banda", "mancuerna", "silla"),
        prioridad=1.2,
    ),
    Intencion(
        nombre="plataforma",
        descripcion="Qué es InkluSport",
        frases=(
            "que es inklusport", "de que se trata", "para que sirve la plataforma",
            "como funciona la plataforma", "quien esta detras",
        ),
        palabras=("inklusport", "plataforma", "aplicacion", "app", "sistema"),
    ),
    Intencion(
        nombre="cuenta",
        descripcion="Cuenta, perfil y registro",
        frases=(
            "crear cuenta", "cambiar mi contraseña", "editar mi perfil",
            "actualizar mis datos", "olvide mi contraseña", "iniciar sesion",
        ),
        palabras=("cuenta", "perfil", "registro", "registrarme", "contraseña", "clave", "sesion", "correo"),
        prioridad=1.25,
    ),
    Intencion(
        nombre="soporte",
        descripcion="Contacto con soporte humano",
        frases=(
            "hablar con una persona", "contactar soporte", "atencion al cliente",
            "reportar un problema", "tengo un error",
        ),
        palabras=("soporte", "contacto", "reclamo", "queja", "problema", "error", "falla"),
        prioridad=1.2,
    ),
    Intencion(
        nombre="peso",
        descripcion="Control de peso y composición corporal",
        frases=(
            "bajar de peso", "perder peso", "quiero adelgazar", "bajar barriga",
            "quemar grasa", "perder grasa", "subir de peso", "ganar masa",
            "bajar kilos", "perder kilos",
        ),
        palabras=("adelgazar", "kilos", "grasa", "obesidad", "sobrepeso", "delgado", "barriga", "abdomen"),
        prioridad=1.35,
    ),
    Intencion(
        nombre="salud",
        descripcion="Condiciones médicas y aptitud para entrenar",
        frases=(
            "puedo entrenar si", "es seguro para mi", "tengo una condicion",
            "estoy embarazada", "tomo medicacion", "tengo la tension alta",
            "soy mayor", "tengo problemas de corazon",
        ),
        palabras=(
            "diabetes", "diabetico", "hipertension", "tension", "presion", "corazon",
            "cardiaco", "asma", "epilepsia", "embarazo", "embarazada", "medicamento",
            "medicacion", "cirugia", "operacion", "artritis", "artrosis", "osteoporosis",
            "anemia", "colesterol", "enfermedad", "medico", "contraindicacion",
        ),
        prioridad=1.55,
    ),
    Intencion(
        nombre="donde_entrenar",
        descripcion="Lugar donde realizar la sesión",
        frases=(
            "entrenar en casa", "entrenar en el parque", "entrenar al aire libre",
            "necesito gimnasio", "donde puedo entrenar", "en la playa",
        ),
        palabras=("casa", "hogar", "gimnasio", "parque", "playa", "calle", "exterior", "interior", "piscina"),
        prioridad=1.3,
    ),
    Intencion(
        nombre="descanso",
        descripcion="Descanso, sueño y recuperación",
        frases=(
            "cuanto debo descansar", "dias de descanso", "cuanto dormir",
            "estoy muy cansado", "agujetas", "dolor muscular al dia siguiente",
        ),
        palabras=("descanso", "descansar", "dormir", "sueño", "recuperacion", "cansancio", "agujetas", "sobreentrenamiento"),
        prioridad=1.35,
    ),
    Intencion(
        nombre="respiracion",
        descripcion="Cómo respirar durante el ejercicio",
        frases=("como respirar", "como respiro", "me falta el aire", "control de la respiracion"),
        palabras=("respiracion", "respirar", "respiro", "aire", "oxigeno", "ahogo"),
        prioridad=1.4,
    ),
    Intencion(
        nombre="objetivos",
        descripcion="Definir objetivos y por dónde empezar",
        frases=(
            "por donde empiezo", "quiero empezar", "soy principiante",
            "nunca he entrenado", "como empiezo", "primer paso",
        ),
        palabras=("empezar", "principiante", "comenzar", "inicio", "novato", "objetivo", "meta"),
        prioridad=1.25,
    ),
]

INTENCIONES: dict[str, Intencion] = {
    d.nombre: _construir(d) for d in _DEFINICIONES
}


COBERTURA_SOCIAL_MINIMA = 0.8


def _mejor_candidato(ranking: list[dict]) -> dict:
    """Elige la intención ganadora descartando la cortesía incidental.

    "que tal si entreno en la playa" contiene el saludo "que tal", pero lo que
    pide el usuario es lo otro. Un saludo solo gana si abarca casi todo el
    mensaje o si no hay ninguna otra intención candidata.
    """
    mejor = ranking[0]
    if not mejor["social"] or mejor["cobertura"] >= COBERTURA_SOCIAL_MINIMA:
        return mejor
    return next((r for r in ranking if not r["social"]), mejor)


def clasificar(mensaje: str) -> dict:
    """Devuelve la intención más probable del mensaje.

    Resultado: `nombre` (None si no hay confianza suficiente), `confianza`
    entre 0 y 1, `terminos` coincidentes y el ranking completo.
    """
    texto = normalizar(mensaje)
    if not texto:
        return {"nombre": None, "confianza": 0.0, "terminos": [], "ranking": []}

    palabras_mensaje = set(tokenizar(mensaje))
    raices_mensaje = {raiz(p) for p in palabras_mensaje}
    total_terminos = max(1, len(raices_mensaje))
    ranking = []

    for intencion in INTENCIONES.values():
        puntaje = 0.0
        cubiertos = 0
        terminos = []

        for frase in intencion.frases:
            if frase and frase in texto:
                puntaje += PESO_FRASE
                cubiertos += len(frase.split())
                terminos.append(frase)

        coincidencias = raices_mensaje & intencion.raices
        puntaje += PESO_PALABRA * len(coincidencias)
        cubiertos += len(coincidencias)
        terminos.extend(sorted(coincidencias))

        literales = palabras_mensaje & intencion.exactas
        puntaje += PESO_PALABRA * len(literales)
        cubiertos += len(literales)
        terminos.extend(sorted(literales))

        if puntaje <= 0:
            continue

        puntaje *= intencion.prioridad
        ranking.append({
            "intencion": intencion.nombre,
            "puntaje": round(puntaje, 3),
            "cobertura": min(1.0, cubiertos / total_terminos),
            "terminos": terminos,
            "social": intencion.social,
        })

    if not ranking:
        return {"nombre": None, "confianza": 0.0, "terminos": [], "ranking": []}

    ranking.sort(key=lambda r: r["puntaje"], reverse=True)
    mejor = _mejor_candidato(ranking)
    # La confianza combina la fuerza de la coincidencia con la proporción del
    # mensaje reconocida: así "hola" se clasifica con seguridad, mientras que una
    # frase larga con una única palabra del dominio queda por debajo del umbral.
    fuerza = mejor["puntaje"] / (mejor["puntaje"] + 2.0)
    confianza = round(fuerza * 0.6 + mejor["cobertura"] * 0.4, 3)

    return {
        "nombre": mejor["intencion"] if confianza >= UMBRAL_CONFIANZA else None,
        "confianza": confianza,
        "terminos": mejor["terminos"],
        "ranking": ranking[:4],
        "mejor_candidato": mejor["intencion"],
    }
