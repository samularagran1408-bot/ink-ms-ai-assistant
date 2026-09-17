"""Casos HU40–HU50 sin voz: reemplazos reales de los CP no aprobados.

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
    assert detectar_comando_entrenamiento("Historial de riesgo") == "historial_riesgo"
    assert detectar_comando_entrenamiento("Tengo dolor al entrenar") == "riesgo_dolor"
    assert detectar_comando_entrenamiento("Genera una rutina de fuerza") == "rutina_objetivo"
    assert detectar_comando_entrenamiento("El plan me quedó difícil, ajústalo") == "ajustar_plan_dificultad"
    assert detectar_comando_entrenamiento("Feedback de dificultad: el plan es muy fácil") == "ajustar_plan_dificultad"
    assert detectar_comando_entrenamiento("Estoy fatigado RPE 9") == "rpe_alto"
    assert detectar_comando_entrenamiento("Visualizar dashboard") == "visualizar_dashboard"
    assert detectar_comando_entrenamiento("Cómo voy este mes") == "veredicto_progreso"
    assert detectar_comando_entrenamiento("Voy bien o mal") == "veredicto_progreso"
    assert detectar_comando_entrenamiento("Cómo salió mi sesión RPE 6") == "cierre_sesion_comparativa"
    assert detectar_comando_entrenamiento("Avance del plan de competencia") == "avance_plan_competencia"
    assert detectar_comando_entrenamiento("Activar TTS") is None
    assert detectar_comando_entrenamiento("Comando de voz") is None
    assert detectar_comando_entrenamiento("Alto contraste") is None
    assert detectar_comando_entrenamiento("Publica una rutina de fuerza") is None


def test_hu40():
    setup()
    a = _run(_cmd("rutina_adaptada", "Quiero una rutina adaptada a mi discapacidad"))
    assert a["datos"]["caso_prueba"] == "CP11-HU40"
    b = _run(_cmd("sugerir_adaptacion", "Adapta el ejercicio remo"))
    assert b["datos"]["caso_prueba"] == "CP12-HU40"


def test_hu41():
    setup()
    a = _run(_cmd("evaluar_riesgo", "Cuál es mi riesgo de lesión"))
    assert a["datos"]["caso_prueba"] == "CP13-HU41"
    b = _run(_cmd("riesgo_dolor", "Tengo dolor al entrenar"))
    assert b["datos"]["caso_prueba"] == "CP14-HU41"


def test_hu42():
    setup()
    a = _run(_cmd("rutina_objetivo", "Genera una rutina de fuerza"))
    assert a["datos"]["caso_prueba"] == "CP15-HU42"
    b = _run(_cmd("ajustar_plan_dificultad", "El plan me quedó difícil, ajústalo"))
    assert b["datos"]["caso_prueba"] == "CP16-HU42"
    assert b["datos"]["plan_ajuste"]["sentido"] == "bajar"
    c = _run(_cmd("ajustar_plan_dificultad", "El plan estuvo fácil, súbelo"))
    assert c["datos"]["plan_ajuste"]["sentido"] == "subir"


def test_hu43():
    setup()
    a = _run(_cmd("rpe_alto", "Estoy fatigado RPE 9"))
    assert a["datos"]["caso_prueba"] == "CP17-HU43"
    b = _run(_cmd("rpe_bajo", "RPE 3"))
    assert b["datos"]["caso_prueba"] == "CP18-HU43"


def test_hu44_sin_voz():
    setup()
    a = _run(_cmd("visualizar_dashboard", "Visualizar dashboard"))
    assert a["datos"]["caso_prueba"] == "CP19-HU44"
    assert a["datos"].get("vista") or a["datos"].get("dashboard")
    assert "voz" not in a["respuesta"].lower()
    assert "tts" not in a["respuesta"].lower()
    b = _run(_cmd("veredicto_progreso", "Cómo voy este mes, voy bien o mal"))
    assert b["datos"]["caso_prueba"] == "CP20-HU44"
    assert b["datos"]["veredicto"] in ("progresando", "estable", "cayendo", "va_mal")
    assert "veredicto" in b["respuesta"].lower() or "vas " in b["respuesta"].lower()


def test_hu45():
    setup()
    a = _run(_cmd("dashboard", "Muéstrame mi dashboard"))
    assert a["datos"]["caso_prueba"] == "CP21-HU45"
    b = _run(_cmd("historial_riesgo", "Historial de riesgo"))
    assert b["datos"]["caso_prueba"] == "CP22-HU45"
    assert b["datos"]["historial_riesgo"]


def test_hu46():
    setup()
    a = _run(_cmd("cierre_sesion_comparativa", "Cómo salió mi sesión RPE 7"))
    assert a["datos"]["caso_prueba"] == "CP23-HU46"
    assert a["datos"]["comparacion_sesion"]["mejor_sesion"] is not None
    assert a["datos"]["comparacion_sesion"]["promedio_historico"] is not None
    b = _run(_cmd("comparar_mes", "Compara este mes con el anterior"))
    assert b["datos"]["caso_prueba"] == "CP24-HU46"


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
    b = _run(_cmd("detectar_discapacidad", "Sugiere configuración de accesibilidad"))
    assert b["datos"]["caso_prueba"] == "CP28-HU48"


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
    b = _run(_cmd("progreso_entrenador", "Notifica progreso destacado RPE 3"))
    assert b["datos"]["caso_prueba"] == "CP32-HU50"
    c = _run(_cmd("umbral_alertas_semana", "Acumulé 3 alertas de riesgo esta semana"))
    assert c["datos"]["caso_prueba"] == "CP33-HU50"
    d = _run(_cmd("avance_plan_competencia", "Avance del plan de competencia"))
    assert d["datos"]["caso_prueba"] == "CP34-HU50"
    assert d["datos"]["avance"]["porcentaje"] > 0


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
