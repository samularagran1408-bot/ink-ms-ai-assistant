"""Planes de entrenamiento multi-sesión (RF44) con progresión semanal."""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from app.data.ejercicios import CATALOGO_EJERCICIOS
from app.database.mongodb import get_db
from app.database.repositorio import COL_PLANES, obtener_catalogo_ejercicios
from app.motor.rutinas import generar_rutina, interpretar_objetivo
from app.nlp.discapacidad import canonizar
from app.services.user_service import UserService

NIVELES = ("principiante", "intermedio", "avanzado")

# Variación semanal/diaria afín al objetivo del usuario (no forzar "fuerza")
_VARIACION_POR_OBJETIVO = {
    "fuerza": ("fuerza", "potencia", "core"),
    "resistencia": ("resistencia", "velocidad", "movilidad"),
    "movilidad": ("movilidad", "flexibilidad", "equilibrio"),
    "flexibilidad": ("flexibilidad", "movilidad", "equilibrio"),
    "equilibrio": ("equilibrio", "core", "agilidad"),
    "rehabilitacion": ("rehabilitacion", "movilidad", "flexibilidad"),
    "peso": ("peso", "resistencia", "fuerza"),
    "reflejos": ("reflejos", "agilidad", "coordinacion"),
    "velocidad": ("velocidad", "agilidad", "potencia"),
    "agilidad": ("agilidad", "reflejos", "velocidad"),
    "potencia": ("potencia", "fuerza", "velocidad"),
    "coordinacion": ("coordinacion", "reflejos", "equilibrio"),
    "core": ("core", "equilibrio", "fuerza"),
    "general": ("movilidad", "equilibrio", "resistencia"),
}


class PlanesAgent:
    """Arma planes multi-sesión con progresión semanal y los persiste (RF44)."""

    def __init__(self):
        """Inicializa el cliente de users (el catálogo arma las sesiones)."""
        self.user_service = UserService()

    async def generar_plan(
        self,
        usuario_id: str,
        objetivo: str = "general",
        discapacidad: Optional[str] = None,
        nivel: Optional[str] = None,
        semanas: int = 4,
        sesiones_por_semana: int = 3,
        duracion_minutos: int = 35,
        authorization: Optional[str] = None,
        perfil: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Genera un plan de 1–8 semanas con sesiones variadas según el objetivo.

        Sube el nivel a mitad de plan si hay margen, rota el enfoque diario afín
        al objetivo y guarda el resultado en Mongo. El resumen es local: no espera al LLM.
        """
        semanas = max(1, min(semanas, 8))
        sesiones_por_semana = max(2, min(sesiones_por_semana, 5))

        if perfil:
            catalogo = await self._catalogo_rapido()
        else:
            perfil, catalogo = await asyncio.gather(
                self._perfil_rapido(usuario_id, authorization),
                self._catalogo_rapido(),
            )
        discapacidad_final = canonizar(discapacidad or (perfil or {}).get("disability") or "general")
        nivel_base = nivel or "principiante"
        if nivel_base not in NIVELES:
            nivel_base = "principiante"
        nombre = (perfil or {}).get("fullName") or "Usuario"
        catalogo = catalogo or CATALOGO_EJERCICIOS

        sesiones: list[dict[str, Any]] = []
        idx_nivel = NIVELES.index(nivel_base)
        objetivo_clave = interpretar_objetivo(objetivo)
        variacion = _VARIACION_POR_OBJETIVO.get(
            objetivo_clave, _VARIACION_POR_OBJETIVO["general"]
        )
        ya_usados: set[str] = set()
        for semana in range(1, semanas + 1):
            # Progresión suave: sube nivel a mitad de plan si hay margen.
            nivel_semana = NIVELES[min(idx_nivel + (1 if semana > semanas // 2 else 0), 2)]
            for dia in range(1, sesiones_por_semana + 1):
                semilla = hash(f"{usuario_id}-{semana}-{dia}-{objetivo}") % 10_000_000
                enfoque = variacion[(dia - 1) % len(variacion)]
                # El texto del usuario manda siempre; el enfoque del día solo aporta variedad
                rutina = generar_rutina(
                    discapacidad=discapacidad_final,
                    objetivo_texto=objetivo or enfoque,
                    tipo_texto=enfoque,
                    nivel=nivel_semana,
                    duracion_minutos=duracion_minutos + (5 if semana > 2 else 0),
                    semilla=semilla,
                    catalogo=catalogo,
                    excluir_ids=set(ya_usados),
                )
                ids_sesion = [
                    str(e.get("id"))
                    for e in (rutina.get("ejercicios") or [])
                    if e.get("id")
                ]
                # Si el catálogo no da para más unicidad, reintenta solo con unicidad intra-sesión.
                if rutina.get("total_ejercicios", 0) < 4 and ya_usados:
                    rutina = generar_rutina(
                        discapacidad=discapacidad_final,
                        objetivo_texto=objetivo or enfoque,
                        tipo_texto=enfoque,
                        nivel=nivel_semana,
                        duracion_minutos=duracion_minutos + (5 if semana > 2 else 0),
                        semilla=semilla,
                        catalogo=catalogo,
                    )
                    ids_sesion = [
                        str(e.get("id"))
                        for e in (rutina.get("ejercicios") or [])
                        if e.get("id")
                    ]
                ya_usados.update(ids_sesion)
                ya_usados.update(
                    (e.get("nombre") or "").strip().lower()
                    for e in (rutina.get("ejercicios") or [])
                    if e.get("nombre")
                )
                ejercicios = [
                    {
                        "nombre": e.get("nombre"),
                        "series": e.get("series"),
                        "repeticiones": e.get("repeticiones"),
                        "fase": e.get("fase"),
                        "instrucciones": e.get("instrucciones"),
                    }
                    for e in (rutina.get("ejercicios") or [])
                    if e.get("nombre")
                ]
                sesiones.append({
                    "id": f"s{semana}d{dia}",
                    "semana": semana,
                    "sesion": dia,
                    "enfoque": enfoque,
                    "nivel": nivel_semana,
                    "nombre": rutina["nombre"],
                    "objetivo_clave": rutina.get("objetivo_clave"),
                    "duracion_estimada_minutos": rutina["duracion_estimada_minutos"],
                    "total_ejercicios": rutina["total_ejercicios"],
                    "ejercicios": ejercicios,
                    "bloques": rutina["bloques"],
                    "material_necesario": rutina["material_necesario"],
                    "recomendaciones": rutina["recomendaciones"][:3],
                })

        plan_id = str(uuid.uuid4())
        plan = {
            "plan_id": plan_id,
            "usuario": {
                "id": (perfil or {}).get("id") or usuario_id,
                "fullName": nombre,
                "disability": discapacidad_final,
            },
            "objetivo": objetivo,
            "nivel_inicial": nivel_base,
            "semanas": semanas,
            "sesiones_por_semana": sesiones_por_semana,
            "total_sesiones": len(sesiones),
            "sesiones": sesiones,
            "progresion": (
                f"El plan empieza en {nivel_base} y progresa en volumen/nivel "
                f"a partir de la semana {max(2, semanas // 2 + 1)}."
            ),
            "creado_en": datetime.now(timezone.utc).isoformat(),
            "fuente": "motor_local",
            "rf": "RF44",
        }
        plan["resumen"] = self._resumen(plan, nombre)
        await self._guardar(plan, bloquear=False)
        return plan

    async def obtener_plan(self, plan_id: str) -> Optional[dict[str, Any]]:
        """Recupera un plan persistido por `plan_id`. None si no hay DB o no existe."""
        db = get_db()
        if db is None:
            return None
        return await db[COL_PLANES].find_one({"plan_id": plan_id}, {"_id": 0})

    async def listar_planes(self, usuario_id: str, limite: int = 8) -> list[dict[str, Any]]:
        """Últimos planes del atleta, más reciente primero. Vacío si no hay DB."""
        db = get_db()
        if db is None:
            return []
        try:
            cursor = (
                db[COL_PLANES]
                .find({"usuario.id": usuario_id}, {"_id": 0})
                .sort("creado_en", -1)
                .limit(max(1, min(limite, 20)))
            )
            return await cursor.to_list(length=max(1, min(limite, 20)))
        except Exception as exc:
            print(f"No se pudieron listar planes: {exc}")
            return []

    def _resumen(self, plan: dict, nombre: str) -> str:
        """Resumen local del plan (sin round-trip al LLM)."""
        return (
            f"{nombre}, tu plan de {plan['semanas']} semanas incluye "
            f"{plan['total_sesiones']} sesiones orientadas a {plan['objetivo']}. "
            f"{plan['sesiones_por_semana']} días por semana, con progresión a mitad del ciclo."
        )

    async def _perfil_rapido(
        self, usuario_id: str, authorization: Optional[str]
    ) -> dict[str, Any]:
        """Perfil de users con tope corto; si no llega, el plan se arma igual."""
        try:
            return await asyncio.wait_for(
                self.user_service.get_user_profile(usuario_id, authorization),
                timeout=2.0,
            ) or {}
        except Exception:
            return {"id": usuario_id}

    async def _catalogo_rapido(self) -> list[dict[str, Any]]:
        """Catálogo local (caché); no espera a Mongo."""
        try:
            return await asyncio.wait_for(obtener_catalogo_ejercicios(), timeout=0.8) or list(
                CATALOGO_EJERCICIOS
            )
        except Exception:
            return list(CATALOGO_EJERCICIOS)

    async def _guardar(self, plan: dict, bloquear: bool = True) -> None:
        """Inserta el plan en Mongo; por defecto no retrasa la respuesta."""
        if bloquear:
            await self._persistir_plan(plan)
            return
        try:
            asyncio.get_running_loop().create_task(self._persistir_plan(plan))
        except RuntimeError:
            await self._persistir_plan(plan)

    async def _persistir_plan(self, plan: dict) -> None:
        """Inserta el plan en Mongo; ignora el fallo si la base no está disponible."""
        db = get_db()
        if db is None:
            return
        try:
            await db[COL_PLANES].insert_one(dict(plan))
        except Exception as exc:
            print(f"No se pudo guardar el plan: {exc}")
