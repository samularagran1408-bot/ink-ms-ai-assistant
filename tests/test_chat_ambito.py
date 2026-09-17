"""El chat ejecuta casos HU sin voz; bloquea solo escrituras de rutina en sports."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.nlp.entrenamiento_pedido import detectar_comando_entrenamiento  # noqa: E402
from app.tools.chat_ambito import (  # noqa: E402
    COMANDOS_ENTRENAMIENTO_CHAT,
    comando_entrenamiento_para_chat,
    filtrar_definiciones_chat,
    tool_bloqueada_en_chat,
)
from app.tools.registry import TOOL_DEFINITIONS  # noqa: E402


def test_comandos_hu_salen_al_chat():
    assert comando_entrenamiento_para_chat("visualizar_dashboard") == "visualizar_dashboard"
    assert comando_entrenamiento_para_chat("veredicto_progreso") == "veredicto_progreso"
    assert comando_entrenamiento_para_chat("ajustar_plan_dificultad") == "ajustar_plan_dificultad"
    assert comando_entrenamiento_para_chat("historial_riesgo") == "historial_riesgo"
    assert comando_entrenamiento_para_chat("avance_plan_competencia") == "avance_plan_competencia"
    assert "activar_tts" not in COMANDOS_ENTRENAMIENTO_CHAT
    assert "comando_accesibilidad" not in COMANDOS_ENTRENAMIENTO_CHAT


def test_voz_ya_no_es_comando_hu():
    assert detectar_comando_entrenamiento("Activar TTS") is None
    assert detectar_comando_entrenamiento("Activar asistencia de voz") is None
    assert detectar_comando_entrenamiento("Ir a eventos") is None
    assert detectar_comando_entrenamiento("Alto contraste") is None


def test_escrituras_plataforma_siguen_fuera():
    assert tool_bloqueada_en_chat("crear_rutina")
    assert tool_bloqueada_en_chat("publicar_rutina")
    filtradas = filtrar_definiciones_chat(TOOL_DEFINITIONS)
    nombres = {(t.get("function") or {}).get("name") for t in filtradas}
    assert "crear_rutina" not in nombres


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
