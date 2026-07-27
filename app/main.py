from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.database.mongodb import connect_to_mongo, close_mongo_connection
from app.routers import chat, rutinas, competencia, recomendacion, quiz


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await connect_to_mongo()
        print("Conectado a MongoDB")
    except Exception as e:
        print(f"MongoDB no disponible (continuando sin KB): {e}")
    yield
    await close_mongo_connection()
    print("Desconectado de MongoDB")


app = FastAPI(
    title="InkluSport AI Assistant",
    description=(
        "Agente de IA para deporte inclusivo: chat, rutinas, competencia, "
        "recomendaciones y quices de aptitud (organizador/entrenador)."
    ),
    version="1.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router, prefix="/api/ai/chat", tags=["Chatbot"])
app.include_router(rutinas.router, prefix="/api/ai/rutinas", tags=["Rutinas"])
app.include_router(competencia.router, prefix="/api/ai/competencia", tags=["Competencia"])
app.include_router(recomendacion.router, prefix="/api/ai/recomendacion", tags=["Recomendaciones"])
app.include_router(quiz.router, prefix="/api/ai/quiz", tags=["Quices verificación"])
# Alias: Postman a veces usa /api/ai/organizer|trainer/... (sin /quiz)
app.include_router(quiz.router, prefix="/api/ai", tags=["Quices (alias)"])


@app.get("/api/ai/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "ink-ms-ai-assistant",
        "llm": "Grok",
        "agents": ["chatbot", "rutinas", "competencia", "recomendacion", "quiz"],
        "quiz_endpoints": [
            "POST /api/ai/quiz/organizer/generar",
            "POST /api/ai/quiz/trainer/generar",
            "POST /api/ai/organizer/generar",
            "POST /api/ai/trainer/generar",
        ],
    }


@app.get("/")
async def root():
    return {
        "service": "ink-ms-ai-assistant",
        "docs": "/docs",
        "health": "/api/ai/health",
    }
