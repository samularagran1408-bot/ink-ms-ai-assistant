"""Base de conocimiento del chatbot.

Cada intención tiene varias redacciones alternativas para que la conversación no
repita literalmente la misma frase, adaptaciones por tipo de discapacidad y una
`accion` opcional que indica al agente que debe enriquecer la respuesta con
datos reales de los otros microservicios.

Acciones soportadas por el agente: eventos | rutina | deportes | discapacidades |
adaptaciones | ejercicios | quiz.
"""

from typing import Any

CONOCIMIENTO: dict[str, dict[str, Any]] = {
    "saludo": {
        "respuestas": [
            "Hola, soy el asistente de InkluSport. Puedo armarte rutinas adaptadas, "
            "recomendarte eventos y resolver dudas sobre deporte inclusivo.",
            "Hola, qué bueno tenerte por aquí. Estoy para ayudarte con entrenamientos "
            "adaptados, eventos y todo lo relacionado con deporte inclusivo.",
            "Hola. Soy tu asistente de InkluSport. Dime qué necesitas y lo vemos juntos.",
        ],
        "adaptaciones": {
            "cognitiva": "Hola. Soy tu asistente. Puedo ayudarte con tres cosas: "
                         "1) rutinas, 2) eventos, 3) dudas. Dime un número o escríbelo.",
        },
        "sugerencias": [
            "Pídeme una rutina adaptada",
            "Pregúntame qué eventos hay disponibles",
            "Consúltame sobre adaptaciones de un deporte",
        ],
    },
    "despedida": {
        "respuestas": [
            "Hasta luego. Recuerda que la constancia importa más que la intensidad.",
            "Nos vemos. Cuando quieras retomar, aquí sigo disponible.",
            "Que te vaya muy bien. Vuelve cuando necesites ajustar tu entrenamiento.",
        ],
        "sugerencias": [],
    },
    "agradecimiento": {
        "respuestas": [
            "Con gusto. ¿Quieres que profundicemos en algo más?",
            "Para eso estoy. Si necesitas otra cosa, dime.",
            "Encantado de ayudar. Puedo seguir con rutinas, eventos o adaptaciones.",
        ],
        "sugerencias": ["Generar una rutina", "Ver eventos recomendados"],
    },
    "ayuda": {
        "respuestas": [
            "Puedo ayudarte con: rutinas de entrenamiento adaptadas a tu discapacidad, "
            "recomendación de eventos según tu perfil, información del catálogo de "
            "deportes y sus adaptaciones, y los quices de aptitud para entrenadores y "
            "organizadores.",
            "Estas son mis funciones: crear rutinas personalizadas, sugerirte eventos "
            "compatibles con tu perfil, explicarte adaptaciones deporte-discapacidad y "
            "guiarte en la verificación como entrenador u organizador.",
        ],
        "adaptaciones": {
            "cognitiva": "Puedo hacer 4 cosas: 1) rutinas de ejercicio, 2) recomendarte "
                         "eventos, 3) explicarte deportes y adaptaciones, 4) ayudarte con "
                         "el quiz de entrenador u organizador. Elige una.",
        },
        "sugerencias": [
            "Quiero una rutina para ganar fuerza",
            "¿Qué eventos hay disponibles?",
            "¿Qué adaptaciones tiene la natación?",
        ],
    },
    "rutinas": {
        "respuestas": [
            "Puedo generarte una rutina adaptada. Te preparo una propuesta con "
            "calentamiento, bloque principal y vuelta a la calma.",
            "Trabajemos tu rutina. La armo con ejercicios seleccionados según tu "
            "discapacidad y tu objetivo.",
        ],
        "sugerencias": [
            "Dime tu objetivo: fuerza, resistencia, movilidad o equilibrio",
            "Puedo generar la rutina completa en POST /api/ai/rutinas/generar",
        ],
        "accion": "rutina",
    },
    "ejercicios": {
        "respuestas": [
            "Tengo un catálogo de ejercicios adaptados clasificados por objetivo, "
            "posición y nivel. Te muestro los más adecuados para tu perfil.",
            "Puedo proponerte ejercicios concretos con series, repeticiones y su "
            "adaptación según tu discapacidad.",
        ],
        "sugerencias": ["Pídeme la rutina completa si quieres el plan ordenado"],
        "accion": "ejercicios",
    },
    "calentamiento": {
        "respuestas": [
            "El calentamiento debería durar entre 8 y 10 minutos: movilidad articular "
            "suave, activación de la zona que vas a trabajar y subida progresiva del "
            "ritmo cardíaco. Nunca empieces el bloque fuerte en frío.",
            "Dedica 8-10 minutos a calentar: primero movilidad de cuello, hombros y "
            "cadera, después activación específica y por último dos minutos de ritmo "
            "moderado.",
        ],
        "adaptaciones": {
            "motriz": "Calienta 8-10 minutos priorizando la movilidad de hombros y "
                      "muñecas si te desplazas en silla, ya que son las articulaciones "
                      "que más carga soportan.",
            "cognitiva": "Calienta así: 1) mueve hombros, 2) mueve cadera, "
                         "3) respira profundo, 4) empieza suave. Unos 8 minutos.",
        },
        "sugerencias": ["Te puedo armar el calentamiento dentro de una rutina completa"],
        "accion": "ejercicios",
    },
    "estiramiento": {
        "respuestas": [
            "Estira al terminar, cuando el músculo está caliente: mantén cada posición "
            "entre 20 y 30 segundos sin rebotes y sin llegar al dolor. Con 5 o 6 "
            "estiramientos de las zonas trabajadas es suficiente.",
            "La vuelta a la calma ideal son 5-8 minutos de estiramientos sostenidos de "
            "20 a 30 segundos, acompañados de respiración lenta.",
        ],
        "adaptaciones": {
            "motriz": "Prioriza pectoral, dorsal y antebrazo si usas silla: son las zonas "
                      "que más se acortan con la propulsión. Sostén 20-30 segundos sin dolor.",
        },
        "sugerencias": ["Puedo incluir la vuelta a la calma en tu rutina"],
        "accion": "ejercicios",
    },
    "frecuencia": {
        "respuestas": [
            "Para empezar, 3 sesiones por semana en días alternos es lo más sostenible: "
            "permite recuperar y crea el hábito. Cuando lo lleves bien, sube a 4 o 5.",
            "Lo recomendable son 3 días no consecutivos a la semana, de 30 a 45 minutos. "
            "Es mejor entrenar poco y seguido que mucho un solo día.",
        ],
        "adaptaciones": {
            "cognitiva": "Entrena 3 días por semana. Por ejemplo: lunes, miércoles y "
                         "viernes. Entre 30 y 40 minutos cada día.",
            "motriz": "Tres sesiones semanales en días alternos, dejando descanso para el "
                      "hombro si además te desplazas en silla a diario.",
        },
        "sugerencias": ["Puedo distribuir tu rutina en los días que tengas disponibles"],
    },
    "eventos": {
        "respuestas": [
            "Te reviso los eventos disponibles y te digo cuáles encajan con tu perfil.",
            "Consulto el calendario de eventos de la plataforma y te propongo los más "
            "compatibles con tu discapacidad.",
        ],
        "sugerencias": ["Pregúntame cómo inscribirte en el que te interese"],
        "accion": "eventos",
    },
    "inscripcion": {
        "respuestas": [
            "Para inscribirte necesitas tener sesión iniciada y elegir un evento con "
            "cupo disponible. La inscripción se hace desde el evento y, si el cupo está "
            "completo, entras automáticamente en lista de espera con una posición "
            "asignada. Al confirmar recibes un código QR para el control de asistencia.",
            "La inscripción requiere estar autenticado. Si el evento tiene cupo, queda "
            "confirmada y se genera tu QR de asistencia; si está lleno, pasas a lista de "
            "espera y avanzas si alguien cancela.",
        ],
        "adaptaciones": {
            "cognitiva": "Para inscribirte: 1) inicia sesión, 2) elige el evento, "
                         "3) pulsa inscribirme, 4) guarda el código QR. Si está lleno, "
                         "quedas en lista de espera.",
        },
        "sugerencias": ["¿Quieres que te recomiende eventos con cupo disponible?"],
        "accion": "eventos",
    },
    "deportes": {
        "respuestas": [
            "Te muestro el catálogo de deportes activos con su nivel de dificultad.",
            "Consulto los deportes disponibles en la plataforma y sus adaptaciones.",
        ],
        "sugerencias": ["Pregúntame por las adaptaciones de un deporte concreto"],
        "accion": "deportes",
    },
    "discapacidades": {
        "respuestas": [
            "La plataforma trabaja con categorías de discapacidad (visual, física o "
            "motriz, auditiva, cognitiva o intelectual y múltiple) y cada deporte tiene "
            "registradas sus adaptaciones para esas categorías.",
            "Te muestro las categorías de discapacidad registradas y cómo se relacionan "
            "con los deportes disponibles.",
        ],
        "sugerencias": ["¿Quieres ver las adaptaciones de un deporte concreto?"],
        "accion": "discapacidades",
    },
    "adaptaciones": {
        "respuestas": [
            "Cada combinación deporte-discapacidad tiene adaptaciones registradas: "
            "material específico, ajustes de reglamento y apoyos de comunicación. Te "
            "muestro las que hay cargadas.",
            "Te consulto las adaptaciones registradas por deporte para que veas qué "
            "ajustes concretos se aplican.",
        ],
        "sugerencias": ["Dime el deporte que te interesa y lo miramos en detalle"],
        "accion": "adaptaciones",
    },
    "accesibilidad": {
        "respuestas": [
            "La accesibilidad se trabaja en dos frentes: la plataforma (contraste, "
            "lectores de pantalla, comandos por voz, texto alternativo y navegación "
            "por teclado) y los eventos, donde la descripción indica accesos, apoyos "
            "disponibles y adaptaciones del deporte.",
            "Cada evento describe sus condiciones de acceso, y la aplicación soporta "
            "lectores de pantalla, alto contraste, voz y navegación por teclado. "
            "En Accesibilidad puedes activar el micrófono y ajustar la interfaz.",
        ],
        "adaptaciones": {
            "visual": "La aplicación es compatible con lectores de pantalla y ofrece alto "
                      "contraste. También puedes usar comandos por voz desde el botón "
                      "flotante de accesibilidad.",
            "auditiva": "Los contenidos priorizan texto e indicaciones visuales. Puedes "
                        "usar comandos por voz desde el botón flotante de accesibilidad.",
        },
        "sugerencias": ["¿Quieres que te explique los comandos de voz?"],
        "accion": None,
    },
    "navegacion_voz": {
        "respuestas": [
            "Puedes navegar con voz desde el botón flotante de accesibilidad. "
            "Di por ejemplo: ir al inicio, ir a eventos, abrir calendario, mi progreso, "
            "perfil, accesibilidad o abrir asistente. También funciona «ayuda» y "
            "«alto contraste».",
        ],
        "sugerencias": [
            "Abre Accesibilidad para ver el glosario completo",
            "Activa el micrófono del botón flotante",
        ],
        "accion": None,
    },
    "verificacion_entrenador": {
        "respuestas": [
            "Para ser entrenador verificado necesitas aprobar el quiz de aptitud con al "
            "menos 75, aportar certificación, acreditar 6 meses o más de experiencia, "
            "tener eventos como entrenador y verificar tu identidad.",
            "La verificación de entrenador exige: quiz de aptitud aprobado con 75 o más, "
            "archivo de certificación, experiencia mínima de 6 meses, eventos dirigidos y "
            "documento de identidad validado.",
        ],
        "adaptaciones": {
            "cognitiva": "Para ser entrenador necesitas: 1) aprobar el quiz con 75, "
                         "2) subir tu certificado, 3) tener 6 meses de experiencia, "
                         "4) haber dirigido eventos, 5) validar tu identidad.",
        },
        "sugerencias": ["Puedo generarte ahora el quiz de entrenador"],
        "accion": "quiz",
    },
    "verificacion_organizador": {
        "respuestas": [
            "Para ser organizador verificado debes aprobar el quiz de aptitud con al "
            "menos 70, haber asistido a eventos, crear un evento de prueba, tener correo "
            "y teléfono verificados y cierta antigüedad en la plataforma.",
            "La verificación de organizador pide: quiz aprobado con 70 o más, asistencia "
            "previa a eventos, un evento de prueba, correo y teléfono verificados y días "
            "mínimos de antigüedad.",
        ],
        "sugerencias": ["Puedo generarte ahora el quiz de organizador"],
        "accion": "quiz",
    },
    "quiz": {
        "respuestas": [
            "Los quices de aptitud se generan automáticamente y son distintos cada vez. "
            "El de organizador se aprueba con 70 y el de entrenador con 75; al evaluarlo "
            "se registra tu puntaje en tu perfil.",
            "Genero quices de aptitud con preguntas de opción múltiple sobre la operación "
            "real de la plataforma. Organizador aprueba con 70, entrenador con 75.",
        ],
        "sugerencias": [
            "POST /api/ai/quiz/organizer/generar para el quiz de organizador",
            "POST /api/ai/quiz/trainer/generar para el quiz de entrenador",
        ],
        "accion": "quiz",
    },
    "progreso": {
        "respuestas": [
            "Tu progreso se construye con las sesiones registradas, la asistencia a "
            "eventos y la evolución de tus rutinas. El servicio de reportes consolida "
            "esa información.",
            "Puedo analizar tu historial de participación en eventos e inscripciones para "
            "darte una lectura de tu evolución.",
        ],
        "sugerencias": ["Prueba el análisis de competencia con tu usuario"],
        "accion": "eventos",
    },
    "nutricion": {
        "respuestas": [
            "Como orientación general: come algo ligero con carbohidratos 1 o 2 horas "
            "antes de entrenar, hidrátate durante la sesión y combina proteína con "
            "carbohidrato en la comida posterior. Para pautas personalizadas consulta a "
            "un profesional de nutrición.",
            "Antes de entrenar, una comida ligera y digerible; durante, agua a sorbos; "
            "después, proteína y carbohidrato. Cualquier plan específico debe validarlo "
            "un nutricionista, sobre todo si tomas medicación.",
        ],
        "adaptaciones": {
            "cognitiva": "Regla simple: 1) come algo ligero 1 hora antes, 2) bebe agua "
                         "durante, 3) después come proteína (huevo, pollo, legumbre). "
                         "Pregunta a un nutricionista para tu caso.",
        },
        "sugerencias": ["Puedo ajustar la intensidad de la rutina a tu energía disponible"],
    },
    "lesiones": {
        "respuestas": [
            "Si aparece dolor, detén el ejercicio. El dolor articular agudo, el mareo o "
            "la falta de aire son señales de parar; la molestia muscular leve al día "
            "siguiente es normal. Si el dolor persiste más de 48 horas o limita tu "
            "movilidad, consulta a un profesional de salud antes de seguir entrenando.",
            "Ante dolor, para la sesión y no la fuerces. Diferencia la fatiga muscular "
            "normal del dolor agudo o punzante: el segundo requiere valoración "
            "profesional. Puedo rebajarte la intensidad de la rutina mientras tanto.",
        ],
        "adaptaciones": {
            "cognitiva": "Si te duele: 1) para, 2) descansa, 3) cuéntaselo a tu "
                         "entrenador o a un médico. El dolor fuerte no es normal.",
            "motriz": "Si el dolor es de hombro y usas silla, reduce el volumen de "
                      "propulsión y refuerza rotadores y estiramiento de pectoral. Si "
                      "persiste, consulta a fisioterapia.",
        },
        "sugerencias": ["Puedo generarte una rutina de baja intensidad y movilidad"],
    },
    "motivacion": {
        "respuestas": [
            "Bajar la motivación es parte del proceso. Lo que mejor funciona es reducir "
            "la meta: una sesión corta de 15 minutos hecha vale más que una perfecta "
            "aplazada. Fija días fijos y registra cada sesión cumplida.",
            "Cuando cuesta arrancar, baja el listón en lugar de saltarte la sesión: "
            "calentamiento y un bloque corto. La constancia se construye con sesiones "
            "pequeñas y repetidas, no con semanas heroicas.",
        ],
        "adaptaciones": {
            "cognitiva": "Haz algo pequeño hoy: 10 minutos. Es suficiente. Marca en un "
                         "calendario cada día que entrenas y verás cómo avanzas.",
        },
        "sugerencias": ["¿Quieres una rutina corta de 15 minutos para hoy?"],
    },
    "equipamiento": {
        "respuestas": [
            "Con muy poco puedes entrenar: una silla estable, una banda elástica y una "
            "botella de agua como peso cubren la mayoría de los ejercicios del catálogo. "
            "Cada deporte de la plataforma indica además su material requerido.",
            "El material básico es una silla firme, una banda elástica y algo de peso "
            "ligero. En el catálogo de deportes puedes ver el material específico de cada "
            "disciplina y sus adaptaciones.",
        ],
        "sugerencias": ["Te muestro el material de cada deporte si quieres"],
        "accion": "deportes",
    },
    "plataforma": {
        "respuestas": [
            "InkluSport es una plataforma de deporte inclusivo: reúne el catálogo de "
            "deportes con sus adaptaciones por discapacidad, gestiona eventos e "
            "inscripciones, y ofrece asistencia con rutinas adaptadas y recomendaciones "
            "personalizadas.",
            "InkluSport conecta a personas con discapacidad con deportes y eventos "
            "adaptados. Incluye catálogo de adaptaciones, gestión de eventos, "
            "verificación de entrenadores y organizadores, y este asistente de IA.",
        ],
        "sugerencias": ["¿Qué te gustaría explorar primero: rutinas o eventos?"],
    },
    "cuenta": {
        "respuestas": [
            "La gestión de cuenta y perfil se hace desde tu área de usuario: ahí "
            "actualizas tus datos, tu tipo de discapacidad y tus preferencias. Tener el "
            "perfil completo mejora bastante la calidad de mis recomendaciones.",
            "Tus datos de acceso y perfil se administran en la sección de usuario. "
            "Mantén actualizado el tipo de discapacidad, porque es lo que uso para "
            "adaptar rutinas y filtrar eventos compatibles.",
        ],
        "sugerencias": ["Cuando tengas el perfil listo, pídeme una rutina adaptada"],
    },
    "soporte": {
        "respuestas": [
            "Si es un problema técnico o necesitas atención humana, repórtalo desde el "
            "área de soporte de la plataforma indicando qué intentabas hacer y qué "
            "mensaje viste. Yo puedo seguir ayudándote con entrenamiento, eventos y "
            "adaptaciones.",
            "Para incidencias que requieran intervención humana usa el canal de soporte "
            "de la plataforma. Describe el paso donde falló y el mensaje de error.",
        ],
        "sugerencias": ["¿Te ayudo mientras con una rutina o con eventos?"],
    },
    "peso": {
        "respuestas": [
            "El peso se mueve sobre todo por la alimentación; el entrenamiento aporta "
            "gasto y, más importante, conserva la masa muscular mientras bajas. Lo que "
            "mejor funciona es combinar 2 o 3 sesiones de fuerza por semana con trabajo "
            "continuo de resistencia y sostenerlo en el tiempo. Un ritmo razonable es "
            "entre 0,5 y 1 % del peso corporal por semana.",
            "Para cambiar composición corporal necesitas constancia más que intensidad: "
            "fuerza para mantener músculo, trabajo aeróbico para sumar gasto y una "
            "alimentación algo por debajo de tu gasto diario. Puedo armarte la parte de "
            "entrenamiento; la pauta nutricional concreta la debe revisar un profesional.",
        ],
        "adaptaciones": {
            "motriz": "Si te desplazas en silla, el gasto viene del tren superior: "
                      "intervalos de propulsión y ergómetro de brazos funcionan muy bien. "
                      "Combínalo con fuerza 2 o 3 veces por semana y una alimentación "
                      "ligeramente por debajo de tu gasto. Cuida el hombro alternando "
                      "días de empuje intenso con días suaves.",
            "cognitiva": "Tres ideas: 1) muévete casi todos los días, 2) haz fuerza dos "
                         "veces por semana, 3) come más verdura y menos ultraprocesado. "
                         "Con eso ya es suficiente para empezar.",
        },
        "sugerencias": [
            "Pídeme una rutina con objetivo 'peso' y te la preparo",
            "¿Quieres que combine fuerza y resistencia en la misma sesión?",
        ],
        "accion": "rutina",
    },
    "salud": {
        "respuestas": [
            "Con una condición médica de por medio la respuesta honesta es que el visto "
            "bueno tiene que darlo tu médico: es quien conoce tu historia y tu "
            "medicación. Dicho eso, en la mayoría de condiciones crónicas estables el "
            "ejercicio está indicado, empezando suave, subiendo poco a poco y evitando "
            "esfuerzos máximos. Yo puedo prepararte una sesión de intensidad baja y "
            "controlada para que la lleves a consulta.",
            "No puedo valorar tu caso clínico ni sustituir a tu médico, así que consúltalo "
            "con él antes de empezar. Como norma general conviene arrancar con "
            "intensidades bajas, progresar de forma gradual, no entrenar con síntomas "
            "agudos y parar ante dolor en el pecho, mareo o falta de aire inusual. "
            "Con esas condiciones puedo armarte una rutina prudente.",
        ],
        "adaptaciones": {
            "cognitiva": "Habla primero con tu médico. Regla simple: empieza suave, ve "
                         "despacio y para si te sientes mal. Yo te preparo una rutina "
                         "tranquila mientras tanto.",
        },
        "sugerencias": [
            "Puedo generarte una rutina de intensidad baja para empezar",
            "Cuéntame tu objetivo y la adapto a un nivel prudente",
        ],
    },
    "donde_entrenar": {
        "respuestas": [
            "Puedes entrenar en cualquier sitio: las rutinas que preparo se apoyan en una "
            "silla estable, una banda elástica y tu propio peso, así que valen igual en "
            "casa, en un parque o en un gimnasio. Al aire libre gana el ambiente y la "
            "motivación; en casa gana la constancia porque quitas la excusa del "
            "desplazamiento.",
            "El sitio importa menos de lo que parece. En casa necesitas un espacio "
            "despejado y una silla firme; en exterior, un suelo regular y sombra. Si "
            "eliges piscina, el agua reduce el impacto y es una gran opción cuando hay "
            "dolor articular.",
        ],
        "adaptaciones": {
            "visual": "En casa tienes la ventaja de que el espacio ya lo conoces y el "
                      "material está siempre en el mismo sitio. Si sales fuera, ve "
                      "acompañado la primera vez y recorre el circuito antes de usarlo. "
                      "Evita superficies irregulares como arena suelta o grava.",
            "motriz": "Comprueba antes el acceso: rampa, ancho de puerta y un suelo firme "
                      "donde la silla no se hunda. La arena de playa y la hierba alta "
                      "complican mucho la propulsión; el asfalto liso o un pabellón "
                      "cubierto funcionan mucho mejor.",
        },
        "sugerencias": [
            "Dime dónde vas a entrenar y ajusto el material de la rutina",
            "¿Quieres ver qué deportes tienen sede cerca en los eventos?",
        ],
        "accion": "deportes",
    },
    "descanso": {
        "respuestas": [
            "El descanso es parte del entrenamiento, no una pausa. Deja al menos 48 horas "
            "entre dos sesiones que trabajen el mismo grupo muscular y apunta a 7 u 8 "
            "horas de sueño, que es cuando de verdad se produce la adaptación. Si el "
            "cansancio se acumula varios días seguidos, baja el volumen antes de parar "
            "del todo.",
            "Alterna días de trabajo con días suaves: entrenar cansado no suma, resta. "
            "Las agujetas de los dos primeros días son normales al cambiar de estímulo y "
            "se alivian moviéndose suave, no con reposo absoluto. Lo que no es normal es "
            "un dolor articular agudo o que no mejora en varios días.",
        ],
        "adaptaciones": {
            "motriz": "El hombro trabaja todo el día con la propulsión, así que necesita "
                      "más margen que el resto: dos días entre sesiones exigentes de tren "
                      "superior. Si notas molestia al empujar la silla, ese día toca "
                      "movilidad y tronco, no fuerza.",
        },
        "sugerencias": [
            "Puedo repartirte la semana en días de trabajo y días suaves",
            "¿Quieres una sesión ligera de recuperación?",
        ],
    },
    "respiracion": {
        "respuestas": [
            "La regla práctica es exhalar en el esfuerzo e inhalar en la fase fácil: al "
            "empujar o levantar sueltas el aire, al bajar lo tomas. Nunca aguantes la "
            "respiración durante una serie, porque sube la tensión arterial. Si te falta "
            "el aire hasta no poder hablar, el ritmo va demasiado alto y toca bajarlo.",
            "Respira por la nariz de forma continua y suelta el aire en el momento de más "
            "esfuerzo. En trabajo de resistencia busca un ritmo en el que puedas decir "
            "una frase corta entrecortada: esa es la intensidad útil. Un buen ejercicio "
            "de base es la respiración diafragmática, inhalando 4 segundos y exhalando 6.",
        ],
        "sugerencias": [
            "Puedo incluir respiración diafragmática en tu vuelta a la calma",
            "¿Quieres una rutina de intensidad más baja?",
        ],
    },
    "objetivos": {
        "respuestas": [
            "Empezar es más fácil de lo que parece: elige un objetivo entre fuerza, "
            "resistencia, movilidad o equilibrio, reserva tres días fijos en la semana y "
            "empieza con sesiones de 20 a 30 minutos. Lo importante las primeras semanas "
            "es aprender los movimientos y no fallar días, no la intensidad.",
            "Si nunca has entrenado, arranca con 3 sesiones semanales cortas y nivel "
            "principiante. Dime qué te gustaría conseguir (moverte con más soltura, ganar "
            "fuerza, aguantar más o controlar el peso) y te preparo la primera sesión "
            "adaptada a tu perfil.",
        ],
        "adaptaciones": {
            "cognitiva": "Empezamos fácil. Elige un día y una hora fija. Haz 20 minutos. "
                         "Repite tres veces por semana. Cuando eso salga solo, subimos.",
            "intelectual": "Vamos paso a paso. Primero elegimos el día. Luego hacemos una "
                           "sesión corta. Después la repetimos igual. Nada más por ahora.",
        },
        "sugerencias": [
            "Dime tu objetivo y te genero la primera rutina",
            "¿Prefieres empezar por movilidad o por fuerza?",
        ],
        "accion": "rutina",
    },
    "progreso": {
        "respuestas": [
            "Reviso tus inscripciones, el riesgo reciente y la comparativa del mes.",
            "Te resumo cómo vas: eventos, rutinas y alertas, sin números crudos de más.",
        ],
        "sugerencias": ["¿Quieres que mire el riesgo de lesión?", "Puedo proponerte una rutina"],
        "accion": "estadisticas",
    },
    "cuenta": {
        "respuestas": [
            "Consulto tu perfil de la sesión: no necesito que me pases correo ni ID.",
            "Miro los datos que ya tienes en InkluSport y te los resumo.",
        ],
        "sugerencias": ["¿Quieres una rutina según tu perfil?", "¿Revisamos tus eventos?"],
        "accion": "perfil",
    },
    "crear_evento": {
        "respuestas": [
            "Te propongo un evento concreto con deporte, fecha y cupo para publicarlo.",
            "Armo una propuesta de evento lista para crear en la plataforma.",
        ],
        "sugerencias": ["Confirmo", "Cancelar"],
        "accion": "propuesta_evento",
    },
    "crear_deporte": {
        "respuestas": [
            "Te propongo un deporte para dar de alta en el catálogo.",
            "Preparo el alta del deporte y te pido confirmación antes de crearlo.",
        ],
        "sugerencias": ["Confirmo", "Cancelar"],
        "accion": "propuesta_deporte",
    },
    "crear_rutina": {
        "respuestas": [
            "Genero una rutina adaptada y, si confirmas, la guardo en tu catálogo de entrenador.",
            "Te dejo la rutina lista para crearla en la plataforma como borrador.",
        ],
        "sugerencias": ["Confirmo", "Cancelar"],
        "accion": "propuesta_rutina",
    },
}


# Respuestas cuando no se identifica la intención: en lugar de un texto fijo, se
# reconoce lo preguntado y se ofrece un camino concreto.
NO_ENTENDIDO = [
    "No estoy seguro de haber entendido lo que me pides. Puedo ayudarte con rutinas "
    "adaptadas, eventos disponibles, adaptaciones deporte-discapacidad y los quices de "
    "entrenador u organizador. ¿Cuál de esos temas se acerca a tu duda?",
    "Eso se me escapa un poco. Donde sí puedo ayudarte es en entrenamiento adaptado, "
    "eventos de la plataforma, adaptaciones por discapacidad y verificación de "
    "entrenadores y organizadores. ¿Reformulamos por ahí?",
    "No logro interpretar tu consulta. Dime si va por rutinas, eventos, adaptaciones o "
    "quices de aptitud y lo resolvemos.",
]

NO_ENTENDIDO_ADAPTADO = {
    "cognitiva": "No entendí bien. Elige una opción: 1) rutina de ejercicio, 2) eventos, "
                 "3) adaptaciones, 4) quiz. Escribe el número o la palabra.",
}
