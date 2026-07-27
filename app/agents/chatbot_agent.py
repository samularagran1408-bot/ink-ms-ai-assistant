from app.services.grok_service import GrokService
from app.database.mongodb import get_db
from datetime import datetime


FALLBACK_RESPUESTAS = {
    "visual": "Hola. Soy el asistente de InkluSport. Puedo ayudarte con rutinas adaptadas, eventos y consejos de deporte inclusivo. ¿Qué necesitas?",
    "auditiva": "Hola. Soy tu asistente de InkluSport. Escribe tu consulta sobre deporte inclusivo, rutinas o eventos.",
    "cognitiva": "Hola. Soy tu asistente. Puedo ayudarte con: 1) rutinas 2) eventos 3) consejos. Dime qué quieres.",
    "motriz": "Hola. Soy el asistente de InkluSport. Te ayudo con ejercicios adaptados, eventos accesibles y recomendaciones.",
    "general": "¡Hola! Soy el asistente virtual de InkluSport. ¿En qué puedo ayudarte con deporte inclusivo?",
}


class ChatbotAgent:
    def __init__(self):
        self.grok = GrokService()

    async def procesar_mensaje(self, usuario_id: str, mensaje: str, discapacidad: str):
        db = get_db()
        entrenamiento = None
        discapacidad = (discapacidad or "general").lower()

        if db is not None:
            try:
                entrenamiento = await db.entrenamiento_chatbot.find_one({
                    "activo": True,
                    "palabras_clave": {"$in": mensaje.lower().split()},
                })
            except Exception as e:
                print(f"Error consultando base de conocimiento: {e}")

        if entrenamiento:
            respuestas = entrenamiento.get("respuesta_adaptada") or {}
            respuesta = respuestas.get(discapacidad) or entrenamiento.get("respuesta_base", "")
            intencion = entrenamiento.get("intencion", "conocimiento")
            adaptada = True
        else:
            prompt = (
                f"Usuario pregunta: {mensaje}\n"
                f"Discapacidad: {discapacidad}\n"
                "Responde de manera clara, profesional y adaptada al deporte inclusivo."
            )
            try:
                respuesta = await self.grok.chat(prompt, discapacidad)
                intencion = "general"
                adaptada = False
            except Exception as e:
                print(f"Grok no disponible, usando fallback: {e}")
                respuesta = FALLBACK_RESPUESTAS.get(discapacidad, FALLBACK_RESPUESTAS["general"])
                intencion = "fallback"
                adaptada = True

        if db is not None:
            try:
                await db.conversaciones_chatbot.update_one(
                    {"usuario_id": usuario_id, "estado": "activa"},
                    {
                        "$push": {"mensajes": {"$each": [
                            {"mensaje": mensaje, "remitente": "usuario", "fecha": datetime.utcnow()},
                            {
                                "mensaje": respuesta,
                                "remitente": "asistente",
                                "intencion": intencion,
                                "fecha": datetime.utcnow(),
                            },
                        ]}},
                        "$set": {"ultima_interaccion": datetime.utcnow()},
                    },
                    upsert=True,
                )
            except Exception as e:
                print(f"Error guardando conversación: {e}")

        return {
            "respuesta": respuesta,
            "intencion": intencion,
            "adaptada": adaptada,
        }
