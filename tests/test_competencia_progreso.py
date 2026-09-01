"""Progreso mixto del plan de competencia (checklist + sesiones)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.competencia_progreso import (  # noqa: E402
    fases_con_sesiones,
    normalizar_checklist,
    progreso_plan_desde_doc,
    rutinas_inscritas_vista,
    sesiones_objetivo_plan,
)


def _plan(semanas=3, checklist=None, fases=None):
    """Fabrica un plan de competencia de prueba (checklist y fases por semana)."""
    if fases is None:
        fases = [
            {"semana": i, "sesiones_sugeridas": 3 if i < semanas else 2}
            for i in range(1, semanas + 1)
        ]
    return {"checklist": checklist or [], "fases": fases}


def test_inactivo_queda_en_cero():
    """Sin documento o con plan inactivo el porcentaje debe ser 0."""
    assert progreso_plan_desde_doc(None)["plan_pct"] == 0
    assert progreso_plan_desde_doc({"activo": False})["plan_pct"] == 0


def test_plan_recien_activado_empieza_en_cero():
    """Un plan recién activado empieza en semana 1 y 0% de progreso."""
    doc = {"activo": True, "semanas": 3, "plan": _plan()}
    prog = progreso_plan_desde_doc(doc)
    assert prog["plan_pct"] == 0
    assert prog["semana_actual"] == 1
    assert prog["sesiones_objetivo"] == 8


def test_solo_checklist_completa_mitad():
    """Checklist al 100% y 0 sesiones equivale al 50% del plan mixto."""
    checklist = [
        {"id": "a", "texto": "Uno", "hecho": True},
        {"id": "b", "texto": "Dos", "hecho": True},
        {"id": "c", "texto": "Tres", "hecho": True},
        {"id": "d", "texto": "Cuatro", "hecho": True},
    ]
    doc = {"activo": True, "semanas": 3, "plan": _plan(checklist=checklist)}
    prog = progreso_plan_desde_doc(doc)
    assert prog["checklist_pct"] == 100
    assert prog["sesiones_pct"] == 0
    assert prog["plan_pct"] == 50


def test_solo_sesiones_completas_mitad():
    """Todas las sesiones hechas y checklist vacío equivalen al 50% del plan."""
    doc = {
        "activo": True,
        "semanas": 3,
        "plan": _plan(),
        "sesiones_hechas": [{"id": str(i)} for i in range(8)],
    }
    prog = progreso_plan_desde_doc(doc)
    assert prog["sesiones_pct"] == 100
    assert prog["checklist_pct"] == 0
    assert prog["plan_pct"] == 50
    assert prog["semana_actual"] == 3


def test_mixto_mitad_lista_y_mitad_sesiones():
    """50% checklist + 50% sesiones da 50% global y avanza a la semana 2."""
    checklist = [
        {"id": "a", "texto": "Uno", "hecho": True},
        {"id": "b", "texto": "Dos", "hecho": True},
        {"id": "c", "texto": "Tres", "hecho": False},
        {"id": "d", "texto": "Cuatro", "hecho": False},
    ]
    doc = {
        "activo": True,
        "semanas": 3,
        "plan": _plan(checklist=checklist),
        "sesiones_hechas": [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}],
    }
    prog = progreso_plan_desde_doc(doc)
    assert prog["checklist_pct"] == 50
    assert prog["sesiones_pct"] == 50
    assert prog["plan_pct"] == 50
    assert prog["semana_actual"] == 2


def test_completar_semana_1_avanza_a_semana_2():
    """Al completar las 3 sesiones de la semana 1, la actual pasa a 2."""
    doc = {
        "activo": True,
        "semanas": 3,
        "plan": _plan(),
        "sesiones_hechas": [{"id": "1"}, {"id": "2"}, {"id": "3"}],
    }
    prog = progreso_plan_desde_doc(doc)
    assert prog["semana_actual"] == 2
    assert prog["sesiones_hechas"] == 3


def test_checklist_legado_en_strings():
    """Un checklist antiguo (lista de strings) se normaliza a items con id."""
    plan = {"checklist": ["Uno", "Dos"]}
    items = normalizar_checklist(plan)
    assert items[0]["id"] == "c1"
    assert items[1]["hecho"] is False
    doc = {"activo": True, "semanas": 3, "plan": {**_plan(), **plan}}
    assert progreso_plan_desde_doc(doc)["checklist_total"] == 2


def test_fases_reparten_sesiones():
    """Reparte las sesiones hechas entre fases y marca la semana actual."""
    plan = _plan()
    fases = fases_con_sesiones(plan, 4, 2)
    assert fases[0]["sesiones"] == "3/3"
    assert fases[1]["sesiones"] == "1/3"
    assert fases[1]["actual"] is True
    assert fases[2]["sesiones"] == "0/2"


def test_sesiones_objetivo_sin_fases():
    """Sin fases, el objetivo de sesiones se infiere por el número de semanas."""
    assert sesiones_objetivo_plan({}, 3) == 8
    assert sesiones_objetivo_plan({}, 1) == 2


def test_rutinas_inscritas_filtra_canceladas():
    """Omite rutinas canceladas y duplicados, dejando una vista limpia."""
    rows = [
        {"routineId": "r1", "routineName": "Fuerza", "status": "active"},
        {"routineId": "r2", "routineName": "X", "status": "cancelled"},
        {"routineId": "r1", "routineName": "dup"},
    ]
    items = rutinas_inscritas_vista(rows)
    assert items == [{"id": "r1", "nombre": "Fuerza"}]


def _ejecutar_todo() -> int:
    """Corre todas las test_* de este módulo y devuelve 1 si alguna falla."""
    pruebas = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    fallidas = 0
    for prueba in pruebas:
        try:
            prueba()
            print(f"  OK   {prueba.__name__}")
        except AssertionError as exc:
            fallidas += 1
            print(f"  FALLA {prueba.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            fallidas += 1
            print(f"  ERROR {prueba.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(pruebas) - fallidas}/{len(pruebas)} pruebas correctas")
    return 1 if fallidas else 0


if __name__ == "__main__":
    raise SystemExit(_ejecutar_todo())
