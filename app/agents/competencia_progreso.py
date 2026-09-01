"""Progreso mixto del plan de competencia: checklist + sesiones de rutina."""

from __future__ import annotations

from typing import Any, Optional


class CompetenciaAccionError(Exception):
    """Acción de plan inválida (modo inactivo, ítem inexistente, etc.)."""

    def __init__(self, status: int, detail: str):
        """Guarda código HTTP y mensaje de negocio para que el router lo traduzca."""
        self.status = status
        self.detail = detail
        super().__init__(detail)


def normalizar_checklist(plan: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convierte el checklist legado (strings) o el actual (dicts) a ítems con id."""
    items: list[dict[str, Any]] = []
    raw = (plan or {}).get("checklist") or []
    if not isinstance(raw, list):
        return items
    for i, item in enumerate(raw, start=1):
        if isinstance(item, dict):
            texto = str(item.get("texto") or item.get("text") or "").strip()
            if not texto:
                continue
            items.append(
                {
                    "id": str(item.get("id") or f"c{i}"),
                    "texto": texto,
                    "hecho": bool(item.get("hecho") or item.get("done")),
                }
            )
            continue
        texto = str(item or "").strip()
        if texto:
            items.append({"id": f"c{i}", "texto": texto, "hecho": False})
    return items


def sesiones_hechas_doc(doc: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Extrae la lista de sesiones de rutina registradas en el documento de modo."""
    raw = (doc or {}).get("sesiones_hechas") or []
    if not isinstance(raw, list):
        return []
    return [s for s in raw if isinstance(s, dict)]


def sesiones_objetivo_plan(plan: Optional[dict[str, Any]], semanas: int) -> int:
    """Suma las sesiones sugeridas de las fases; si no hay, estima 3 por semana (2 la última)."""
    total = 0
    for fase in (plan or {}).get("fases") or []:
        if isinstance(fase, dict):
            total += max(0, int(fase.get("sesiones_sugeridas") or 0))
    if total > 0:
        return total
    semanas = max(1, semanas)
    return sum(3 if i < semanas else 2 for i in range(1, semanas + 1))


def _semana_por_sesiones(plan: Optional[dict[str, Any]], semanas: int, hechas: int) -> int:
    """Infiere la semana actual del plan según cuántas sesiones de rutina ya se registraron."""
    fases = [f for f in ((plan or {}).get("fases") or []) if isinstance(f, dict)]
    if not fases:
        por_semana = max(1, sesiones_objetivo_plan(plan, semanas) // max(1, semanas))
        return min(semanas, hechas // por_semana + 1)

    acumulado = 0
    semana_actual = 1
    for fase in fases:
        semana_actual = int(fase.get("semana") or semana_actual)
        sugeridas = max(1, int(fase.get("sesiones_sugeridas") or 0))
        if hechas < acumulado + sugeridas:
            return min(semanas, max(1, semana_actual))
        acumulado += sugeridas
    return min(semanas, max(1, semana_actual))


def progreso_plan_desde_doc(doc: Optional[dict[str, Any]]) -> dict[str, Any]:
    """% del plan = media de checklist completado y sesiones de rutina hechas."""
    vacio = {
        "semanas": 0,
        "semana_actual": 0,
        "plan_pct": 0,
        "checklist_pct": 0,
        "checklist_hechos": 0,
        "checklist_total": 0,
        "sesiones_pct": 0,
        "sesiones_hechas": 0,
        "sesiones_objetivo": 0,
        "checklist": [],
        "activado_en": None,
    }
    if not doc or not doc.get("activo"):
        return vacio

    semanas = max(1, min(int(doc.get("semanas") or 3), 8))
    plan = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
    checklist = normalizar_checklist(plan)
    hechos = sum(1 for item in checklist if item.get("hecho"))
    check_total = len(checklist)
    check_ratio = (hechos / check_total) if check_total else 0.0

    sesiones = sesiones_hechas_doc(doc)
    hechas = len(sesiones)
    objetivo = max(1, sesiones_objetivo_plan(plan, semanas))
    ses_ratio = min(1.0, hechas / objetivo)
    plan_pct = round(((check_ratio + ses_ratio) / 2) * 100)
    semana_actual = _semana_por_sesiones(plan, semanas, hechas)

    return {
        "semanas": semanas,
        "semana_actual": semana_actual,
        "plan_pct": plan_pct,
        "checklist_pct": round(check_ratio * 100),
        "checklist_hechos": hechos,
        "checklist_total": check_total,
        "sesiones_pct": round(ses_ratio * 100),
        "sesiones_hechas": hechas,
        "sesiones_objetivo": objetivo,
        "checklist": checklist,
        "activado_en": doc.get("activado_en"),
    }


def fases_con_sesiones(
    plan: Optional[dict[str, Any]],
    sesiones_hechas: int,
    semana_actual: int,
) -> list[dict[str, Any]]:
    """Anota en cada fase cuántas sesiones van hechas y cuál es la semana actual."""
    restantes = max(0, int(sesiones_hechas or 0))
    out: list[dict[str, Any]] = []
    for fase in (plan or {}).get("fases") or []:
        if not isinstance(fase, dict):
            continue
        sugeridas = max(0, int(fase.get("sesiones_sugeridas") or 0))
        hechas = min(sugeridas, restantes)
        restantes = max(0, restantes - sugeridas)
        semana = fase.get("semana")
        out.append(
            {
                "semana": semana,
                "foco": fase.get("foco"),
                "intensidad": fase.get("intensidad"),
                "sesiones": f"{hechas}/{sugeridas}" if sugeridas else str(hechas),
                "sesiones_hechas": hechas,
                "sesiones_sugeridas": sugeridas,
                "actual": int(semana or 0) == int(semana_actual or 0),
                "nota": fase.get("nota"),
            }
        )
    return out


def rutinas_inscritas_vista(rutinas: Optional[list]) -> list[dict[str, str]]:
    """Lista id/nombre de rutinas activas (sin canceladas ni duplicados) para la UI."""
    items: list[dict[str, str]] = []
    vistos: set[str] = set()
    for row in rutinas or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "active").lower() == "cancelled":
            continue
        rid = str(row.get("routineId") or row.get("id") or "").strip()
        if not rid or rid in vistos:
            continue
        vistos.add(rid)
        items.append(
            {
                "id": rid,
                "nombre": str(row.get("routineName") or row.get("name") or "Rutina"),
            }
        )
    return items
