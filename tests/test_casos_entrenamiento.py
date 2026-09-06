"""Casos de prueba simples HU40–HU50 (2 por historia), alineados con los RF.

    python tests/test_casos_entrenamiento.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.entrenamiento_agent import EntrenamientoAgent  # noqa: E402
from app.nlp.entrenamiento_pedido import detectar_comando_entrenamiento  # noqa: E402
from app.services.entrenamiento_store import reset_memoria  # noqa: E402

UID = "tester-hu-simple"


def _run(coro):
    return asyncio.run(coro)


async def _cmd(comando: str, mensaje: str, disc: str = "motriz"):
    return await EntrenamientoAgent().procesar(
        comando, UID, mensaje, disc, authorization=None, perfil_usuario={"id": UID}
    )


def setup():
    reset_memoria()


def test_detectar_frases_simples():
    assert detectar_comando_entrenamiento("Quiero una rutina adaptada") == "rutina_adaptada"
    assert detectar_comando_entrenamiento("Adapta el ejercicio") == "sugerir_adaptacion"
    assert detectar_comando_entrenamiento("Cuál es mi riesgo de lesión") == "evaluar_riesgo"
    assert detectar_comando_entrenamiento("Tengo dolor al entrenar") == "riesgo_dolor"
    assert detectar_comando_entrenamiento("Genera una rutina de fuerza") == "rutina_objetivo"
    assert detectar_comando_entrenamiento("Plan semanal 3 veces por semana") == "plan_semanal"
    assert detectar_comando_entrenamiento("Estoy fatigado RPE 9") == "rpe_alto"
    assert detectar_comando_entrenamiento("La sesión estuvo fácil RPE 3") == "rpe_bajo"
    assert detectar_comando_entrenamiento("Activar asistencia de voz") == "iniciar_entrenamiento"
    assert detectar_comando_entrenamiento("Comando de voz dame una rutina") == "comando_voz"
    assert detectar_comando_entrenamiento("Muéstrame mi dashboard") == "dashboard"
    assert detectar_comando_entrenamiento("Dashboard de métricas y predicciones") == "dashboard_predicciones"
    assert detectar_comando_entrenamiento("Compara este mes con el anterior") == "comparar_mes"
    assert detectar_comando_entrenamiento("Compara con mi historial") == "comparar_historial"
    assert detectar_comando_entrenamiento("comparativa") == "comparar_mes"
    assert detectar_comando_entrenamiento("Recomiéndame eventos") == "recomendar_eventos"
    assert detectar_comando_entrenamiento("Qué deportes puedo practicar") == "recomendar_deportes"
    assert detectar_comando_entrenamiento("Uso silla de ruedas") == "detectar_discapacidad"
    assert detectar_comando_entrenamiento("Sugiere configuración de accesibilidad") == "detectar_discapacidad"
    assert detectar_comando_entrenamiento("Activa modo competencia") == "modo_competencia"
    assert detectar_comando_entrenamiento("Competir contra mi historial") == "competencia_historial"
    assert detectar_comando_entrenamiento("Avisa al entrenador") == "alerta_entrenador"
    assert detectar_comando_entrenamiento("Notifica progreso destacado") == "progreso_entrenador"


def test_hu40():
    setup()
    a = _run(_cmd("rutina_adaptada", "Quiero una rutina adaptada a mi discapacidad"))
    assert a["datos"]["caso_prueba"] == "CP11-HU40"
    assert a["datos"]["rutina"]["ejercicios"]
    b = _run(_cmd("sugerir_adaptacion", "Adapta el ejercicio para motriz"))
    assert b["datos"]["caso_prueba"] == "CP12-HU40"
    assert b["datos"]["variante_adaptada"]["variante"]


def test_hu41():
    setup()
    a = _run(_cmd("evaluar_riesgo", "Cuál es mi riesgo de lesión"))
    assert a["datos"]["caso_prueba"] == "CP13-HU41"
    assert a["datos"]["riesgo"]["nivel"] in ("bajo", "moderado", "alto")
    b = _run(_cmd("riesgo_dolor", "Tengo dolor al entrenar"))
    assert b["datos"]["caso_prueba"] == "CP14-HU41"
    assert b["datos"]["dolor_reportado"] is True
    assert b["datos"]["riesgo"]["score_riesgo"] >= a["datos"]["riesgo"]["score_riesgo"]


def test_hu42():
    setup()
    a = _run(_cmd("rutina_objetivo", "Genera una rutina de fuerza"))
    assert a["datos"]["caso_prueba"] == "CP15-HU42"
    assert a["datos"]["rutina"]["ejercicios"]
    b = _run(_cmd("plan_semanal", "Plan semanal 3 veces por semana"))
    assert b["datos"]["caso_prueba"] == "CP16-HU42"
    assert b["datos"]["plan"]["sesiones_por_semana"] == 3


def test_hu43():
    setup()
    a = _run(_cmd("rpe_alto", "Estoy fatigado RPE 9"))
    assert a["datos"]["caso_prueba"] == "CP17-HU43"
    assert a["datos"]["plan_ajuste"]["ajuste"] == "bajar"
    b = _run(_cmd("rpe_bajo", "La sesión estuvo fácil RPE 3"))
    assert b["datos"]["caso_prueba"] == "CP18-HU43"
    assert b["datos"]["plan_ajuste"]["ajuste"] == "subir"


def test_hu44():
    setup()
    a = _run(_cmd("iniciar_entrenamiento", "Activar asistencia de voz e iniciar entrenamiento"))
    assert a["datos"]["caso_prueba"] == "CP19-HU44"
    assert a["datos"]["respuesta_auditiva"] is True
    b = _run(_cmd("comando_voz", "Comando de voz: dame una rutina"))
    assert b["datos"]["caso_prueba"] == "CP20-HU44"
    assert b["datos"]["respuesta_auditiva"] is True


def test_hu45():
    setup()
    a = _run(_cmd("dashboard", "Muéstrame mi dashboard"))
    assert a["datos"]["caso_prueba"] == "CP21-HU45"
    assert a["datos"]["graficos"] is True
    b = _run(_cmd("dashboard_predicciones", "Dashboard de métricas y predicciones"))
    assert b["datos"]["caso_prueba"] == "CP22-HU45"
    assert b["datos"]["prediccion_riesgo"]["nivel"]


def test_hu46():
    setup()
    _run(_cmd("rpe_alto", "RPE 9"))
    a = _run(_cmd("comparar_mes", "Compara este mes con el anterior"))
    assert a["datos"]["caso_prueba"] == "CP23-HU46"
    assert "Comparativa" in a["respuesta"]
    assert "riesgo" not in a["respuesta"].lower() or "no es un informe de riesgo" in a["respuesta"].lower()
    b = _run(_cmd("comparar_historial", "Compara con mi historial"))
    assert b["datos"]["caso_prueba"] == "CP24-HU46"
    assert b["datos"]["comparacion_sesion"]["sesiones"] >= 1
    assert "historial" in b["respuesta"].lower()


def test_hu47():
    setup()
    a = _run(_cmd("recomendar_eventos", "Recomiéndame eventos según mi perfil"))
    assert a["datos"]["caso_prueba"] == "CP25-HU47"
    b = _run(_cmd("recomendar_deportes", "Qué deportes puedo practicar"))
    assert b["datos"]["caso_prueba"] == "CP26-HU47"


def test_hu48():
    setup()
    a = _run(_cmd("detectar_discapacidad", "Uso silla de ruedas"))
    assert a["datos"]["caso_prueba"] == "CP27-HU48"
    assert a["datos"]["requiere_confirmacion"] is True
    b = _run(_cmd("detectar_discapacidad", "Sugiere configuración de accesibilidad"))
    assert b["datos"]["caso_prueba"] == "CP28-HU48"
    assert b["datos"]["deteccion"]["requiere_confirmacion"] is True


def test_hu49():
    setup()
    a = _run(_cmd("modo_competencia", "Activa modo competencia"))
    assert a["datos"]["caso_prueba"] == "CP29-HU49"
    b = _run(_cmd("competencia_historial", "Competir contra mi historial"))
    assert b["datos"]["caso_prueba"] == "CP30-HU49"


def test_hu50():
    setup()
    a = _run(_cmd("alerta_entrenador", "Avisa al entrenador, RPE 9"))
    assert a["datos"]["caso_prueba"] == "CP31-HU50"
    assert a["datos"]["alertas"]
    b = _run(_cmd("progreso_entrenador", "Notifica progreso destacado RPE 3"))
    assert b["datos"]["caso_prueba"] == "CP32-HU50"
    assert any(x.get("tipo") == "PROGRESO_DESTACADO" for x in b["datos"]["alertas"])


def _ejecutar_todo() -> int:
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
