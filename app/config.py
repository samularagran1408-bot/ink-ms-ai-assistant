import os

from dotenv import load_dotenv

load_dotenv()


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.getenv(nombre)
    if valor is None or not valor.strip():
        return defecto
    return valor.strip().lower() in ("1", "true", "yes", "y", "si", "sí", "on")


def _int(nombre: str, defecto: int) -> int:
    try:
        return int(os.getenv(nombre, "").strip() or defecto)
    except ValueError:
        return defecto


def _primero(*nombres: str, defecto: str = "") -> str:
    for nombre in nombres:
        valor = os.getenv(nombre)
        if valor and valor.strip():
            return valor.strip()
    return defecto


class Settings:
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

    # Tras un fallo del proveedor se deja de intentar durante este tiempo, para
    # que el chat no espere el timeout completo en cada petición.
    LLM_COOLDOWN_SEGUNDOS = _int("LLM_COOLDOWN_SEGUNDOS", 60)

    # Compatibilidad con el nombre anterior de las variables
    GROK_API_KEY = LLM_API_KEY
    GROK_MODEL = LLM_MODEL
    GROK_API_URL = LLM_API_URL


settings = Settings()
