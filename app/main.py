import asyncio
from contextlib import asynccontextmanager
from typing import Callable

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
from app.routers import (
    alertas,
    chat,
    competencia,
    dashboard,
    deportes,
    deteccion,
    ejercicios,
    fatiga,
    historial,
    planes,
    progreso,
    quiz,
    recomendacion,
    riesgo,
    rutinas,
    voz,
)
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


class _StripTrailingSlash:
    """Evita 307 a http://ai-service:3008/... detrás del gateway (rompe Postman)."""

    def __init__(self, app: Callable):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path") or ""
            if len(path) > 1 and path.endswith("/"):
                scope = {**scope, "path": path.rstrip("/") or "/"}
        await self.app(scope, receive, send)

    def __getattr__(self, name):
        return getattr(self.app, name)


_fastapi = FastAPI(
    title="InkluSport AI Assistant",
    description=(
        "Agente profesional de InkluSport (RF41–RF55): chat, rutinas/planes, "
        "recomendaciones, competencia, riesgo, métricas, alertas y voz. "
        "Expone /api/ai/** vía gateway en inklusport.inklusport.uk."
    ),
    version="2.3.0",
    lifespan=lifespan,
    redirect_slashes=False,
)

_fastapi.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_fastapi.include_router(chat.router, prefix="/api/ai/chat", tags=["Chatbot"])
_fastapi.include_router(rutinas.router, prefix="/api/ai/rutinas", tags=["Rutinas RF42/RF44"])
_fastapi.include_router(ejercicios.router, prefix="/api/ai/ejercicios", tags=["Ejercicios RF42"])
_fastapi.include_router(planes.router, prefix="/api/ai/planes", tags=["Planes RF44"])
_fastapi.include_router(competencia.router, prefix="/api/ai/competencia", tags=["Competencia RF53"])
_fastapi.include_router(recomendacion.router, prefix="/api/ai/recomendacion", tags=["Eventos RF49"])
_fastapi.include_router(deportes.router, prefix="/api/ai/deportes", tags=["Deportes RF50/RF51"])
_fastapi.include_router(riesgo.router, prefix="/api/ai/riesgo", tags=["Riesgo RF43"])
_fastapi.include_router(historial.router, prefix="/api/ai/historial", tags=["Historial RF47/RF48"])
_fastapi.include_router(progreso.router, prefix="/api/ai/progreso", tags=["Progreso RF48"])
_fastapi.include_router(dashboard.router, prefix="/api/ai/dashboard", tags=["Dashboard RF47"])
_fastapi.include_router(alertas.router, prefix="/api/ai/alertas", tags=["Alertas RF55"])
_fastapi.include_router(deteccion.router, prefix="/api/ai/deteccion", tags=["Detección RF52"])
_fastapi.include_router(fatiga.router, prefix="/api/ai/fatiga", tags=["Fatiga RF45"])
_fastapi.include_router(voz.router, prefix="/api/ai/voz", tags=["Voz RF46"])
_fastapi.include_router(quiz.router, prefix="/api/ai/quiz", tags=["Quices verificación"])
_fastapi.include_router(quiz.router, prefix="/api/ai", tags=["Quices (alias)"])


@_fastapi.get("/api/ai/health")
async def health_check():
    mongo = estado_mongo()
    return {
        "status": "healthy",
        "service": "ink-ms-ai-assistant",
        "version": "2.3.0",
        "auth": "Bearer JWT → GET /api/users/perfil (discapacidad y roles reales)",
        "agents": [
            "chatbot", "rutinas", "planes", "competencia", "recomendacion",
            "deportes", "riesgo", "historial", "dashboard", "alertas",
            "deteccion", "fatiga", "voz", "quiz",
        ],
        "rf_cubiertos": {
            "RF41": "omitido (requiere visión artificial)",
            "RF42": "POST /api/ai/ejercicios/adaptar (+ alias /rutinas/adaptar)",
            "RF43": "POST /api/ai/riesgo/lesiones/{userId} (+ alias /riesgo/evaluar)",
            "RF44": "POST /api/ai/rutinas/generar + POST /api/ai/planes/generar",
            "RF45": "parcial POST /api/ai/fatiga/rpe (detectar omitido; sin sensores RT)",
            "RF46": "POST /api/ai/voz/comando (+ accessibility)",
            "RF47": "GET /api/ai/dashboard/{userId} (+ historial/metricas)",
            "RF48": "GET /api/ai/progreso/comparativa/{userId} (+ historial/comparar)",
            "RF49": "GET /api/ai/recomendacion/eventos/{id}",
            "RF50": "GET /api/ai/deportes/filtrar/{id}",
            "RF51": "GET /api/ai/deportes/filtrar/{id}",
            "RF52": "POST /api/ai/deteccion/discapacidad",
            "RF53": "POST /api/ai/competencia/modo/{userId} (+ analizar)",
            "RF54": "omitido (wearables vendor)",
            "RF55": "POST /api/ai/alertas/{entrenadorId} (+ /alertas/entrenador)",
        },
        "gateway_path": "/api/ai/**",
        "public_base": "https://inklusport.inklusport.uk",
        "llm": LLMService.estado(),
        "mongodb": mongo,
        "motor_local": {
            "intenciones": len(INTENCIONES),
            "ejercicios_en_catalogo": len(CATALOGO_EJERCICIOS),
            "preguntas_organizador": len(BANCOS["ORGANIZADOR"]),
            "preguntas_entrenador": len(BANCOS["ENTRENADOR"]),
        },
    }


@_fastapi.get("/api/ai/diagnostico")
async def diagnostico():
    """Comprueba las dependencias del servicio para localizar qué falta levantar."""
    llm = LLMService()
    base_llm = llm.api_url.split("/v1/")[0] if "/v1/" in llm.api_url else llm.api_url

    servicios = {
        "auth": f"{settings.AUTH_SERVICE_URL}/api/auth/validate",
        "users": f"{settings.USERS_SERVICE_URL}/api/internal/users/roles-by-email",
        "sports": f"{settings.SPORTS_SERVICE_URL}/api/events",
        "accessibility": f"{settings.ACCESSIBILITY_SERVICE_URL}/api/voice/commands",
        "reports": f"{settings.REPORTS_SERVICE_URL}/api/dashboard",
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
            "Chat, rutinas, planes, riesgo, detección y fatiga RPE funcionan con motor "
            "local. Eventos/deportes/competencia necesitan sports; alertas necesitan "
            "accessibility; métricas enriquecen con reports si está arriba."
        ),
    }


@_fastapi.get("/")
async def root():
    return {
        "service": "ink-ms-ai-assistant",
        "docs": "/docs",
        "health": "/api/ai/health",
        "diagnostico": "/api/ai/diagnostico",
        "version": "2.3.0",
    }


# Wrapper ASGI: uvicorn carga `app` (quita "/" final sin 307 a ai-service)
app = _StripTrailingSlash(_fastapi)
