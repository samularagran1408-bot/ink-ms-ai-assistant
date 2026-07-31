from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.rutinas_agent import RutinasAgent
from app.data.ejercicios import CATALOGO_EJERCICIOS, PAUTAS_DISCAPACIDAD
from app.deps.contexto import discapacidad_efectiva, resolver_contexto
from app.motor.rutinas import adaptacion_de, generar_rutina
from app.nlp.discapacidad import canonizar

router = APIRouter()
agent = RutinasAgent()


class RutinaRequest(BaseModel):
    usuario_id: Optional[str] = Field(
        default=None,
        description="Opcional con token. Se usa el perfil autenticado.",
    )
    tipo: str = Field(default="general", description="fuerza | resistencia | movilidad | en silla | piscina...")
    objetivo: str = Field(default="general", description="Objetivo en texto libre")
    discapacidad: Optional[str] = Field(
        default=None,
        description="Sólo ADMIN/ENTRENADOR pueden forzarla; si no, se toma del perfil del token",
    )
    nivel: Optional[str] = Field(default=None, description="principiante | intermedio | avanzado")
    duracion_minutos: int = Field(default=35, ge=10, le=90)
    semilla: Optional[int] = None


class AdaptarRequest(BaseModel):
    ejercicio_id: Optional[str] = None
    nombre_ejercicio: Optional[str] = None
    discapacidad: Optional[str] = None
    limitacion: Optional[str] = None
    nivel: Optional[str] = "principiante"


@router.post("/generar")
async def generar_rutina_endpoint(
    request: RutinaRequest, authorization: Optional[str] = Header(None)
):
    try:
        ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)
        discapacidad = discapacidad_efectiva(
            ctx, request.discapacidad, permitir_override=True
        )
        return await agent.generar_rutina(
            usuario_id=ctx.id,
            tipo=request.tipo,
            objetivo=request.objetivo,
            discapacidad=discapacidad,
            nivel=request.nivel,
            duracion_minutos=request.duracion_minutos,
            semilla=request.semilla,
            authorization=ctx.authorization,
            perfil=ctx.perfil,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error generando la rutina: {exc}")


@router.post("/adaptar")
async def adaptar_ejercicio(
    request: AdaptarRequest, authorization: Optional[str] = Header(None)
):
    try:
        ctx = await resolver_contexto(authorization, require_auth=True)
        discapacidad = discapacidad_efectiva(
            ctx, request.discapacidad, permitir_override=True
        )
    except HTTPException:
        raise

    ejercicio = None
    if request.ejercicio_id:
        ejercicio = next((e for e in CATALOGO_EJERCICIOS if e["id"] == request.ejercicio_id), None)
    if ejercicio is None and request.nombre_ejercicio:
        nombre = request.nombre_ejercicio.lower()
        ejercicio = next(
            (e for e in CATALOGO_EJERCICIOS if nombre in e["nombre"].lower()),
            None,
        )
    if ejercicio is None:
        alternativa = generar_rutina(
            discapacidad=discapacidad,
            objetivo_texto=request.limitacion or "rehabilitacion",
            nivel=request.nivel,
            duracion_minutos=20,
            semilla=7,
        )
        return {
            "encontrado": False,
            "mensaje": "No se encontró el ejercicio; aquí va una alternativa segura.",
            "alternativa": alternativa["ejercicios"][:3] if alternativa.get("ejercicios") else [],
            "pauta": PAUTAS_DISCAPACIDAD.get(discapacidad, {}).get("pauta"),
            "discapacidad": discapacidad,
            "usuario_id": ctx.id,
            "rf": "RF42",
        }

    adaptado = {
        "ejercicio_original": {
            "id": ejercicio["id"],
            "nombre": ejercicio["nombre"],
            "instrucciones": ejercicio["instrucciones"],
        },
        "adaptacion": adaptacion_de(ejercicio, discapacidad),
        "modificaciones": [
            adaptacion_de(ejercicio, discapacidad),
            PAUTAS_DISCAPACIDAD.get(discapacidad, PAUTAS_DISCAPACIDAD["general"])["pauta"],
        ],
        "discapacidad": discapacidad,
        "usuario_id": ctx.id,
        "rf": "RF42",
    }
    if request.limitacion:
        lim = request.limitacion.lower()
        if "dolor" in lim or "lesion" in lim:
            adaptado["modificaciones"].append(
                "Reduce el rango al tramo libre de dolor y baja 1 serie."
            )
        if "fatiga" in lim or "cansancio" in lim:
            adaptado["modificaciones"].append(
                "Aumenta el descanso un 50% y elimina la serie más exigente."
            )
        if "material" in lim or "sin " in lim:
            adaptado["modificaciones"].append(
                "Sustituye el material por peso corporal o apoyo de silla/pared."
            )
    return adaptado
