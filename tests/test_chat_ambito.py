"""El chat flotante no consume tools de competencia, riesgo, rutinas, planes ni estadísticas."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.nlp.entrenamiento_pedido import detectar_comando_entrenamiento  # noqa: E402
from app.tools.chat_ambito import (  # noqa: E402
    COMANDOS_ENTRENAMIENTO_CHAT,
    comando_entrenamiento_para_chat,
    filtrar_definiciones_chat,
    intencion_de_otro_apartado,
    tool_bloqueada_en_chat,
)
from app.tools.registry import TOOL_DEFINITIONS  # noqa: E402


def test_comandos_consulta_siguen_en_chat():
    assert detectar_comando_entrenamiento("Recomiéndame eventos") == "recomendar_eventos"
    assert comando_entrenamiento_para_chat("recomendar_eventos") == "recomendar_eventos"
    assert comando_entrenamiento_para_chat("recomendar_deportes") == "recomendar_deportes"
    assert comando_entrenamiento_para_chat("detectar_discapacidad") == "detectar_discapacidad"
    assert COMANDOS_ENTRENAMIENTO_CHAT == {
        "recomendar_eventos",
        "recomendar_deportes",
        "detectar_discapacidad",
    }


def test_comandos_de_apartados_no_salen_al_chat():
    assert detectar_comando_entrenamiento("Quiero una rutina adaptada") == "rutina_adaptada"
    assert comando_entrenamiento_para_chat("rutina_adaptada") is None
    assert comando_entrenamiento_para_chat("plan_semanal") is None
    assert comando_entrenamiento_para_chat("evaluar_riesgo") is None
    assert comando_entrenamiento_para_chat("modo_competencia") is None
    assert comando_entrenamiento_para_chat("dashboard") is None
    assert comando_entrenamiento_para_chat("comparar_mes") is None


def test_tools_de_apartados_fuera_del_catalogo_chat():
    for nombre in (
        "generar_rutina",
        "listar_ejercicios",
        "estadisticas_usuario",
        "recomendar_rutina_nueva",
        "dibujar_cuerpo",
        "crear_rutina",
        "publicar_rutina",
    ):
        assert tool_bloqueada_en_chat(nombre)
    filtradas = filtrar_definiciones_chat(TOOL_DEFINITIONS)
    nombres = {(t.get("function") or {}).get("name") for t in filtradas}
    assert "listar_eventos" in nombres
    assert "consultar_mi_perfil" in nombres
    assert "generar_rutina" not in nombres
    assert "estadisticas_usuario" not in nombres


def test_intenciones_de_apartados():
    assert intencion_de_otro_apartado("rutinas")
    assert intencion_de_otro_apartado("progreso")
    assert intencion_de_otro_apartado("lesiones")
    assert not intencion_de_otro_apartado("eventos")
    assert not intencion_de_otro_apartado("cuenta")


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
