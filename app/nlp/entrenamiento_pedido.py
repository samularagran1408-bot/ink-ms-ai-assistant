"""Comandos simples HU40–HU50 alineados con los RF del asistente."""

from __future__ import annotations

import re
from typing import Optional

from app.nlp.texto import normalizar

# Más específico primero.
_COMANDOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("detectar_discapacidad", (
        "silla de ruedas", "detecta mi discapacidad", "detectar discapacidad",
        "configuracion de accesibilidad", "soy ciego", "soy sordo",
        "sugiere accesibilidad",
    )),
    ("alerta_entrenador", (
        "avisa al entrenador", "alerta al entrenador", "notifica al entrenador",
        "alerta de riesgo al entrenador",
    )),
    ("progreso_entrenador", (
        "progreso destacado", "notifica progreso", "avisa progreso al entrenador",
    )),
    ("modo_competencia", (
        "activa modo competencia", "activar modo competencia", "modo competencia",
    )),
    ("competencia_historial", (
        "competir contra mi historial", "como voy en competencia",
        "mi plan de competencia", "analiza mi competencia",
    )),
    ("riesgo_dolor", (
        "tengo dolor", "duele al entrenar", "dolor al entrenar", "molestia al entrenar",
    )),
    ("evaluar_riesgo", (
        "riesgo de lesion", "prediccion de lesion", "mi riesgo",
        "probabilidad de lesion", "evalua mi riesgo",
    )),
    ("recomendar_deportes", (
        "que deportes puedo", "deportes para mi", "deportes segun mi perfil",
        "recomienda deportes", "que deporte practicar",
    )),
    ("recomendar_eventos", (
        "recomienda eventos", "recomiendame eventos", "eventos para mi perfil",
        "eventos segun mi perfil",
    )),
    ("comparar_historial", (
        "compara con mi historial", "evolucion de mis sesiones",
        "comparativa con historial", "sesiones actuales con historicas",
        "historial personal",
    )),
    ("comparar_mes", (
        "compara este mes", "mes anterior", "comparativa mensual",
        "mes actual contra el anterior", "comparativa", "mi evolucion",
    )),
    ("dashboard_predicciones", (
        "predicciones del dashboard", "metricas avanzadas", "dashboard de metricas",
        "rendimiento y predicciones",
    )),
    ("dashboard", (
        "visualizar dashboard", "muestra el dashboard", "mi dashboard",
        "graficos interactivos", "mis metricas",
    )),
    ("iniciar_entrenamiento", (
        "iniciar entrenamiento", "iniciar el entrenamiento",
        "activar asistencia de voz", "activar voz", "asistencia de voz",
    )),
    ("comando_voz", (
        "comando de voz", "por voz", "respuesta auditiva",
    )),
    ("rpe_alto", (
        "estoy fatigado", "rpe 8", "rpe 9", "rpe 10", "demasiado cansado",
        "estuvo dificil",
    )),
    ("rpe_bajo", (
        "estuvo facil", "rpe 3", "rpe 2", "rpe 1", "rpe 4",
    )),
    ("plan_semanal", (
        "rutina semanal", "plan semanal", "veces por semana",
        "plan de entrenamiento personalizado",
    )),
    ("rutina_objetivo", (
        "genera una rutina", "rutina de fuerza", "rutina de resistencia",
        "quiero una rutina de",
    )),
    ("rutina_adaptada", (
        "rutina adaptada", "ejercicios adaptados", "modificaciones de ejercicios",
        "segun mi discapacidad",
    )),
    ("sugerir_adaptacion", (
        "adapta el", "adapta la", "adapta ", "variante adaptada",
        "modifica el ejercicio",
    )),
)


def detectar_comando_entrenamiento(mensaje: str) -> Optional[str]:
    """Comando HU40–HU50, o None si el mensaje no es de estos casos."""
    texto = normalizar(mensaje)
    if not texto:
        return None
    for nombre, frases in _COMANDOS:
        if any(f in texto for f in frases):
            return nombre
    return None


def extraer_rpe(mensaje: str) -> Optional[float]:
    """RPE 0–10 si el usuario lo menciona."""
    texto = normalizar(mensaje)
    m = re.search(r"\brpe\s*(\d+(?:[.,]\d+)?)", texto)
    if m:
        return min(10.0, max(0.0, float(m.group(1).replace(",", "."))))
    m = re.search(r"\b(\d+(?:[.,]\d+)?)\s*(?:/10|de 10)\b", texto)
    if m:
        return min(10.0, max(0.0, float(m.group(1).replace(",", "."))))
    return None


def extraer_frecuencia(mensaje: str) -> int:
    """Sesiones por semana (2–5), por defecto 3."""
    texto = normalizar(mensaje)
    m = re.search(r"(\d)\s*(?:veces|dias|sesiones)?\s*(?:por|a la)?\s*semana", texto)
    if m:
        return max(2, min(5, int(m.group(1))))
    return 3
