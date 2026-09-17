"""Comandos HU40–HU50 del asistente (sin voz, sin sensores, sin visión)."""

from __future__ import annotations

import re
from typing import Optional

from app.nlp.texto import normalizar

# Más específico primero.
_COMANDOS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("umbral_alertas_semana", (
        "3 alertas de riesgo",
        "tres alertas de riesgo",
        "alertas de riesgo esta semana",
        "acumule 3 alertas",
        "acumulo 3 alertas",
        "notificacion push y correo",
        "push y correo",
    )),
    ("avance_plan_competencia", (
        "avance del plan de competencia",
        "progreso del plan de competencia",
        "marcar sesion del plan",
        "completar checklist de competencia",
        "porcentaje del plan de competencia",
        "avance de mi plan competitivo",
    )),
    ("configurar_alertas", (
        "configurar umbrales",
        "configurar umbral",
        "umbral personalizado",
        "umbral de alertas",
        "cambiar umbral de alertas",
        "silenciar alertas",
        "silencio temporal",
    )),
    ("detectar_discapacidad", (
        "silla de ruedas", "detecta mi discapacidad", "detectar discapacidad",
        "configuracion de accesibilidad", "soy ciego", "soy sordo",
        "sugiere accesibilidad", "sugiere configuracion de accesibilidad",
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
    ("historial_riesgo", (
        "historial de riesgo", "mis evaluaciones de riesgo",
        "historial de evaluaciones", "ultimas evaluaciones de riesgo",
        "ver historial de riesgo",
    )),
    ("evaluar_riesgo", (
        "riesgo de lesion", "prediccion de lesion", "mi riesgo",
        "probabilidad de lesion", "evalua mi riesgo", "evaluar riesgo",
    )),
    ("recomendar_deportes", (
        "que deportes puedo", "deportes para mi", "deportes segun mi perfil",
        "recomienda deportes", "que deporte practicar",
    )),
    ("recomendar_eventos", (
        "recomienda eventos", "recomiendame eventos", "eventos para mi perfil",
        "eventos segun mi perfil",
    )),
    ("cierre_sesion_comparativa", (
        "cierre de sesion", "al finalizar sesion", "comparar mi sesion",
        "sesion vs promedio", "mejor sesion", "promedio historico y mejor",
        "como salio mi sesion",
    )),
    ("veredicto_progreso", (
        "voy bien o mal", "estoy progresando", "estoy cayendo",
        "evalua mi progreso", "veredicto de progreso", "tendencia de progreso",
        "como voy este mes", "progreso mes actual", "mes actual y el anterior",
        "si voy mejorando", "si voy empeorando",
    )),
    ("comparar_historial", (
        "compara con mi historial", "evolucion de mis sesiones",
        "comparativa con historial", "sesiones actuales con historicas",
        "historial personal",
    )),
    ("comparar_mes", (
        "compara este mes", "mes anterior", "comparativa mensual",
        "mes actual contra el anterior", "comparativa",
    )),
    ("visualizar_dashboard", (
        "visualizar dashboard", "muestra el dashboard", "muestrame el dashboard",
        "ver dashboard", "dashboard del atleta", "mis indicadores",
        "mostrar mis kpis", "kpis del dashboard",
    )),
    ("dashboard", (
        "muestrame mi dashboard", "mi dashboard", "mi progreso",
        "graficos interactivos", "mis metricas", "ver mi dashboard",
    )),
    ("ajustar_plan_dificultad", (
        "ajusta el plan", "ajustar el plan", "ajustar plan",
        "plan me quedo dificil", "plan estuvo dificil", "plan es muy dificil",
        "plan me quedo facil", "plan estuvo facil", "plan es muy facil",
        "feedback de dificultad", "el plan me resulta dificil",
        "el plan me resulta facil", "baja la intensidad del plan",
        "sube la intensidad del plan",
    )),
    ("rpe_alto", (
        "estoy fatigado", "rpe 8", "rpe 9", "rpe 10", "demasiado cansado",
        "registrar rpe alto",
    )),
    ("rpe_bajo", (
        "rpe 3", "rpe 2", "rpe 1", "rpe 4",
        "registrar rpe bajo", "sesion estuvo facil rpe",
    )),
    ("plan_semanal", (
        "rutina semanal", "plan semanal", "veces por semana",
        "plan de entrenamiento personalizado",
    )),
    ("rutina_objetivo", (
        "genera una rutina", "quiero una rutina de", "dame una rutina",
        "rutina de fuerza", "rutina de resistencia", "rutina de reflejos",
        "rutina de velocidad", "rutina de agilidad", "rutina de coordinacion",
        "rutina de potencia", "rutina de equilibrio", "rutina de movilidad",
    )),
    ("rutina_adaptada", (
        "rutina adaptada", "ejercicios adaptados", "modificaciones de ejercicios",
        "segun mi discapacidad",
    )),
    ("sugerir_adaptacion", (
        "adapta el", "adapta la", "adapta ", "variante adaptada",
        "modifica el ejercicio", "sugerir variante",
    )),
)


_ESCRITURAS_PLATAFORMA = (
    "crea un deporte",
    "crear un deporte",
    "crear deporte",
    "crea deporte",
    "publica una rutina",
    "publicar una rutina",
    "publicar rutina",
    "publica rutina",
    "guardar la rutina",
    "subir la rutina",
    "crear rutina en la plataforma",
)


def detectar_comando_entrenamiento(mensaje: str) -> Optional[str]:
    """Comando HU40–HU50, o None si el mensaje no es de estos casos."""
    texto = normalizar(mensaje)
    if not texto:
        return None
    if any(f in texto for f in _ESCRITURAS_PLATAFORMA):
        return None
    for nombre, frases in _COMANDOS:
        if any(f in texto for f in frases):
            return nombre
    return None


_ALTA_DEPORTE = re.compile(
    r"(?:crea|crear|anade|agrega|alta de|nuevo)\s+(?:un\s+)?deporte\s+"
    r"(?:de\s+|llamado\s+|que se llame\s+)?(.+)",
)


def extraer_nombre_alta_deporte(mensaje: str) -> str:
    """Nombre del deporte a dar de alta."""
    texto = normalizar(mensaje)
    if not texto:
        return ""
    m = _ALTA_DEPORTE.search(texto)
    if not m:
        return ""
    nombre = m.group(1).strip(" .,:;")
    nombre = re.sub(r"^(de|del|la|el|un|una)\s+", "", nombre)
    if not nombre or nombre in {"deporte", "nuevo"}:
        return ""
    return " ".join(p.capitalize() for p in nombre.split())


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


def extraer_umbral_alertas(mensaje: str) -> Optional[int]:
    """Umbral semanal 1–10 si el usuario lo indica."""
    texto = normalizar(mensaje)
    m = re.search(r"umbral(?:\s+de)?(?:\s+alertas)?(?:\s+a|=)?\s*(\d+)", texto)
    if m:
        return max(1, min(10, int(m.group(1))))
    m = re.search(r"(\d+)\s*alertas", texto)
    if m:
        return max(1, min(10, int(m.group(1))))
    m = re.search(r"(?:a|=)\s*(\d+)\b", texto)
    if m and "umbral" in texto:
        return max(1, min(10, int(m.group(1))))
    return None


def extraer_horas_silencio(mensaje: str) -> int:
    """Horas de silencio temporal (1–168), por defecto 24."""
    texto = normalizar(mensaje)
    m = re.search(r"(\d+)\s*horas?", texto)
    if m:
        return max(1, min(168, int(m.group(1))))
    m = re.search(r"(\d+)\s*dias?", texto)
    if m:
        return max(1, min(168, int(m.group(1)) * 24))
    return 24


def feedback_dificultad(mensaje: str) -> str:
    """'bajar' | 'subir' | 'mantener' según el feedback del plan."""
    texto = normalizar(mensaje)
    if any(p in texto for p in ("dificil", "duro", "pesado", "exigente", "baja la", "bajar")):
        return "bajar"
    if any(p in texto for p in ("facil", "suave", "liviano", "sube la", "subir", "progres")):
        return "subir"
    return "mantener"
