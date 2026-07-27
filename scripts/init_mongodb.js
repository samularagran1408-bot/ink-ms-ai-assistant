db = db.getSiblingDB("inclusport_training_ia");

db.createCollection("conversaciones_chatbot");
db.createCollection("entrenamiento_chatbot");

db.entrenamiento_chatbot.deleteMany({});
db.entrenamiento_chatbot.insertMany([
    {
        pregunta: "Hola",
        respuesta_base: "¡Hola! Soy el asistente virtual de InkluSport. ¿En qué puedo ayudarte?",
        intencion: "saludo",
        palabras_clave: ["hola", "buenos", "saludo", "hey"],
        respuesta_adaptada: {
            visual: "Hola. Soy el asistente de InkluSport. ¿Cómo puedo ayudarte?",
            auditiva: "¡Hola! Soy tu asistente. ¿Qué necesitas?",
            cognitiva: "Hola. Soy tu asistente. Dime cómo te ayudo.",
            motriz: "Hola. Soy el asistente de InkluSport. ¿En qué te ayudo hoy?"
        },
        activo: true
    },
    {
        pregunta: "Rutinas",
        respuesta_base: "Puedo generar rutinas personalizadas. Usa el agente de rutinas o dime tu objetivo y tipo de discapacidad.",
        intencion: "rutinas",
        palabras_clave: ["rutina", "ejercicio", "entrenar", "entrenamiento"],
        respuesta_adaptada: {
            visual: "Puedo crear una rutina con instrucciones claras paso a paso. Indica tu objetivo.",
            auditiva: "Puedo generar una rutina por escrito con series y repeticiones. Indica tu objetivo.",
            cognitiva: "Puedo armarte una rutina simple. Dime: 1) objetivo 2) tipo de ejercicio.",
            motriz: "Puedo proponer ejercicios adaptados a movilidad reducida. ¿Cuál es tu objetivo?"
        },
        activo: true
    },
    {
        pregunta: "Eventos",
        respuesta_base: "Puedo recomendarte eventos según tu perfil y discapacidad. Consulta el agente de recomendaciones.",
        intencion: "eventos",
        palabras_clave: ["evento", "eventos", "competencia", "torneo", "inscripcion"],
        respuesta_adaptada: {
            visual: "Puedo sugerirte eventos inclusivos según tu perfil. ¿Quieres recomendaciones?",
            auditiva: "Puedo listar eventos recomendados por escrito según tu discapacidad.",
            cognitiva: "Puedo recomendarte eventos. Pregunta por recomendaciones de eventos.",
            motriz: "Puedo buscar eventos accesibles y adaptados. ¿Quieres recomendaciones?"
        },
        activo: true
    }
]);

print("Base de datos inicializada");
