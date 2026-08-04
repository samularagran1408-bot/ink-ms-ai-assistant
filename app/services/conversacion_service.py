"""Historial de chat con límites anti-basura (Mongo + contexto LLM).

Diseño:
- El usuario puede listar, abrir y borrar conversaciones (API lista para el front).
- En disco solo se guardan los últimos N mensajes por conversación ($slice).
- Por usuario solo se mantienen M conversaciones activas; el resto se archiva.
- Al LLM solo se envían un resumen corto + los últimos turnos, no el archivo entero.
- Mensajes vacíos o absurdamente largos se recortan/ignoran.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.config import settings
from app.database.mongodb import get_db
from app.database.repositorio import COL_CONVERSACIONES

# Remitentes persistidos
REMITENTE_USUARIO = "usuario"
REMITENTE_ASISTENTE = "asistente"


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def _recortar(texto: str, max_chars: int) -> str:
    t = (texto or "").strip()
    if len(t) <= max_chars:
        return t
    return t[: max_chars - 1].rstrip() + "…"


def _titulo_desde_mensaje(mensaje: str) -> str:
    limpio = " ".join((mensaje or "").split())
    if not limpio:
        return "Conversación"
    return limpio[:60] + ("…" if len(limpio) > 60 else "")


def _resumen_local(mensajes: list[dict[str, Any]], max_chars: int) -> str:
    """Resumen extractivo barato (sin LLM) de turnos antiguos."""
    if not mensajes:
        return ""
    lineas: list[str] = []
    for m in mensajes:
        rol = "Usuario" if m.get("remitente") == REMITENTE_USUARIO else "Asistente"
        texto = _recortar(str(m.get("mensaje") or ""), 160)
        if texto:
            lineas.append(f"- {rol}: {texto}")
    bloque = "\n".join(lineas)
    return _recortar(bloque, max_chars)


class ConversacionService:
    def __init__(self) -> None:
        self.max_mensajes = settings.CHAT_MAX_MENSAJES_POR_CONVERSACION
        self.max_conversaciones = settings.CHAT_MAX_CONVERSACIONES_POR_USUARIO
        self.turnos_llm = settings.CHAT_HISTORIAL_LLM_TURNOS
        self.max_chars_msg = settings.CHAT_MAX_CHARS_MENSAJE
        self.max_chars_resumen = settings.CHAT_RESUMEN_MAX_CHARS

    # ---------------------------------------------------------------- lectura LLM

    async def cargar_contexto_llm(
        self, usuario_id: str, conversacion_id: str
    ) -> tuple[list[dict[str, str]], Optional[str], Optional[str]]:
        """Devuelve (mensajes_role_content, conversacion_id_efectiva, resumen).

        Solo los últimos `turnos_llm` pares user/assistant van al modelo.
        Si hay más historial, se antepone un resumen local/almacenado.
        """
        doc = await self._buscar_doc(usuario_id, conversacion_id)
        if not doc:
            return [], None, None

        cid = doc.get("conversacion_id") or conversacion_id
        mensajes = doc.get("mensajes") or []
        ventana = self.turnos_llm * 2
        recientes = mensajes[-ventana:]
        antiguos = mensajes[:-ventana] if len(mensajes) > ventana else []

        historial: list[dict[str, str]] = []
        for m in recientes:
            texto = _recortar(str(m.get("mensaje") or ""), self.max_chars_msg)
            if not texto:
                continue
            rol = "assistant" if m.get("remitente") == REMITENTE_ASISTENTE else "user"
            historial.append({"role": rol, "content": texto})

        resumen = (doc.get("resumen") or "").strip()
        if antiguos and not resumen:
            resumen = _resumen_local(antiguos, self.max_chars_resumen)
        elif antiguos and resumen:
            # Mezcla ligera: resumen guardado + pico de lo más viejo reciente
            extra = _resumen_local(antiguos[-4:], min(300, self.max_chars_resumen // 3))
            if extra and extra not in resumen:
                resumen = _recortar(f"{resumen}\n{extra}", self.max_chars_resumen)

        return historial[-ventana:], cid, resumen or None

    def mensajes_para_llm(
        self,
        historial: list[dict[str, str]],
        resumen: Optional[str],
    ) -> list[dict[str, str]]:
        """Inserta el resumen como mensaje de sistema auxiliar si existe."""
        if not resumen:
            return list(historial)
        return [
            {
                "role": "system",
                "content": (
                    "Resumen de turnos anteriores de esta conversación "
                    "(no inventes nada fuera de esto):\n" + resumen
                ),
            },
            *historial,
        ]

    # ------------------------------------------------------------- persistencia

    async def guardar_turno(
        self,
        usuario_id: str,
        conversacion_id: str,
        mensaje_usuario: str,
        resultado: dict[str, Any],
    ) -> None:
        db = get_db()
        if db is None:
            return

        mensaje_usuario = _recortar(mensaje_usuario, self.max_chars_msg)
        respuesta = _recortar(str(resultado.get("respuesta") or ""), self.max_chars_msg)
        if not mensaje_usuario or not respuesta:
            return

        ahora = _ahora()
        entrada_user = {
            "mensaje": mensaje_usuario,
            "remitente": REMITENTE_USUARIO,
            "fecha": ahora,
        }
        entrada_bot = {
            "mensaje": respuesta,
            "remitente": REMITENTE_ASISTENTE,
            "intencion": resultado.get("intencion"),
            "fuente": resultado.get("fuente"),
            "fecha": ahora,
        }

        try:
            doc_prev = await db[COL_CONVERSACIONES].find_one(
                {"usuario_id": usuario_id, "conversacion_id": conversacion_id},
                {"mensajes": 1, "titulo": 1, "resumen": 1},
            )
            mensajes_prev = list((doc_prev or {}).get("mensajes") or [])
            todos = mensajes_prev + [entrada_user, entrada_bot]
            # Anti-basura en disco: solo la cola
            todos = todos[-self.max_mensajes :]

            resumen = (doc_prev or {}).get("resumen") or ""
            if len(mensajes_prev) >= self.turnos_llm * 2:
                # Actualiza resumen con lo que queda fuera de la ventana LLM
                fuera = todos[: -self.turnos_llm * 2] if len(todos) > self.turnos_llm * 2 else []
                if fuera:
                    resumen = _resumen_local(fuera, self.max_chars_resumen)

            titulo = (doc_prev or {}).get("titulo") or _titulo_desde_mensaje(mensaje_usuario)

            await db[COL_CONVERSACIONES].update_one(
                {"usuario_id": usuario_id, "conversacion_id": conversacion_id},
                {
                    "$set": {
                        "mensajes": todos,
                        "ultima_interaccion": ahora,
                        "estado": "activa",
                        "agente": resultado.get("agente"),
                        "titulo": titulo,
                        "resumen": resumen,
                        "total_mensajes": len(todos),
                    },
                    "$setOnInsert": {"creada_en": ahora},
                    "$inc": {"turnos": 1},
                },
                upsert=True,
            )
            await self._aplicar_cupo_conversaciones(usuario_id)
        except Exception as exc:
            print(f"Error guardando conversación: {exc}")

    async def _aplicar_cupo_conversaciones(self, usuario_id: str) -> None:
        """Archiva las más viejas si el usuario supera el máximo de activas."""
        db = get_db()
        if db is None:
            return
        try:
            cursor = (
                db[COL_CONVERSACIONES]
                .find({"usuario_id": usuario_id, "estado": "activa"})
                .sort("ultima_interaccion", -1)
            )
            docs = await cursor.to_list(length=self.max_conversaciones + 20)
            sobran = docs[self.max_conversaciones :]
            if not sobran:
                return
            ids = [d["conversacion_id"] for d in sobran if d.get("conversacion_id")]
            if ids:
                await db[COL_CONVERSACIONES].update_many(
                    {"usuario_id": usuario_id, "conversacion_id": {"$in": ids}},
                    {"$set": {"estado": "archivada", "archivada_en": _ahora()}},
                )
        except Exception as exc:
            print(f"Error aplicando cupo de conversaciones: {exc}")

    # ------------------------------------------------------------------- CRUD API

    async def listar(
        self,
        usuario_id: str,
        *,
        incluir_archivadas: bool = False,
        limite: int = 20,
    ) -> list[dict[str, Any]]:
        db = get_db()
        if db is None:
            return []
        filtro: dict[str, Any] = {"usuario_id": usuario_id}
        if not incluir_archivadas:
            filtro["estado"] = "activa"
        try:
            docs = await (
                db[COL_CONVERSACIONES]
                .find(filtro, {"_id": 0, "mensajes": 0})
                .sort("ultima_interaccion", -1)
                .to_list(length=max(1, min(limite, 50)))
            )
            return [
                {
                    "conversacion_id": d.get("conversacion_id"),
                    "titulo": d.get("titulo") or "Conversación",
                    "estado": d.get("estado") or "activa",
                    "creada_en": d.get("creada_en"),
                    "ultima_interaccion": d.get("ultima_interaccion"),
                    "total_mensajes": d.get("total_mensajes")
                    or d.get("turnos")
                    or 0,
                    "tiene_resumen": bool(d.get("resumen")),
                }
                for d in docs
            ]
        except Exception as exc:
            print(f"Error listando conversaciones: {exc}")
            return []

    async def obtener(
        self, usuario_id: str, conversacion_id: str, *, max_mensajes: Optional[int] = None
    ) -> Optional[dict[str, Any]]:
        doc = await self._buscar_doc(usuario_id, conversacion_id, exigir_id=True)
        if not doc:
            return None
        mensajes = doc.get("mensajes") or []
        tope = max_mensajes or self.max_mensajes
        mensajes = mensajes[-tope:]
        return {
            "conversacion_id": doc.get("conversacion_id"),
            "titulo": doc.get("titulo") or "Conversación",
            "estado": doc.get("estado"),
            "creada_en": doc.get("creada_en"),
            "ultima_interaccion": doc.get("ultima_interaccion"),
            "resumen": doc.get("resumen") or None,
            "total_mensajes": len(doc.get("mensajes") or []),
            "mensajes": [
                {
                    "mensaje": m.get("mensaje"),
                    "remitente": m.get("remitente"),
                    "intencion": m.get("intencion"),
                    "fuente": m.get("fuente"),
                    "fecha": m.get("fecha"),
                }
                for m in mensajes
            ],
            "limites": {
                "max_mensajes_guardados": self.max_mensajes,
                "max_conversaciones_activas": self.max_conversaciones,
                "turnos_enviados_al_llm": self.turnos_llm,
            },
        }

    async def borrar(self, usuario_id: str, conversacion_id: str) -> bool:
        db = get_db()
        if db is None:
            return False
        try:
            res = await db[COL_CONVERSACIONES].delete_one(
                {"usuario_id": usuario_id, "conversacion_id": conversacion_id}
            )
            return res.deleted_count > 0
        except Exception as exc:
            print(f"Error borrando conversación: {exc}")
            return False

    async def borrar_todas(self, usuario_id: str) -> int:
        db = get_db()
        if db is None:
            return 0
        try:
            res = await db[COL_CONVERSACIONES].delete_many({"usuario_id": usuario_id})
            return int(res.deleted_count or 0)
        except Exception as exc:
            print(f"Error borrando conversaciones: {exc}")
            return 0

    async def archivar(self, usuario_id: str, conversacion_id: str) -> bool:
        db = get_db()
        if db is None:
            return False
        try:
            res = await db[COL_CONVERSACIONES].update_one(
                {"usuario_id": usuario_id, "conversacion_id": conversacion_id},
                {"$set": {"estado": "archivada", "archivada_en": _ahora()}},
            )
            return res.matched_count > 0
        except Exception as exc:
            print(f"Error archivando conversación: {exc}")
            return False

    # ------------------------------------------------------------------- helpers

    async def _buscar_doc(
        self,
        usuario_id: str,
        conversacion_id: Optional[str],
        *,
        exigir_id: bool = False,
    ) -> Optional[dict[str, Any]]:
        db = get_db()
        if db is None:
            return None
        try:
            cid = (conversacion_id or "").strip()
            if cid:
                return await db[COL_CONVERSACIONES].find_one(
                    {"usuario_id": usuario_id, "conversacion_id": cid},
                    {"_id": 0},
                )
            if exigir_id:
                return None
            # Sin id: continúa la última conversación activa del usuario
            return await db[COL_CONVERSACIONES].find_one(
                {"usuario_id": usuario_id, "estado": "activa"},
                {"_id": 0},
                sort=[("ultima_interaccion", -1)],
            )
        except Exception as exc:
            print(f"Error buscando conversación: {exc}")
            return None
