"""Ámbito del chat flotante: solo consulta e investigación.

Competencia, riesgo, rutinas, planes y estadísticas personales tienen
apartado propio en la UI. El chat no ejecuta esas tools; sí puede orientar
en texto y consultar catálogo (eventos, deportes, perfil, métricas de
plataforma).
"""

from __future__ import annotations

from typing import Any, Optional

# Comandos HU que el chat sí despacha (consulta de catálogo / perfil).
COMANDOS_ENTRENAMIENTO_CHAT = frozenset({
    "recomendar_eventos",
    "recomendar_deportes",
    "detectar_discapacidad",
})

COMANDOS_ENTRENAMIENTO_BLOQUEADOS = frozenset({
    "umbral_alertas_semana",
    "alerta_entrenador",
    "progreso_entrenador",
    "modo_competencia",
    "competencia_historial",
    "riesgo_dolor",
    "evaluar_riesgo",
    "comparar_historial",
    "comparar_mes",
    "dashboard_predicciones",
    "dashboard",
    "iniciar_entrenamiento",
    "comando_voz",
    "rpe_alto",
    "rpe_bajo",
    "plan_semanal",
    "rutina_objetivo",
    "rutina_adaptada",
    "sugerir_adaptacion",
})

INTENCIONES_OTROS_APARTADOS = frozenset({
    "rutinas",
    "ejercicios",
    "progreso",
    "lesiones",
    "crear_rutina",
})

ACCIONES_OTROS_APARTADOS = frozenset({
    "rutina",
    "ejercicios",
    "estadisticas",
    "cuerpo",
    "propuesta_rutina",
})

TOOLS_CHAT_BLOQUEADAS = frozenset({
    "generar_rutina",
    "listar_ejercicios",
    "estadisticas_usuario",
    "recomendar_rutina_nueva",
    "dibujar_cuerpo",
    "listar_rutinas_publicadas",
    "listar_rutinas_entrenador",
    "crear_rutina",
    "publicar_rutina",
})

_APARTADO_POR_COMANDO = {
    "umbral_alertas_semana": "riesgo",
    "alerta_entrenador": "riesgo",
    "progreso_entrenador": "estadísticas",
    "modo_competencia": "competencia",
    "competencia_historial": "competencia",
    "riesgo_dolor": "riesgo",
    "evaluar_riesgo": "riesgo",
    "comparar_historial": "estadísticas",
    "comparar_mes": "estadísticas",
    "dashboard_predicciones": "estadísticas",
    "dashboard": "estadísticas",
    "iniciar_entrenamiento": "rutinas",
    "comando_voz": "rutinas",
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
    """Devuelve el comando solo si el chat puede ejecutarlo; si no, None."""
    if not comando:
        return None
    if comando in COMANDOS_ENTRENAMIENTO_BLOQUEADOS:
        return None
    return comando


def intencion_de_otro_apartado(intencion: Optional[str]) -> bool:
    """True si la intención pertenece a rutinas, riesgo, planes o estadísticas."""
    return (intencion or "") in INTENCIONES_OTROS_APARTADOS


def accion_de_otro_apartado(accion: Optional[str]) -> bool:
    """True si la acción interna del motor es de un apartado fuera del chat."""
    return (accion or "") in ACCIONES_OTROS_APARTADOS


def tool_bloqueada_en_chat(nombre: Optional[str]) -> bool:
    """True si esa tool no debe ejecutarse ni ofrecerse en el chat flotante."""
    return (nombre or "") in TOOLS_CHAT_BLOQUEADAS


def filtrar_definiciones_chat(definiciones: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quita del catálogo OpenAI-tools las de competencia, riesgo, rutinas, planes y estadísticas."""
    out: list[dict[str, Any]] = []
    for item in definiciones:
        fn = (item.get("function") or {}) if isinstance(item, dict) else {}
        nombre = fn.get("name")
        if not tool_bloqueada_en_chat(nombre):
            out.append(item)
    return out


def apartado_de(clave: Optional[str]) -> str:
    """Nombre del panel de la UI al que redirigir (rutinas, riesgo, etc.)."""
    k = clave or ""
    return (
        _APARTADO_POR_COMANDO.get(k)
        or _APARTADO_POR_TOOL.get(k)
        or _APARTADO_POR_INTENCION.get(k)
        or "ese módulo"
    )


def mensaje_redirigir_apartado(clave: Optional[str]) -> str:
    """Texto corto: oriento en el chat, la acción vive en su apartado."""
    panel = apartado_de(clave)
    return (
        f"Eso lo gestionas en el apartado de {panel} de InkluSport. "
        "Desde el chat te oriento con consultas e investigación "
        "(eventos, deportes, adaptaciones, perfil o datos de la plataforma), "
        "pero no ejecuto esas herramientas."
    )
