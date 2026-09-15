"""El chat del producto no usa CrewAI por defecto (CHAT_ORQUESTA_CREW=false).

El chat flotante es consulta e investigación. CrewAI de competencia, riesgo
o rutinas queda en POST /api/ai/crew o en sus apartados. Si se activa el
flag, este puente solo cubre consulta, investigación y quiz.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

from app.config import settings
from app.crew.crews import resultado_a_informe, run_dominio
from app.crew.ctx import lecturas_sesion
from app.crew.enrutar import (
    Enrutado,
    EnrutadoAlChat,
    EnrutadoAmbiguo,
    EnrutadoProhibido,
    resolver_dominio,
)
from app.crew.schemas import InformeCrew

_DOMINIOS_CHAT = frozenset({"consulta", "investigacion", "quiz"})

_META_MARCAS = (
    "model context protocol",
    "sandbox environment",
    "herramientas mcp",
    "interacción con herramientas",
    "interaccion con herramientas",
    "análisis completo de la interacción",
    "analisis completo de la interaccion",
    "via_mcp",
    "via_sandbox",
    "fuente_tools",
)

_TOOLS_EVENTO = (
    "listar_eventos_disponibles",
    "listar_eventos",
    "recomendar_evento_nuevo",
)


def enrutado_chat_crew(
    mensaje: str,
    roles: Optional[list[str]] = None,
) -> Optional[Enrutado]:
    """Dominio de crew para este turno, o None si el chat local debe seguir."""
    try:
        ruta = resolver_dominio(mensaje, "auto", roles=roles)
    except (EnrutadoAlChat, EnrutadoAmbiguo, EnrutadoProhibido):
        return None
    if not ruta.dominio or ruta.dominio not in _DOMINIOS_CHAT:
        return None
    return ruta


def es_texto_meta(texto: str) -> bool:
    """True si el LLM describió el taller (MCP/sandbox) en vez de responder."""
    t = (texto or "").strip().lower()
    if not t:
        return True
    return any(marca in t for marca in _META_MARCAS)


def texto_para_usuario(informe: InformeCrew) -> Optional[str]:
    """Hallazgos o resumen, si no son jerga de protocolo. None = fallback."""
    for candidato in (informe.hallazgos, informe.resumen):
        texto = (candidato or "").strip()
        if texto and not es_texto_meta(texto):
            return texto
    return None


def herramientas_reales(nombres: Optional[list[str]]) -> list[str]:
    """Quita chips de taller (MCP, sandbox, protocolos) del widget."""
    out: list[str] = []
    vistos: set[str] = set()
    for bruto in nombres or []:
        clave = (bruto or "").strip()
        if not clave:
            continue
        bajo = clave.lower().replace("_", " ")
        if bajo in {"mcp", "sandbox", "agente"}:
            continue
        if any(
            marca in bajo
            for marca in (
                "mcp",
                "sandbox",
                "protocol",
                "protocolo",
                "environment",
            )
        ):
            continue
        if " " in clave:
            continue
        if clave not in vistos:
            vistos.add(clave)
            out.append(clave)
    return out


def _lista_hechos(payload: Any) -> list[dict[str, Any]]:
    """Lista de dicts dentro de un JSON de tool (data / recomendaciones / eventos)."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for clave in ("content", "items", "eventos", "events", "recomendaciones"):
            valor = data.get(clave)
            if isinstance(valor, list):
                return [x for x in valor if isinstance(x, dict)]
    for clave in ("eventos", "events", "recomendaciones"):
        valor = payload.get(clave)
        if isinstance(valor, list):
            return [x for x in valor if isinstance(x, dict)]
    return []


def _cupos(evento: dict[str, Any]) -> Optional[int]:
    valor = evento.get("cupos_disponibles")
    if valor is None:
        valor = evento.get("availableCapacity")
    if valor is None:
        return None
    try:
        return int(valor)
    except (TypeError, ValueError):
        return None


def _con_cupo(evento: dict[str, Any]) -> bool:
    """False si sabemos que no hay cupos (iría a lista de espera)."""
    cupos = _cupos(evento)
    return True if cupos is None else cupos > 0


def _normalizar_evento(evento: dict[str, Any]) -> dict[str, Any]:
    nombre = evento.get("nombre") or evento.get("name") or evento.get("evento")
    fecha = evento.get("fecha") or evento.get("eventDate")
    cupos = _cupos(evento)
    out = dict(evento)
    if nombre:
        out["nombre"] = nombre
        out.setdefault("name", nombre)
    if fecha:
        out["fecha"] = fecha
        out.setdefault("eventDate", fecha)
    if cupos is not None:
        out["cupos_disponibles"] = cupos
    if not out.get("id") and evento.get("evento_id"):
        out["id"] = evento["evento_id"]
    return out


def eventos_de_lecturas(lecturas: dict[str, Any]) -> list[dict[str, Any]]:
    """Eventos con cupo, priorizando listar_eventos_disponibles."""
    vistos: set[str] = set()
    out: list[dict[str, Any]] = []
    for nombre in _TOOLS_EVENTO:
        payload = lecturas.get(nombre)
        if not payload:
            continue
        for bruto in _lista_hechos(payload):
            if not _con_cupo(bruto):
                continue
            ev = _normalizar_evento(bruto)
            clave = str(ev.get("id") or ev.get("nombre") or "")
            if clave and clave in vistos:
                continue
            if clave:
                vistos.add(clave)
            out.append(ev)
        if out:
            break
    return out


def texto_desde_lecturas(lecturas: dict[str, Any]) -> Optional[str]:
    """Lista en español a partir de tools, si el LLM no redactó hechos."""
    eventos = eventos_de_lecturas(lecturas)
    if not eventos:
        if any(n in lecturas for n in _TOOLS_EVENTO):
            return (
                "Ahora mismo no hay eventos con cupos libres para inscribirse "
                "(sin lista de espera)."
            )
        return None
    lineas: list[str] = []
    for ev in eventos[:8]:
        partes = [str(ev.get("nombre") or "Evento")]
        deporte = ev.get("deporte") or ev.get("sportName")
        if deporte:
            partes.append(str(deporte))
        fecha = ev.get("fecha") or ev.get("eventDate")
        if fecha:
            partes.append(str(fecha))
        cupos = _cupos(ev)
        if cupos is not None:
            partes.append(f"{cupos} cupos")
        lineas.append(" · ".join(partes))
    return "Puedes inscribirte en estos eventos con cupos disponibles:\n" + "\n".join(
        f"- {linea}" for linea in lineas
    )


def datos_tools_para_chat(lecturas: dict[str, Any]) -> dict[str, Any]:
    """Payloads de tools, con eventos ya filtrados por cupo para las cards."""
    datos: dict[str, Any] = {}
    for nombre, payload in lecturas.items():
        if not isinstance(payload, dict):
            continue
        if nombre in _TOOLS_EVENTO:
            eventos = [_normalizar_evento(e) for e in _lista_hechos(payload) if _con_cupo(e)]
            datos[nombre] = {**payload, "eventos": eventos}
        else:
            datos[nombre] = payload
    return datos


def empaquetar_chat(
    ruta: Enrutado,
    informe: InformeCrew,
    lecturas: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Arma el dict del chat. None si no hay texto útil (cae al motor local)."""
    lecturas = lecturas or {}
    pidio_eventos = (ruta.intencion or "") in {"eventos", "inscripcion"}
    if pidio_eventos and not any(n in lecturas for n in _TOOLS_EVENTO):
        return None

    respuesta = texto_para_usuario(informe) or texto_desde_lecturas(lecturas)
    if not respuesta:
        return None

    tools = herramientas_reales(informe.tools_usadas)
    for nombre in lecturas:
        if nombre not in tools:
            tools.append(nombre)

    return {
        "respuesta": respuesta,
        "intencion": ruta.intencion or ruta.dominio,
        "adaptada": True,
        "fuente": "crew",
        "agente": f"crew-{ruta.dominio}",
        "sugerencias": [],
        "herramientas_usadas": tools,
        "datos": {
            "crew": {
                "dominio": ruta.dominio,
                "dominio_origen": ruta.origen,
                "via_mcp": informe.via_mcp,
                "via_sandbox": informe.via_sandbox,
                "fuente_tools": informe.fuente_tools,
                "hallazgos": informe.hallazgos,
            },
            **datos_tools_para_chat(lecturas),
        },
        "tool_calling": True,
    }


def _kickoff_con_lecturas(
    dominio: str,
    mensaje: str,
    authorization: Optional[str],
    usuario_id: str,
    discapacidad: str,
) -> tuple[Any, dict[str, Any]]:
    """Kickoff en el hilo del crew y copia las lecturas de ese mismo contexto."""
    bruto = run_dominio(dominio, mensaje, authorization, usuario_id, discapacidad)
    return bruto, lecturas_sesion()


async def ejecutar_crew_en_chat(
    *,
    mensaje: str,
    roles: Optional[list[str]],
    authorization: Optional[str],
    usuario_id: str,
    discapacidad: str,
    eventos: Optional[Any] = None,
) -> Optional[dict[str, Any]]:
    """Kickoff CrewAI y lo empaqueta como respuesta de chat. None = fallback."""
    ruta = enrutado_chat_crew(mensaje, roles)
    if ruta is None or not ruta.dominio:
        return None

    if eventos is not None:
        eventos.append({"evento": "estado", "detalle": "crew"})

    try:
        bruto, lecturas = await asyncio.wait_for(
            asyncio.to_thread(
                _kickoff_con_lecturas,
                ruta.dominio,
                mensaje,
                authorization,
                usuario_id,
                discapacidad,
            ),
            timeout=float(settings.CREW_TIMEOUT_SEGUNDOS),
        )
    except Exception as exc:
        print(f"Crew desde chat falló; motor local. {type(exc).__name__}: {exc}", flush=True)
        return None

    paquete = empaquetar_chat(ruta, resultado_a_informe(bruto), lecturas)
    if paquete is None:
        print("Crew devolvió meta-texto (MCP/sandbox); motor local.", flush=True)
        return None

    if eventos is not None:
        eventos.append({"evento": "estado", "detalle": "crew", "estado": "listo"})
    return paquete
