"""Pruebas de filtros de retención (sin Mongo)."""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents import quiz_agent  # noqa: E402
from app.database.retencion import filtro_anterior, _purgar_quizzes_memoria  # noqa: E402


def test_filtro_anterior_cubre_date_e_iso():
    cutoff = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
    filtro = filtro_anterior("creado_en", cutoff)
    ramas = filtro["$or"]
    assert ramas[0]["creado_en"]["$lt"] == cutoff
    assert ramas[1]["creado_en"]["$lt"] == cutoff.isoformat()


def test_purga_quiz_evaluado_a_las_2_horas():
    quiz_agent._QUIZ_STORE.clear()
    ahora = datetime.now(timezone.utc)
    quiz_agent._QUIZ_STORE["viejo"] = {
        "quiz_id": "viejo",
        "estado": "evaluado",
        "evaluado_en": (ahora - timedelta(hours=3)).isoformat(),
    }
    quiz_agent._QUIZ_STORE["reciente"] = {
        "quiz_id": "reciente",
        "estado": "evaluado",
        "evaluado_en": (ahora - timedelta(minutes=10)).isoformat(),
    }
    quiz_agent._QUIZ_STORE["activo"] = {
        "quiz_id": "activo",
        "estado": "activo",
        "creado_en": (ahora - timedelta(hours=1)).isoformat(),
    }
    quiz_agent._QUIZ_STORE["activo_viejo"] = {
        "quiz_id": "activo_viejo",
        "estado": "activo",
        "creado_en": (ahora - timedelta(hours=5)).isoformat(),
    }

    borrados = _purgar_quizzes_memoria(ahora)

    assert borrados == 2
    assert "viejo" not in quiz_agent._QUIZ_STORE
    assert "activo_viejo" not in quiz_agent._QUIZ_STORE
    assert "reciente" in quiz_agent._QUIZ_STORE
    assert "activo" in quiz_agent._QUIZ_STORE
    quiz_agent._QUIZ_STORE.clear()


if __name__ == "__main__":
    test_filtro_anterior_cubre_date_e_iso()
    test_purga_quiz_evaluado_a_las_2_horas()
    print("ok")
