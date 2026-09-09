"""Pedidos de métricas de plataforma (conteos, dashboard, asociaciones).

Va por el motor local: Sports/Reports, sin Crew ni el LLM eligiendo tools.
Más específico primero. No captura «mi dashboard» ni «mis métricas» (HU personal).
"""

from __future__ import annotations

from typing import Optional

from app.nlp.texto import normalizar

_PEDIDOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "estadisticas_eventos",
        (
            "evento con mas usuarios inscritos",
            "evento con mas inscritos",
            "evento con mas usuarios",
            "evento con mas participantes",
            "evento con mas gente",
            "evento con mas cupos ocupados",
            "cual evento tiene mas",
            "que evento tiene mas",
            "el evento con mas",
            "evento mas popular",
            "evento mas lleno",
            "evento mas inscrito",
            "evento con menos inscritos",
            "evento con menos gente",
            "ranking de inscritos",
            "inscritos por evento",
            "estadisticas de eventos",
            "estadisticas de inscripciones",
            "cuantos inscritos tiene",
            "cuantos inscritos hay",
            "cuantas inscripciones",
            "aforo de eventos",
            "cupos ocupados",
        ),
    ),
    (
        "asociaciones_por_deporte",
        (
            "asociaciones por deporte",
            "asociacion por deporte",
            "cuantas asociaciones",
            "cuantas adaptaciones por deporte",
            "adaptaciones por deporte",
            "discapacidades por deporte",
            "numeros de asociaciones",
            "numero de asociaciones",
            "conteo de asociaciones",
            "asociaciones deporte discapacidad",
        ),
    ),
    (
        "cuantos_usuarios",
        (
            "cuantos usuarios",
            "cuantas usuarios",
            "total de usuarios",
            "usuarios registrados",
            "usuarios activos",
            "cuantos activos hay",
            "cuantos inactivos",
        ),
    ),
    (
        "cuantos_atletas",
        (
            "cuantos atletas",
            "atletas inscritos",
            "resumen de atletas",
            "listado de atletas",
            "asistencia de atletas",
        ),
    ),
    (
        "cuantas_rutinas",
        (
            "cuantas rutinas",
            "rutinas publicadas hay",
            "total de rutinas",
            "cuantas sesiones publicadas",
        ),
    ),
    (
        "cuantos_eventos",
        (
            "cuantos eventos",
            "cuantas eventos",
            "total de eventos",
            "numero de eventos",
            "cuantos eventos hay",
            "cuantos eventos publicados",
        ),
    ),
    (
        "cuantos_deportes",
        (
            "cuantos deportes",
            "total de deportes",
            "cuantos deportes hay",
            "numero de deportes",
        ),
    ),
    (
        "cuantas_discapacidades",
        (
            "cuantas discapacidades hay",
            "cuantos tipos de discapacidad",
            "total de discapacidades",
            "numero de discapacidades",
        ),
    ),
    (
        "panel_organizador",
        (
            "panel de organizador",
            "metricas de organizador",
            "metricas de mis eventos",
            "asistencia de mis eventos",
            "tasa de asistencia",
            "resumen de organizador",
        ),
    ),
    (
        "panel_entrenador",
        (
            "panel de entrenador",
            "metricas de entrenador",
            "metricas de mis rutinas",
            "resumen de entrenador",
            "atletas de mis rutinas",
        ),
    ),
    (
        "dashboard_plataforma",
        (
            "dashboard admin",
            "dashboard de la plataforma",
            "dashboard de inklusport",
            "metricas de la plataforma",
            "resumen de la plataforma",
            "kpis de la plataforma",
            "numeros de la plataforma",
            "estadisticas de la plataforma",
            "cuantos hay en la plataforma",
        ),
    ),
)


def detectar_pedido_metricas(mensaje: str) -> Optional[str]:
    """Comando de métricas, o None si el mensaje no pide números de plataforma."""
    texto = normalizar(mensaje)
    if not texto:
        return None
    if texto.startswith("mi ") or " mis " in f" {texto} ":
        if "plataforma" not in texto and "asociacion" not in texto:
            return None
    for nombre, frases in _PEDIDOS:
        if any(f in texto for f in frases):
            return nombre
    return None
