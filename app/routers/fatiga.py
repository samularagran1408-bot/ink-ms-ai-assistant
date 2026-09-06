"""RF45 light: registro de RPE post-sesión (sin sensores en tiempo real)."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agents.entrenamiento_agent import EntrenamientoAgent
from app.database.mongodb import get_db
from app.database.repositorio import COL_SESIONES_RPE
from app.deps.contexto import resolver_contexto

router = APIRouter()


class RpeRequest(BaseModel):
    """Cuerpo para registrar el esfuerzo percibido (RPE 0–10) de una sesión."""

    usuario_id: Optional[str] = None
    rpe: float = Field(..., ge=0, le=10, description="Perceived exertion 0-10")
    sesion_id: Optional[str] = None
    notas: Optional[str] = None


@router.post("/rpe")
async def registrar_rpe(
    request: RpeRequest, authorization: Optional[str] = Header(None)
):
    """RF45 — guarda el RPE post-sesión y sugiere ajuste de carga para la siguiente.

    Persiste el registro en Mongo si hay base disponible. RPE ≥ 8 sugiere bajar
    volumen; ≤ 3 permite progresar ligeramente.
    """
    ctx = await resolver_contexto(authorization, request.usuario_id, require_auth=True)

    sugerencia = "Mantén el plan."
    if request.rpe >= 8:
        sugerencia = "Reduce volumen un 20% o añade un día de movilidad suave."
    elif request.rpe >= 6:
        sugerencia = "Mantén series pero alarga descansos 15–30 s."
    elif request.rpe <= 3:
        sugerencia = "Puedes progresar ligeramente en la próxima sesión."

    doc = {
        "usuario_id": ctx.id,
        "email": ctx.email,
        "rpe": request.rpe,
        "sesion_id": request.sesion_id,
        "notas": request.notas,
        "sugerencia": sugerencia,
        "discapacidad": ctx.disability,
        "fecha": datetime.now(timezone.utc).isoformat(),
        "rf": "RF45",
    }
    db = get_db()
    if db is not None:
        try:
            await db[COL_SESIONES_RPE].insert_one(dict(doc))
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"No se pudo guardar RPE: {exc}")

    ajuste = None
    try:
        ajuste = await EntrenamientoAgent().aplicar_feedback_rpe(
            ctx.id, request.rpe, ctx.disability or "general", ctx.authorization
        )
        if ajuste.get("plan_ajuste"):
            sugerencia = ajuste["plan_ajuste"].get("detalle") or sugerencia
    except Exception as exc:
        print(f"No se pudo ajustar el plan por RPE: {exc}")

    return {
        "registrado": True,
        "usuario_id": ctx.id,
        "rpe": request.rpe,
        "sugerencia_siguiente_sesion": sugerencia,
        "plan_ajuste": (ajuste or {}).get("plan_ajuste"),
        "modo": "rpe_post_sesion",
        "rf": "RF45",
        "caso_prueba": "CP17-HU43" if request.rpe >= 8 else "CP18-HU43",
    }
