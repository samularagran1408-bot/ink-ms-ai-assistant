"""Configuración del servicio leída desde variables de entorno."""

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(nombre: str, defecto: bool) -> bool:
    """Interpreta una variable de entorno como booleano.

    Acepta 1, true, yes, y, si, sí y on (sin distinguir mayúsculas).
    Si falta o está vacía, devuelve `defecto`.
    """
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    return valor.strip().lower() in ("1", "true", "yes", "y", "si", "sí", "on")


def _int(nombre: str, defecto: int) -> int:
    """Lee una variable de entorno como entero; si no es un número válido, usa `defecto`."""
    try:
        return int(os.getenv(nombre, "").strip() or defecto)
    except ValueError:
        return defecto


def _primero(*nombres: str, defecto: str = "") -> str:
    """Devuelve el primer valor de entorno no vacío entre `nombres`, o `defecto`."""
    for nombre in nombres:
        valor = os.getenv(nombre)
        if valor and valor.strip():
            return valor.strip()
    return defecto


class Settings:
    """Ajustes de MongoDB, microservicios, LLM, historial de chat y retención.

    Los valores por defecto sirven para desarrollo local; Docker o `.env`
    los sobrescriben.
    """
    # Defaults pensados para desarrollo local; Docker los sobrescribe
    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017/")
    MONGODB_DB = os.getenv("MONGODB_DB", "inclusport_training_ia")

    # Si la URI principal falla (p. ej. hostname de Docker fuera de Docker, o
    # credenciales en una instancia sin autenticación) se intentan estas.
    # El 27018 es el MongoDB de Docker visto desde el host.
    MONGODB_URI_ALTERNATIVAS = [
        u.strip()
        for u in os.getenv(
            "MONGODB_URI_ALTERNATIVAS",
            "mongodb://localhost:27017/,"
            "mongodb://admin:admin123@localhost:27018/,"
            "mongodb://admin:admin123@localhost:27017/",
        ).split(",")
        if u.strip()
    ]

    AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:3001")
    USERS_SERVICE_URL = os.getenv("USERS_SERVICE_URL", "http://localhost:3002")
    SPORTS_SERVICE_URL = os.getenv("SPORTS_SERVICE_URL", "http://localhost:3003")
    ACCESSIBILITY_SERVICE_URL = os.getenv(
        "ACCESSIBILITY_SERVICE_URL", "http://localhost:3004"
    )
    REPORTS_SERVICE_URL = os.getenv("REPORTS_SERVICE_URL", "http://localhost:3006")

    # Servidor MCP (ink-mcp-inklusport). El chat actúa como cliente.
    MCP_ENABLED = _bool("MCP_ENABLED", True)
    MCP_URL = os.getenv("MCP_URL", "http://127.0.0.1:8000/mcp")

    # LLM opcional. El servicio funciona completo sin él (motor local);
    # cuando está disponible se usa para enriquecer las respuestas.
    LLM_ENABLED = _bool("LLM_ENABLED", True)

    # auto | ollama | xai | groq | openai. En "auto" el proveedor se deduce del
    # prefijo de la clave, o se asume Ollama cuando la URL apunta a un servidor local.
    LLM_PROVIDER = _primero("LLM_PROVIDER", defecto="auto").lower()

    LLM_API_KEY = _primero("LLM_API_KEY", "GROK_API_KEY")
    LLM_MODEL = _primero("LLM_MODEL", "GROK_MODEL", defecto="")
    LLM_API_URL = _primero("LLM_API_URL", "GROK_API_URL", defecto="")

    # La inferencia local en CPU es lenta la primera vez (carga del modelo en RAM),
    # así que el timeout por defecto es holgado.
    LLM_TIMEOUT = _int("LLM_TIMEOUT", 120)
    LLM_MAX_TOKENS = _int("LLM_MAX_TOKENS", 800)

    # Kickoff CrewAI: varias iteraciones de LLM + tools. El front debe esperar esto.
    CREW_TIMEOUT_SEGUNDOS = _int("CREW_TIMEOUT_SEGUNDOS", 180)

    # Las mutaciones del crew son SIEMPRE sandbox. CREW_WRITE_MODE=mcp se ignora
    # (ver app.crew.politica). El chat sigue escribiendo vía MCP con Confirmo.

    # Tras un fallo del proveedor se deja de intentar durante este tiempo, para
    # que el chat no espere el timeout completo en cada petición.
    LLM_COOLDOWN_SEGUNDOS = _int("LLM_COOLDOWN_SEGUNDOS", 60)

    # Si true, el LLM reescribe también respuestas de intenciones ya resueltas
    # por el motor local (más tokens). Por defecto solo pulimos casos difíciles.
    LLM_SINTESIS_INTENIONES_CONOCIDAS = _bool("LLM_SINTESIS_INTENIONES_CONOCIDAS", False)

    # Tool-calling estilo OpenAI/MCP: el LLM elige tools; si falla → motor local.
    LLM_TOOL_CALLING_ENABLED = _bool("LLM_TOOL_CALLING_ENABLED", True)
    LLM_TOOL_MAX_RONDAS = _int("LLM_TOOL_MAX_RONDAS", 3)

    # Historial de chat: anti-basura en Mongo y en el prompt del LLM
    CHAT_MAX_MENSAJES_POR_CONVERSACION = _int("CHAT_MAX_MENSAJES_POR_CONVERSACION", 40)
    CHAT_MAX_CONVERSACIONES_POR_USUARIO = _int("CHAT_MAX_CONVERSACIONES_POR_USUARIO", 10)
    CHAT_HISTORIAL_LLM_TURNOS = _int("CHAT_HISTORIAL_LLM_TURNOS", 6)
    CHAT_MAX_CHARS_MENSAJE = _int("CHAT_MAX_CHARS_MENSAJE", 2000)
    CHAT_RESUMEN_MAX_CHARS = _int("CHAT_RESUMEN_MAX_CHARS", 800)

    # Retención de datos efímeros (no toca catálogos ni modo competencia)
    RETENCION_CHAT_HORAS = _int("RETENCION_CHAT_HORAS", 4)
    RETENCION_QUIZ_ACTIVO_HORAS = _int("RETENCION_QUIZ_ACTIVO_HORAS", 4)
    RETENCION_QUIZ_EVALUADO_HORAS = _int("RETENCION_QUIZ_EVALUADO_HORAS", 2)
    RETENCION_ALERTAS_HORAS = _int("RETENCION_ALERTAS_HORAS", 4)
    RETENCION_PLANES_HORAS = _int("RETENCION_PLANES_HORAS", 24)
    RETENCION_RPE_HORAS = _int("RETENCION_RPE_HORAS", 24)
    RETENCION_INTERVALO_SEGUNDOS = _int("RETENCION_INTERVALO_SEGUNDOS", 900)

    # Compatibilidad con el nombre anterior de las variables
    GROK_API_KEY = LLM_API_KEY
    GROK_MODEL = LLM_MODEL
    GROK_API_URL = LLM_API_URL


settings = Settings()
