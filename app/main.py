import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.data.ejercicios import CATALOGO_EJERCICIOS
from app.data.quiz_banco import BANCOS
from app.database.mongodb import (
    close_mongo_connection,
    connect_to_mongo,
    estado as estado_mongo,
    ocultar_credenciales,
)
from app.database.semilla import sembrar_catalogos
from app.nlp.intenciones import INTENCIONES
from app.routers import chat, competencia, quiz, recomendacion, rutinas
from app.services.llm_service import LLMService


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        uri = await connect_to_mongo()
        print(f"Conectado a MongoDB en {ocultar_credenciales(uri)}")
        resumen = await sembrar_catalogos()
        print(f"Catálogos sembrados: {resumen}")
    except Exception as exc:
        print(f"MongoDB no disponible, se usarán los catálogos del código: {exc}")

    estado_llm = LLMService.estado()
    print(
        f"LLM: proveedor={estado_llm['proveedor']} modelo={estado_llm['modelo']} "
        f"modo={estado_llm['modo']}"
    )

    # Se precalienta en segundo plano: cargar el modelo en RAM tarda, y bloquear
    # el arranque dejaría el health check sin responder mientras tanto.
    calentamiento = asyncio.create_task(_precalentar_llm())

    yield

    calentamiento.cancel()
    await close_mongo_connection()
    print("Desconectado de MongoDB")


async def _precalentar_llm() -> None:
    llm = LLMService()
    if not llm.is_configured:
        return
    print(f"Precalentando el modelo {llm.model}...")
    if await llm.precalentar():
        print(f"Modelo {llm.model} listo y cargado en memoria")
    else:
        print("El modelo no respondió; el asistente sigue operativo con el motor local")


app = FastAPI(
    title="InkluSport AI Assistant",
    description=(
        "Agente de IA para deporte inclusivo: chat con detección de intenciones, "
        "rutinas adaptadas, análisis de competencia, recomendación de eventos y "
        "quices de aptitud para entrenadores y organizadores. Funciona con o sin "
        "proveedor de LLM configurado."
    ),
    version="2.0.0",
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
# Alias sin /quiz, usado por algunas colecciones de Postman
app.include_router(quiz.router, prefix="/api/ai", tags=["Quices (alias)"])


@app.get("/api/ai/health")
async def health_check():
    mongo = estado_mongo()
    return {
        "status": "healthy",
        "service": "ink-ms-ai-assistant",
        "version": "2.0.0",
        "agents": ["chatbot", "rutinas", "competencia", "recomendacion", "quiz"],
        "llm": LLMService.estado(),
        "mongodb": mongo,
        "motor_local": {
            "intenciones": len(INTENCIONES),
            "ejercicios_en_catalogo": len(CATALOGO_EJERCICIOS),
            "preguntas_organizador": len(BANCOS["ORGANIZADOR"]),
            "preguntas_entrenador": len(BANCOS["ENTRENADOR"]),
        },
    }


@app.get("/api/ai/diagnostico")
async def diagnostico():
    """Comprueba las dependencias del servicio para localizar qué falta levantar."""
    llm = LLMService()
    base_llm = llm.api_url.split("/v1/")[0] if "/v1/" in llm.api_url else llm.api_url

    servicios = {
        "auth": f"{settings.AUTH_SERVICE_URL}/api/auth/validate",
        # Ruta interna que este servicio realmente consume: sin el parámetro
        # obligatorio devuelve 400, lo que ya confirma que la app responde.
        # (/actuator/health no está expuesto en users y daba un 404 confuso.)
        "users": f"{settings.USERS_SERVICE_URL}/api/internal/users/roles-by-email",
        "sports": f"{settings.SPORTS_SERVICE_URL}/api/events",
    }
    if base_llm and not llm.requiere_clave:
        servicios["ollama"] = f"{base_llm}/api/tags"

    resultados = {}
    async with httpx.AsyncClient(timeout=5.0) as client:
        for nombre, url in servicios.items():
            try:
                respuesta = await client.get(url)
                resultados[nombre] = {
                    "alcanzable": True,
                    "http": respuesta.status_code,
                    "url": url,
                }
            except Exception as exc:
                resultados[nombre] = {
                    "alcanzable": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "url": url,
                }

    if resultados.get("ollama", {}).get("http") == 200:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                datos = (await client.get(servicios["ollama"])).json()
            instalados = [m.get("name") for m in datos.get("models", [])]
            resultados["ollama"]["modelos_instalados"] = instalados
            resultados["ollama"]["modelo_configurado_disponible"] = any(
                str(m).startswith(llm.model.split(":")[0]) for m in instalados
            )
        except Exception:
            resultados["ollama"]["modelos_instalados"] = None

    eventos = resultados.get("sports", {})
    if eventos.get("http") == 200:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                datos = (await client.get(servicios["sports"])).json()
            eventos["eventos_publicados"] = len(datos) if isinstance(datos, list) else 0
        except Exception:
            eventos["eventos_publicados"] = None

    return {
        "mongodb": estado_mongo(),
        "llm": LLMService.estado(),
        "servicios": resultados,
        "nota": (
            "El chat, las rutinas y los quices funcionan sin LLM y sin los otros "
            "microservicios. La recomendación de eventos necesita ink-ms-sports con "
            "eventos publicados, y las preguntas abiertas del chat necesitan el LLM."
        ),
    }


@app.get("/")
async def root():
    return {
        "service": "ink-ms-ai-assistant",
        "docs": "/docs",
        "health": "/api/ai/health",
        "diagnostico": "/api/ai/diagnostico",
    }
