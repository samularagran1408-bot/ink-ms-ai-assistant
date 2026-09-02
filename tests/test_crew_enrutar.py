"""Pruebas del enrutado CrewAI: intenciones, roles y confirmación.

No arrancan CrewAI ni el LLM. Ejecutar:

    python tests/test_crew_enrutar.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.crew.enrutar import (  # noqa: E402
    EnrutadoAlChat,
    EnrutadoAmbiguo,
    EnrutadoProhibido,
    catalogo_para_roles,
    dominios_permitidos,
    resolver_dominio,
    rol_principal,
)
from app.crew.crews import resultado_a_informe  # noqa: E402
from app.crew.schemas import InformeCrew  # noqa: E402


def test_atleta_no_ve_investigacion_ni_quiz():
    """El atleta solo consulta y competencia (estilo agente usuario MCP)."""
    permitidos = dominios_permitidos(["USUARIO"])
    assert "consulta" in permitidos
    assert "competencia" in permitidos
    assert "investigacion" not in permitidos
    assert "quiz" not in permitidos
    assert "automatizado" not in permitidos
    ids = {d["id"] for d in catalogo_para_roles(["USUARIO"])}
    assert ids == {"consulta", "competencia"}


def test_admin_ve_todos_los_dominios():
    """Admin cubre el catálogo completo."""
    assert set(dominios_permitidos(["ADMIN"])) == {
        "investigacion",
        "quiz",
        "competencia",
        "automatizado",
        "consulta",
    }
    assert rol_principal(["USUARIO", "ADMIN"]) == "ADMIN"


def test_entrenador_puede_sandbox_y_quiz():
    """Entrenador: quiz, plan, consulta y sandbox. Sin auditoría admin."""
    permitidos = set(dominios_permitidos(["ENTRENADOR"]))
    assert permitidos == {"quiz", "competencia", "consulta", "automatizado"}
    assert "investigacion" not in permitidos


def test_hola_va_al_chat():
    """Los saludos no son un crew."""
    try:
        resolver_dominio("Hola", "auto")
        raise AssertionError("debía lanzar EnrutadoAlChat")
    except EnrutadoAlChat as exc:
        assert exc.intencion == "saludo"


def test_auto_quiz_y_consulta():
    """Clasifica umbral → quiz y recomendaciones → consulta."""
    quiz = resolver_dominio("¿Cuál es el umbral del quiz de organizador?", "auto")
    assert quiz.dominio == "quiz"
    consulta = resolver_dominio("Recomiéndame eventos", "auto")
    assert consulta.dominio == "consulta"


def test_cuantos_eventos_es_consulta_no_investigacion():
    """Un atleta preguntando por eventos no debe ir a métricas admin."""
    ruta = resolver_dominio("¿Cuántos eventos hay?", "auto", roles=["USUARIO"])
    assert ruta.dominio == "consulta"


def test_atleta_no_puede_investigacion():
    """«¿Cuántos usuarios hay?» es investigación; el atleta recibe prohibido."""
    try:
        resolver_dominio("¿Cuántos usuarios hay?", "auto", roles=["USUARIO"])
        raise AssertionError("debía lanzar EnrutadoProhibido")
    except EnrutadoProhibido as exc:
        assert exc.dominio == "investigacion"
        assert "consulta" in exc.permitidos


def test_atleta_no_puede_pedir_quiz_explicito():
    """El selector del front no debe poder forzar un dominio ajeno al rol."""
    try:
        resolver_dominio("Explícame el quiz", "quiz", roles=["USUARIO"])
        raise AssertionError("debía lanzar EnrutadoProhibido")
    except EnrutadoProhibido as exc:
        assert exc.dominio == "quiz"


def test_confirmo_sin_sandbox_en_atleta():
    """Confirmo solo existe en el dominio automatizado."""
    try:
        resolver_dominio("Confirmo", "auto", roles=["USUARIO"])
        raise AssertionError("debía lanzar EnrutadoProhibido")
    except EnrutadoProhibido as exc:
        assert exc.dominio == "automatizado"


def test_confirmo_organizador_va_a_sandbox():
    """Organizador sí puede confirmar una mutación sandbox."""
    ruta = resolver_dominio("Confirmo", "auto", roles=["ORGANIZADOR"])
    assert ruta.dominio == "automatizado"
    assert ruta.origen == "confirmo"


def test_dominio_invalido_es_ambiguo():
    """Un id inventado no pasa como dominio."""
    try:
        resolver_dominio("hola", "naves-espaciales")
        raise AssertionError("debía lanzar EnrutadoAmbiguo")
    except EnrutadoAmbiguo:
        pass


def test_informe_consulta_no_pide_confirmo():
    """Una lectura MCP no debe pintar el botón de sandbox."""
    informe = InformeCrew(
        resumen="Eventos recomendados",
        via_mcp=True,
        via_sandbox=False,
        fuente_tools="mcp",
        hallazgos="listar_eventos",
        pendiente_confirmacion=True,
    )

    class _Fake:
        raw = "recomiendo natacion"
        pydantic = informe

    out = resultado_a_informe(_Fake())
    assert out.pendiente_confirmacion is False
    assert out.via_sandbox is False


def test_informe_detecta_pendiente_confirmacion():
    """Si el raw trae pendiente_confirmacion, el JSON del front lo marca."""

    class _Fake:
        raw = '{"via": "sandbox", "pendiente_confirmacion": true}'
        pydantic = None

    informe = resultado_a_informe(_Fake())
    assert isinstance(informe, InformeCrew)
    assert informe.pendiente_confirmacion is True
    assert informe.via_sandbox is True


def test_politica_crew_solo_sandbox():
    """CrewAI no tiene interruptor a MCP de escritura."""
    from pathlib import Path

    from app.crew.politica import descripcion_escritura, modo_escritura_crew, tools_escritura_crew
    from app.tools.writes import WRITE_TOOLS

    assert modo_escritura_crew() == "sandbox"
    desc = descripcion_escritura()
    assert desc["crew"] == "sandbox"
    assert desc["chat"] == "mcp"
    nombres = {getattr(t, "name", None) or getattr(t, "__name__", "") for t in tools_escritura_crew()}
    assert "crear_evento_sandbox" in nombres
    assert not (nombres & WRITE_TOOLS)

    sandbox = (Path(__file__).resolve().parents[1] / "app/crew/tools_sandbox.py").read_text(
        encoding="utf-8"
    )
    assert "llamar_tool" not in sandbox
    assert "httpx" not in sandbox


def test_mcp_read_rechaza_crear_evento():
    """Un POST de crear_evento no puede colarse por las tools de lectura."""
    from app.crew.tools_mcp_read import _llamar_lectura

    datos = _llamar_lectura("crear_evento", {"name": "x"})
    assert datos["success"] is False
    assert "escritura" in datos["error"]


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
