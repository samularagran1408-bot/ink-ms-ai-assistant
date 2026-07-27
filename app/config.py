import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # Defaults pensados para desarrollo local; Docker los sobrescribe
    MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://admin:admin123@localhost:27017/")
    MONGODB_DB = os.getenv("MONGODB_DB", "inclusport_training_ia")

    AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:3001")
    USERS_SERVICE_URL = os.getenv("USERS_SERVICE_URL", "http://localhost:3002")
    SPORTS_SERVICE_URL = os.getenv("SPORTS_SERVICE_URL", "http://localhost:3003")

    GROK_API_KEY = os.getenv("GROK_API_KEY", "")
    GROK_MODEL = os.getenv("GROK_MODEL", "grok-4.5")
    GROK_API_URL = os.getenv("GROK_API_URL", "https://api.x.ai/v1/chat/completions")


settings = Settings()
