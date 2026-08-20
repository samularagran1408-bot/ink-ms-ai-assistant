"""Cards accionables a partir de datos de tools / motor local.

El front las pinta con CTA (ver evento, quiz, sesiones). No sustituyen el texto
del chat: lo complementan con hechos estructurados.
"""

from __future__ import annotations

from typing import Any, Optional


def construir_cards(
    datos: Optional[dict[str, Any]],
    herramientas_usadas: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """Normaliza datos de tool-calling o motor local a cards con CTA."""
    if not datos or not isinstance(datos, dict):
        return []

    cards: list[dict[str, Any]] = []
    usados = herramientas_usadas or []

    # Tool-calling anida el payload bajo el nombre de la tool.
    skip = {
        "modo",
        "rondas",
        "usuario",
        "contexto_usado",
        "historial_turnos_contexto",
        "historial_con_resumen",
        "sintesis_llm",
        "tool_calling",
        "modelo_llm",
        "session_id",
        "pendiente_write",
        "cards",
    }
    for clave, payload in list(datos.items()):
        if clave in skip:
            continue
        if isinstance(payload, dict):
            cards.extend(_cards_desde_bloque(clave, payload))

    # Motor local deja las listas en la raíz.
    cards.extend(_cards_desde_bloque("raiz", datos))

    # Deduplicar por tipo+titulo
    vistos: set[tuple[str, str]] = set()
    unicas: list[dict[str, Any]] = []
    for card in cards:
        clave = (str(card.get("tipo")), str(card.get("titulo")))
        if clave in vistos:
            continue
        vistos.add(clave)
        if usados and not card.get("tool"):
            card["tool"] = usados[0]
        unicas.append(card)
    return unicas[:12]


def _lista_mcp(bloque: dict[str, Any]) -> list:
    data = bloque.get("data")
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for clave in ("content", "items", "eventos", "events", "deportes", "sports"):
            valor = data.get(clave)
            if isinstance(valor, list):
                return valor
    return []


def _cards_desde_bloque(origen: str, bloque: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    tool = origen if origen != "raiz" else None
    items = _lista_mcp(bloque)
    if items and isinstance(items[0], dict):
        muestra = items[0]
        if not bloque.get("eventos") and (
            "evento" in (origen or "")
            or any(k in muestra for k in ("eventDate", "sportName", "availableCapacity"))
        ):
            bloque = {**bloque, "eventos": items}
        elif not bloque.get("deportes") and (
            "deporte" in (origen or "")
            or any(k in muestra for k in ("difficulty", "requiredMaterials"))
        ):
            bloque = {**bloque, "deportes": items}

    for ev in bloque.get("eventos") or []:
        if not isinstance(ev, dict):
            continue
        titulo = str(ev.get("nombre") or ev.get("name") or "Evento")
        deporte = ev.get("deporte") or ev.get("sportName") or ""
        fecha = ev.get("fecha") or ev.get("eventDate") or ""
        meta = [x for x in (deporte, fecha, ev.get("ubicacion")) if x]
        if ev.get("cupos_disponibles") is not None:
            meta.append(f"{ev['cupos_disponibles']} cupos")
        if ev.get("compatible"):
            meta.append("Compatible con tu perfil")
        out.append(
            {
                "tipo": "evento",
                "tool": tool or "listar_eventos",
                "titulo": titulo,
                "subtitulo": deporte or None,
                "meta": meta,
                "cta": {
                    "accion": "ver_eventos",
                    "label": "Ver eventos",
                    "id": str(ev.get("id") or ""),
                },
            }
        )

    for dep in bloque.get("deportes") or []:
        if not isinstance(dep, dict):
            continue
        titulo = str(dep.get("nombre") or dep.get("name") or "Deporte")
        meta = [x for x in (dep.get("dificultad"), dep.get("material")) if x]
        out.append(
            {
                "tipo": "deporte",
                "tool": tool or "listar_deportes",
                "titulo": titulo,
                "subtitulo": dep.get("dificultad"),
                "meta": meta,
                "cta": {"accion": "ver_deportes", "label": "Ver deportes", "id": str(dep.get("id") or "")},
            }
        )

    rutina = bloque.get("rutina_sugerida")
    if isinstance(rutina, dict) and rutina:
        bloques = rutina.get("bloques") or []
        nombres = []
        for b in bloques[:3]:
            if isinstance(b, dict):
                nombres.append(str(b.get("bloque") or ""))
        out.append(
            {
                "tipo": "rutina",
                "tool": tool or "generar_rutina",
                "titulo": str(rutina.get("nombre") or "Rutina adaptada"),
                "subtitulo": rutina.get("objetivo"),
                "meta": [
                    x
                    for x in (
                        f"{rutina.get('duracion_estimada_minutos')} min"
                        if rutina.get("duracion_estimada_minutos")
                        else None,
                        f"{rutina.get('total_ejercicios')} ejercicios"
                        if rutina.get("total_ejercicios")
                        else None,
                        " · ".join(n for n in nombres if n),
                    )
                    if x
                ],
                "cta": {"accion": "ver_sesiones", "label": "Ver sesiones", "id": ""},
            }
        )

    for ej in (bloque.get("ejercicios") or [])[:4]:
        if not isinstance(ej, dict):
            continue
        out.append(
            {
                "tipo": "ejercicio",
                "tool": tool or "listar_ejercicios",
                "titulo": str(ej.get("nombre") or "Ejercicio"),
                "subtitulo": f"{ej.get('series')} × {ej.get('repeticiones')}"
                if ej.get("series")
                else None,
                "meta": [ej.get("instrucciones")] if ej.get("instrucciones") else [],
                "cta": {"accion": "ver_sesiones", "label": "Ver sesiones", "id": ""},
            }
        )

    for ad in (bloque.get("adaptaciones") or [])[:5]:
        if not isinstance(ad, dict):
            continue
        out.append(
            {
                "tipo": "adaptacion",
                "tool": tool or "listar_adaptaciones",
                "titulo": str(ad.get("deporte") or "Adaptación"),
                "subtitulo": ad.get("discapacidad"),
                "meta": [ad.get("adaptacion")] if ad.get("adaptacion") else [],
                "cta": {
                    "accion": "ver_discapacidades",
                    "label": "Ver discapacidades",
                    "id": "",
                },
            }
        )

    if bloque.get("preguntas_organizador") or bloque.get("preguntas_entrenador"):
        out.append(
            {
                "tipo": "quiz",
                "tool": tool or "info_quiz",
                "titulo": "Quiz de aptitud",
                "subtitulo": "Organizador y entrenador",
                "meta": [
                    f"Organizador: {bloque.get('preguntas_organizador')} preguntas, umbral {bloque.get('umbral_organizador')}%",
                    f"Entrenador: {bloque.get('preguntas_entrenador')} preguntas, umbral {bloque.get('umbral_entrenador')}%",
                ],
                "cta": {"accion": "ver_quiz", "label": "Ir al quiz", "id": ""},
            }
        )

    if bloque.get("pendiente_write") and isinstance(bloque.get("pendiente_write"), dict):
        pend = bloque["pendiente_write"]
        out.append(
            {
                "tipo": "confirmacion",
                "tool": pend.get("tool"),
                "titulo": "Confirmar acción",
                "subtitulo": pend.get("resumen"),
                "meta": ["Responde Confirmo o Cancelar"],
                "cta": {
                    "accion": "confirmar_write",
                    "label": "Confirmar",
                    "id": "",
                },
            }
        )

    usuario = bloque.get("usuario_card")
    if isinstance(usuario, dict) and usuario:
        out.append(
            {
                "tipo": "usuario",
                "tool": tool or "consultar_mi_perfil",
                "titulo": str(usuario.get("nombre") or "Tu perfil"),
                "subtitulo": usuario.get("discapacidad"),
                "meta": [", ".join(usuario.get("roles") or [])],
                "cta": {"accion": "ver_perfil", "label": "Ver perfil", "id": ""},
            }
        )

    vista = bloque.get("vista") or bloque.get("estadisticas")
    if isinstance(vista, dict) and vista.get("kpis"):
        for kpi in (vista.get("kpis") or [])[:4]:
            if not isinstance(kpi, dict):
                continue
            out.append(
                {
                    "tipo": "kpi",
                    "tool": tool or "estadisticas_usuario",
                    "titulo": str(kpi.get("label") or kpi.get("clave") or "Dato"),
                    "subtitulo": str(kpi.get("valor")),
                    "meta": [str(kpi.get("icono") or "")],
                    "cta": {"accion": "ver_estadisticas", "label": "Ver estadísticas", "id": ""},
                }
            )

    return out
