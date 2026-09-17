"""Ámbito del chat: consulta de plataforma + casos HU40–HU50 (sin voz)."""

from __future__ import annotations

from typing import Any, Optional

COMANDOS_ENTRENAMIENTO_CHAT = frozenset({
    "recomendar_eventos",
    "recomendar_deportes",
    "detectar_discapacidad",
    "umbral_alertas_semana",
    "configurar_alertas",
    "avance_plan_competencia",
    "alerta_entrenador",
    "progreso_entrenador",
    "modo_competencia",
    "competencia_historial",
    "riesgo_dolor",
    "evaluar_riesgo",
    "historial_riesgo",
    "comparar_historial",
    "comparar_mes",
    "cierre_sesion_comparativa",
    "veredicto_progreso",
    "visualizar_dashboard",
    "dashboard_predicciones",
    "dashboard",
    "ajustar_plan_dificultad",
    "rpe_alto",
    "rpe_bajo",
    "plan_semanal",
    "rutina_objetivo",
    "rutina_adaptada",
    "sugerir_adaptacion",
})

COMANDOS_ENTRENAMIENTO_BLOQUEADOS = frozenset()

INTENCIONES_OTROS_APARTADOS = frozenset({
    "crear_rutina",
})

ACCIONES_OTROS_APARTADOS = frozenset({
    "propuesta_rutina",
})

TOOLS_CHAT_BLOQUEADAS = frozenset({
    "crear_rutina",
    "publicar_rutina",
})

_APARTADO_POR_COMANDO = {
    "umbral_alertas_semana": "riesgo",
    "configurar_alertas": "riesgo",
    "avance_plan_competencia": "competencia",
    "alerta_entrenador": "riesgo",
    "progreso_entrenador": "estadísticas",
    "modo_competencia": "competencia",
    "competencia_historial": "competencia",
    "riesgo_dolor": "riesgo",
    "evaluar_riesgo": "riesgo",
    "historial_riesgo": "riesgo",
    "comparar_historial": "estadísticas",
    "comparar_mes": "estadísticas",
    "cierre_sesion_comparativa": "estadísticas",
    "veredicto_progreso": "estadísticas",
    "visualizar_dashboard": "estadísticas",
    "dashboard_predicciones": "riesgo",
    "dashboard": "estadísticas",
    "ajustar_plan_dificultad": "planes",
    "rpe_alto": "riesgo",
    "rpe_bajo": "riesgo",
    "plan_semanal": "planes",
    "rutina_objetivo": "rutinas",
    "rutina_adaptada": "rutinas",
    "sugerir_adaptacion": "rutinas",
}

_APARTADO_POR_TOOL = {
    "generar_rutina": "rutinas",
    "listar_ejercicios": "rutinas",
    "estadisticas_usuario": "estadísticas",
    "recomendar_rutina_nueva": "rutinas",
    "dibujar_cuerpo": "riesgo",
    "listar_rutinas_publicadas": "rutinas",
    "listar_rutinas_entrenador": "rutinas",
    "crear_rutina": "rutinas",
    "publicar_rutina": "rutinas",
}

_APARTADO_POR_INTENCION = {
    "rutinas": "rutinas",
    "ejercicios": "rutinas",
    "progreso": "estadísticas",
    "lesiones": "riesgo",
    "crear_rutina": "rutinas",
}


def comando_entrenamiento_para_chat(comando: Optional[str]) -> Optional[str]:
    """Devuelve el comando si el chat puede ejecutarlo; si no, None."""
    if not comando:
        return None
    if comando in COMANDOS_ENTRENAMIENTO_BLOQUEADOS:
        return None
    if comando in COMANDOS_ENTRENAMIENTO_CHAT:
        return comando
    return comando


def intencion_de_otro_apartado(intencion: Optional[str]) -> bool:
    return (intencion or "") in INTENCIONES_OTROS_APARTADOS


def accion_de_otro_apartado(accion: Optional[str]) -> bool:
    return (accion or "") in ACCIONES_OTROS_APARTADOS


def tool_bloqueada_en_chat(nombre: Optional[str]) -> bool:
    return (nombre or "") in TOOLS_CHAT_BLOQUEADAS


def filtrar_definiciones_chat(definiciones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in definiciones:
        fn = (item.get("function") or {}) if isinstance(item, dict) else {}
        nombre = fn.get("name")
        if not tool_bloqueada_en_chat(nombre):
            out.append(item)
    return out


def apartado_de(clave: Optional[str]) -> str:
    k = clave or ""
    return (
        _APARTADO_POR_COMANDO.get(k)
        or _APARTADO_POR_TOOL.get(k)
        or _APARTADO_POR_INTENCION.get(k)
        or "ese módulo"
    )


def mensaje_redirigir_apartado(clave: Optional[str]) -> str:
    panel = apartado_de(clave)
    return (
        f"Eso lo gestionas en el apartado de {panel} de InkluSport. "
        "Desde el chat te oriento con consultas e investigación "
        "(eventos, deportes, adaptaciones, perfil o datos de la plataforma), "
        "pero no ejecuto esas herramientas."
    )
