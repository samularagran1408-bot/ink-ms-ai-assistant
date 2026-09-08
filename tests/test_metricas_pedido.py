"""Detector de métricas de plataforma (sin HTTP).

    python tests/test_metricas_pedido.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.nlp.entrenamiento_pedido import detectar_comando_entrenamiento  # noqa: E402
from app.nlp.metricas_pedido import detectar_pedido_metricas  # noqa: E402


def test_asociaciones_y_conteos():
    assert detectar_pedido_metricas("Números de asociaciones por deporte") == "asociaciones_por_deporte"
    assert detectar_pedido_metricas("¿Cuántas asociaciones hay?") == "asociaciones_por_deporte"
    assert detectar_pedido_metricas("¿Cuántos usuarios hay?") == "cuantos_usuarios"
    assert detectar_pedido_metricas("¿Cuántos eventos hay?") == "cuantos_eventos"
    assert detectar_pedido_metricas("¿Cuántos deportes hay?") == "cuantos_deportes"
    assert detectar_pedido_metricas("¿Cuántas discapacidades hay?") == "cuantas_discapacidades"
    assert detectar_pedido_metricas("¿Cuántas rutinas publicadas hay?") == "cuantas_rutinas"
    assert detectar_pedido_metricas("Atletas inscritos") == "cuantos_atletas"
    assert detectar_pedido_metricas("Métricas de la plataforma") == "dashboard_plataforma"
    assert detectar_pedido_metricas("Dashboard admin") == "dashboard_plataforma"
    assert detectar_pedido_metricas("Tasa de asistencia") == "panel_organizador"
    assert detectar_pedido_metricas("Métricas de entrenador") == "panel_entrenador"


def test_no_roba_chat_personal_ni_listados():
    assert detectar_pedido_metricas("Hola") is None
    assert detectar_pedido_metricas("¿Qué eventos hay disponibles?") is None
    assert detectar_pedido_metricas("Muéstrame mi dashboard") is None
    assert detectar_comando_entrenamiento("Muéstrame mi dashboard") == "dashboard"
    assert detectar_pedido_metricas("Mis métricas") is None
    assert detectar_pedido_metricas("Quiero una rutina adaptada") is None


if __name__ == "__main__":
    test_asociaciones_y_conteos()
    test_no_roba_chat_personal_ni_listados()
    print("ok")
