from motor.motor_asyncio import AsyncIOMotorClient
from app.config import settings

client = None
db = None


async def connect_to_mongo():
    global client, db
    client = AsyncIOMotorClient(settings.MONGODB_URI, serverSelectionTimeoutMS=5000)
    # Fuerza verificación de conexión
    await client.admin.command("ping")
    db = client[settings.MONGODB_DB]


async def close_mongo_connection():
    global client, db
    if client:
        client.close()
    client = None
    db = None


def get_db():
    return db
