"""RF45 light: registro de RPE post-sesión (sin sensores en tiempo real)."""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.database.mongodb import get_db
from app.database.repositorio import COL_SESIONES_RPE
from app.deps.contexto import resolver_contexto

router = APIRouter()


class RpeRequest(BaseModel):
    usuario_id: Optional[str] = None
    rpe: float = Field(..., ge=0, le=10, description="Perceived exertion 0-10")
    sesion_id: Optional[str] = None
    notas: Optional[str] = None


@router.post("/rpe")
async def registrar_rpe(
    request: RpeRequest, authorization: Optional[str] = Header(None)
):
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

    return {
        "registrado": True,
        "usuario_id": ctx.id,
        "rpe": request.rpe,
        "sugerencia_siguiente_sesion": sugerencia,
        "modo": "rpe_post_sesion",
        "rf": "RF45",
    }
