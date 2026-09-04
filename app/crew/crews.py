"""5 crews sequential (taller 01): un dominio = un agente + 1 task."""

from __future__ import annotations

from typing import Any, Callable, Optional

from crewai import Crew, LLM, Process, Task

from app.crew.agents import (
    agente_automatizado,
    agente_competencia,
    agente_consulta,
    agente_investigacion,
    agente_quiz,
)
from app.crew.ctx import set_sesion
from app.crew.llm import candidatos_llm, llm_crew, llm_saturado
from app.crew.schemas import InformeCrew
from app.crew.tools_mcp_read import set_authorization

_SALIDA_USUARIO = (
    "InformeCrew para el usuario final: resumen = respuesta en español con hechos "
    "(nombres, fechas, cupos). hallazgos = los mismos hechos. "
    "tools_usadas = nombres reales de tools (p.ej. listar_eventos_disponibles). "
    "PROHIBIDO en resumen y hallazgos: MCP, sandbox, Model Context Protocol, "
    "herramientas, análisis de la interacción."
)


def _crew(agente, description: str, expected: str) -> Crew:
    tarea = Task(
        description=description,
        expected_output=expected,
        agent=agente,
        output_pydantic=InformeCrew,
    )
    return Crew(
        agents=[agente],
        tasks=[tarea],
        process=Process.sequential,
        verbose=True,
    )


def crew_investigacion(llm: Optional[LLM] = None) -> Crew:
    """Estadísticas y listados MCP. Sin quiz ni sandbox."""
    return _crew(
        agente_investigacion(llm=llm),
        (
            "El usuario pregunta: '{mensaje}'.\n"
            "Usa UNA o DOS tools de lectura. Prioriza listar_eventos o "
            "consultar_dashboard. Prohibido: crear/cancelar/bloquear, quiz, rutinas, quién soy.\n"
            "Responde con cifras y nombres reales. No menciones MCP ni sandbox."
        ),
        _SALIDA_USUARIO,
    )


def crew_quiz(llm: Optional[LLM] = None) -> Crew:
    """Solo quiz local. Sin MCP de eventos ni CRUD."""
    return _crew(
        agente_quiz(llm=llm),
        (
            "El usuario pregunta: '{mensaje}'.\n"
            "Usa info_quiz y/o muestra_preguntas_quiz. No llames tools de eventos, "
            "dashboard, usuarios ni sandbox.\n"
            "Explica umbrales y banco al usuario. No menciones MCP ni sandbox."
        ),
        _SALIDA_USUARIO,
    )


def crew_competencia(llm: Optional[LLM] = None) -> Crew:
    """Planes y riesgo. Sin quiz ni admin."""
    return _crew(
        agente_competencia(llm=llm),
        (
            "El usuario pregunta: '{mensaje}'.\n"
            "Usa panorama_competencia o evaluar_riesgo_plan. Opcional: "
            "listar_eventos_disponibles o listar_rutinas_publicadas solo para contexto. "
            "Prohibido: quiz, dashboard admin, CRUD.\n"
            "Habla de plan y riesgo. No menciones MCP ni sandbox."
        ),
        _SALIDA_USUARIO,
    )


def crew_automatizado(llm: Optional[LLM] = None) -> Crew:
    """Solo sandbox. Confirmación Confirmo."""
    return _crew(
        agente_automatizado(llm=llm),
        (
            "El usuario pide: '{mensaje}'.\n"
            "Usa SOLO tools sandbox (via=sandbox). Si no hay Confirmo, llama la tool "
            "igual: devolverá pendiente_confirmacion. Si el mensaje es Confirmo, "
            "pasa confirmacion='Confirmo'. Prohibido: MCP de escritura, quiz, dashboard."
        ),
        "Informe via_sandbox=true. pendiente_confirmacion=true si faltó Confirmo. "
        "Nunca digas que cambió MySQL o Sports real.",
    )


def crew_consulta(llm: Optional[LLM] = None) -> Crew:
    """Perfil y recomendaciones para esa persona."""
    return _crew(
        agente_consulta(llm=llm),
        (
            "El usuario pregunta: '{mensaje}'.\n"
            "Hablas con el usuario de InkluSport, no con un evaluador de taller.\n"
            "Si pregunta por eventos disponibles, cupos, lista de espera o inscripción, "
            "llama listar_eventos_disponibles. Si necesita el listado general, listar_eventos. "
            "Si es para ESA persona, consultar_usuario y consultar_inscripciones. "
            "También puedes usar deportes, adaptaciones o recomendar_*/generar_rutina.\n"
            "En resumen: lista concreta (nombre, fecha, cupos) o di que no hay. "
            "Prohibido: dashboard global, quiz, CRUD, bloquear, MCP, sandbox, "
            "Model Context Protocol, 'análisis de la interacción'."
        ),
        _SALIDA_USUARIO,
    )


_FABRICAS: dict[str, Callable[..., Crew]] = {
    "investigacion": crew_investigacion,
    "quiz": crew_quiz,
    "competencia": crew_competencia,
    "automatizado": crew_automatizado,
    "consulta": crew_consulta,
}


def run_dominio(
    dominio: str,
    mensaje: str,
    authorization: Optional[str] = None,
    usuario_id: Optional[str] = None,
    discapacidad: Optional[str] = None,
) -> Any:
    """Kickoff del crew del dominio. JWT y perfil de sesión para las tools."""
    set_sesion(
        authorization=authorization,
        usuario_id=usuario_id,
        discapacidad=discapacidad,
        mensaje=mensaje,
    )
    fabrica = _FABRICAS.get(dominio)
    if fabrica is None:
        raise ValueError(f"dominio desconocido: {dominio}")

    ultimo: Optional[Exception] = None
    candidatos = candidatos_llm()
    for i, modelo in enumerate(candidatos):
        try:
            llm = llm_crew(modelo=modelo) if modelo else llm_crew()
            return fabrica(llm=llm).kickoff(inputs={"mensaje": mensaje})
        except Exception as exc:
            ultimo = exc
            if llm_saturado(exc) and i < len(candidatos) - 1:
                print(
                    f" [LLM] saturado o sin endpoint; pruebo el siguiente "
                    f"({i + 2}/{len(candidatos)})",
                    flush=True,
                )
                continue
            if llm_saturado(exc):
                break
            raise
    raise RuntimeError(
        "Todos los modelos :free de OpenRouter están saturados (429). "
        "Espera unos minutos o pon en .env Groq/xAI, o un slug concreto en LLM_MODEL."
    ) from ultimo


def run_investigacion(mensaje: str, authorization: Optional[str] = None) -> Any:
    """Compat del paso 3."""
    return run_dominio("investigacion", mensaje, authorization=authorization)


def resultado_a_informe(resultado: Any) -> InformeCrew:
    """Normaliza la salida del kickoff al JSON del front."""
    texto = str(getattr(resultado, "raw", None) or resultado)
    pendiente_en_texto = "pendiente_confirmacion" in texto.lower()

    pydantic = getattr(resultado, "pydantic", None)
    if isinstance(pydantic, InformeCrew):
        informe = pydantic
    elif pydantic is not None:
        informe = InformeCrew.model_validate(pydantic)
    else:
        via_mcp = '"via": "mcp"' in texto or "via_mcp" in texto
        via_sandbox = '"via": "sandbox"' in texto or "via_sandbox" in texto or pendiente_en_texto
        fuente = "sandbox" if via_sandbox else ("mcp" if via_mcp else "agente")
        informe = InformeCrew(
            resumen=texto[:2000],
            tools_usadas=[],
            via_mcp=via_mcp,
            via_sandbox=via_sandbox,
            fuente_tools=fuente,
            hallazgos=texto[:4000],
            pendiente_confirmacion=pendiente_en_texto,
        )

    if pendiente_en_texto:
        informe = informe.model_copy(update={"pendiente_confirmacion": True, "via_sandbox": True})
    if informe.pendiente_confirmacion and not informe.via_sandbox:
        informe = informe.model_copy(update={"pendiente_confirmacion": False})
    return informe


if __name__ == "__main__":
    import os
    import sys

    jwt = os.getenv("CREW_JWT")
    if jwt:
        set_authorization(jwt if jwt.startswith("Bearer ") else f"Bearer {jwt}")

    dominio = sys.argv[1] if len(sys.argv) > 1 else "investigacion"
    pregunta = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "¿Cuántos eventos publicados hay? Lista nombres y no inventes."
    )
    try:
        resultado = run_dominio(dominio, pregunta)
    except RuntimeError as exc:
        print(f" {exc}")
        sys.exit(1)
    print("--- resultado ---")
    print(resultado)
    pydantic = getattr(resultado, "pydantic", None)
    if pydantic is not None:
        print("--- pydantic ---")
        print(pydantic.model_dump_json(indent=2))
