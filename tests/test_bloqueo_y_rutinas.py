"""Bloqueo admin (destino) y unicidad de ejercicios entre objetivos.

    python tests/test_bloqueo_y_rutinas.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.ejercicios import CATALOGO_EJERCICIOS  # noqa: E402
from app.motor.rutinas import generar_rutina  # noqa: E402
from app.nlp.admin_pedido import (  # noqa: E402
    coincidencias_usuario,
    extraer_destino_bloqueo,
    pide_desbloqueo,
)
from app.nlp.intenciones import clasificar  # noqa: E402


def test_extraer_destino_por_email():
    assert extraer_destino_bloqueo("Bloquear a ana@correo.com") == "ana@correo.com"


def test_dificultad_deporte_enum_sports():
    from app.agents.chatbot_agent import ChatbotAgent

    assert ChatbotAgent._dificultad_deporte("intermedio") == "medio"
    assert ChatbotAgent._dificultad_deporte("intermediate") == "medio"
    assert ChatbotAgent._dificultad_deporte("bajo") == "bajo"
    assert ChatbotAgent._dificultad_deporte("avanzado") == "alto"


def test_llm_reintenta_modelo_invalido():
    from app.services.llm_service import _es_modelo_reintentable

    assert _es_modelo_reintentable(400, "is not a valid model") is True
    assert _es_modelo_reintentable(429, "rate-limited") is True
    assert _es_modelo_reintentable(401, "unauthorized") is False


def test_cuota_free_diaria_salta_modelos_de_pago():
    import time

    from app.services.llm_service import (
        LLMService,
        _es_cuota_free_diaria,
        _es_modelo_free,
        _segundos_hasta_reset_cuota,
    )

    assert _es_modelo_free("google/gemma-4-26b-a4b-it:free") is True
    assert _es_modelo_free("openai/gpt-oss-20b") is False
    cuerpo = (
        '{"error":{"message":"Rate limit exceeded: free-models-per-day",'
        '"code":429,"metadata":{"headers":{"X-RateLimit-Reset":"1788912000000"}}}}'
    )
    assert _es_cuota_free_diaria(429, cuerpo) is True
    assert _segundos_hasta_reset_cuota(cuerpo) >= 60
    LLMService._free_cuota_hasta = time.time() + 3600
    try:
        svc = LLMService()
        svc.proveedor = "openrouter"
        svc.model = "google/gemma-4-26b-a4b-it:free"
        modelos = svc._modelos_a_probar()
        assert modelos
        assert all(not m.endswith(":free") for m in modelos)
        assert "openai/gpt-oss-20b" in modelos
    finally:
        LLMService._free_cuota_hasta = 0.0


def test_intencion_floja_va_al_chat_abierto():
    from app.agents.chatbot_agent import ChatbotAgent

    assert ChatbotAgent._intencion_local_firme({"nombre": None, "confianza": 0.9}) is False
    assert ChatbotAgent._intencion_local_firme({"nombre": "deportes", "confianza": 0.4}) is False
    assert ChatbotAgent._intencion_local_firme({"nombre": "deportes", "confianza": 0.82}) is True
    assert ChatbotAgent._intencion_local_firme({"nombre": "crear_deporte", "confianza": 0.4}) is True


def test_respuesta_abierta_no_dice_no_entendi():
    from app.agents.chatbot_agent import ChatbotAgent
    from app.data.conocimiento import NO_ENTENDIDO, NO_ENTENDIDO_ADAPTADO

    texto = ChatbotAgent._respuesta_abierta_sin_llm(
        "¿cuál es la capital de Francia?", "general"
    )
    bajo = texto.lower()
    assert "no entend" not in bajo
    assert "se me escapa" not in bajo
    assert "no logro" not in bajo
    assert "vamos con" not in bajo
    assert "capital francia" not in bajo
    for frase in NO_ENTENDIDO + list(NO_ENTENDIDO_ADAPTADO.values()):
        f = frase.lower()
        assert "no entend" not in f
        assert "se me escapa" not in f
        assert "no estoy seguro" not in f


def test_proximo_evento_es_por_fecha_no_por_inscritos():
    from datetime import date

    from app.nlp.eventos_pedido import (
        criterio_ranking_evento,
        evento_mas_inscritos,
        proximo_a_iniciar,
    )

    assert criterio_ranking_evento("Evento más reciente en iniciar") == "proximo"
    assert criterio_ranking_evento("cuál es el próximo evento") == "proximo"
    assert criterio_ranking_evento("el de más inscritos") == "mas_inscritos"

    eventos = [
        {
            "name": "Torneo Amistoso de Baloncesto en Silla",
            "eventDate": "2026-09-21",
            "location": "Polideportivo Parque Simón Bolívar",
            "maxCapacity": 20,
            "availableCapacity": 16,
        },
        {
            "name": "3 km",
            "sportName": "Running",
            "eventDate": "2026-09-10",
            "location": "Colegio del Sur Calarcá",
            "maxCapacity": 24,
            "availableCapacity": 24,
        },
        {
            "name": "Jornada inclusiva de Fútbol Sala",
            "eventDate": "2026-09-12",
            "maxCapacity": 24,
            "availableCapacity": 23,
        },
    ]
    hoy = date(2026, 9, 10)
    proximo = proximo_a_iniciar(eventos, hoy)
    popular = evento_mas_inscritos(eventos)
    assert proximo["name"] == "3 km"
    assert popular["name"] == "Torneo Amistoso de Baloncesto en Silla"


def test_unir_continuacion_pega_palabra_cortada():
    from app.services.llm_service import _unir_continuacion

    assert (
        _unir_continuacion("en el Polideport", "ivo Municipal.")
        == "en el Polideportivo Municipal."
    )
    assert (
        _unir_continuacion("en el Polideport", "Polideportivo Municipal.")
        == "en el Polideportivo Municipal."
    )


def test_fallo_duro_no_incluye_429():
    import httpx

    from app.services.llm_service import _es_error_red, _es_fallo_duro

    assert _es_fallo_duro(401, "unauthorized") is True
    assert _es_fallo_duro(429, "rate-limited") is False
    assert _es_error_red(httpx.TimeoutException("timed out")) is True


def _reset_llm_estado() -> None:
    from app.services.llm_service import LLMService

    LLMService._bloqueado_hasta = 0.0
    LLMService._free_cuota_hasta = 0.0
    LLMService._ultimo_error = None
    LLMService._sema = None
    LLMService._en_curso = 0


def _svc_openrouter():
    from app.services.llm_service import LLMService

    svc = LLMService()
    svc.habilitado = True
    svc.api_key = "sk-or-test"
    svc.api_url = "https://openrouter.ai/api/v1/chat/completions"
    svc.proveedor = "openrouter"
    svc.model = "google/gemma-4-26b-a4b-it:free"
    svc.timeout = 5
    return svc


def test_timeout_prueba_siguiente_modelo():
    """Un timeout del :free no debe activar cooldown ni abortar el turno."""
    import asyncio
    import json
    import time
    from unittest.mock import patch

    import httpx

    from app.config import settings
    from app.services.llm_service import LLMService

    class FakeResp:
        def __init__(self, status, data=None):
            self.status_code = status
            self._data = data or {}
            self.text = json.dumps(self._data)

        def json(self):
            return self._data

    ok = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "Respuesta completa."},
            }
        ]
    }
    posts = [httpx.TimeoutException("timed out"), FakeResp(200, ok)]

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            item = posts.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    async def _noop(_intento: int) -> None:
        return None

    _reset_llm_estado()
    prev_reint = settings.LLM_REINTENTOS_POR_MODELO
    settings.LLM_REINTENTOS_POR_MODELO = 0
    try:
        svc = _svc_openrouter()

        async def run():
            with patch(
                "app.services.llm_service.httpx.AsyncClient",
                side_effect=lambda *a, **k: FakeClient(),
            ), patch("app.services.llm_service._esperar_reintento", _noop):
                return await svc.completar([{"role": "user", "content": "hola"}])

        resultado = asyncio.run(run())
        assert resultado.content == "Respuesta completa."
        assert LLMService._bloqueado_hasta <= time.monotonic()
        assert LLMService._ultimo_error is None
    finally:
        settings.LLM_REINTENTOS_POR_MODELO = prev_reint
        _reset_llm_estado()


def test_continuacion_si_finish_reason_length():
    import asyncio
    import json
    from unittest.mock import patch

    from app.config import settings
    from app.services.llm_service import LLMService

    class FakeResp:
        def __init__(self, status, data=None):
            self.status_code = status
            self._data = data or {}
            self.text = json.dumps(self._data)

        def json(self):
            return self._data

    cortado = {
        "choices": [
            {
                "finish_reason": "length",
                "message": {
                    "role": "assistant",
                    "content": "Tu próximo evento es en el Polideport",
                },
            }
        ]
    }
    resto = {
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": "ivo Municipal."},
            }
        ]
    }
    posts = [FakeResp(200, cortado), FakeResp(200, resto)]

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, *a, **k):
            return posts.pop(0)

    _reset_llm_estado()
    prev_cont = settings.LLM_CONTINUACIONES_TRUNCADO
    settings.LLM_CONTINUACIONES_TRUNCADO = 2
    try:
        svc = _svc_openrouter()

        async def run():
            with patch(
                "app.services.llm_service.httpx.AsyncClient",
                side_effect=lambda *a, **k: FakeClient(),
            ):
                return await svc.completar([{"role": "user", "content": "evento"}])

        resultado = asyncio.run(run())
        assert resultado.content == "Tu próximo evento es en el Polideportivo Municipal."
        assert (resultado.finish_reason or "").lower() == "stop"
        assert LLMService._ultimo_error is None
    finally:
        settings.LLM_CONTINUACIONES_TRUNCADO = prev_cont
        _reset_llm_estado()


def test_extraer_destino_por_nombre():
    dest = extraer_destino_bloqueo("Bloquear a Samu Lara porque no asiste")
    assert "samu" in dest.lower()
    assert "porque" not in dest.lower()


def test_pide_desbloqueo():
    assert pide_desbloqueo("Activar a ana@correo.com") is True
    assert pide_desbloqueo("Bloquear a ana@correo.com") is False


def test_coincidencias_usuario_email():
    lista = [
        {"email": "ana@correo.com", "fullName": "Ana"},
        {"email": "bob@correo.com", "fullName": "Bob"},
    ]
    hits = coincidencias_usuario(lista, "ana@correo.com")
    assert len(hits) == 1
    assert hits[0]["fullName"] == "Ana"


def test_confirmo_en_frase():
    from app.tools.writes import es_confirmacion

    assert es_confirmacion("Confirmo") is True
    assert es_confirmacion("te confirmo") is True
    assert es_confirmacion("sí, confirmo el bloqueo") is True
    assert es_confirmacion("hola") is False
    clas = clasificar("Bloquear a ana@correo.com")
    assert clas["nombre"] == "bloquear_usuario"


def test_cancela_inscripcion_no_es_abortar_confirmo():
    from app.nlp.inscripcion_pedido import (
        coincidencias_inscripcion,
        extraer_nombre_evento,
    )
    from app.tools.writes import es_cancelacion

    pedido = "Cancela mi inscripción al evento de Festival Acuático Inclusivo"
    assert es_cancelacion("cancelar") is True
    assert es_cancelacion("cancela") is True
    assert es_cancelacion("Cancelar.") is True
    assert es_cancelacion(pedido) is False
    assert clasificar(pedido)["nombre"] == "cancelar_inscripcion"
    assert extraer_nombre_evento(pedido) == "Festival Acuático Inclusivo"
    hits = coincidencias_inscripcion(
        [
            {"id": "1", "eventName": "Festival Acuático Inclusivo"},
            {"id": "2", "eventName": "Copa de fútbol"},
        ],
        "Festival Acuático Inclusivo",
    )
    assert len(hits) == 1
    assert hits[0]["id"] == "1"


def _ids(rutina: dict) -> list[str]:
    return [str(e.get("id")) for e in (rutina.get("ejercicios") or []) if e.get("id")]


def _nombres(rutina: dict) -> set[str]:
    return {
        str(e.get("nombre") or "").strip().lower()
        for e in (rutina.get("ejercicios") or [])
        if e.get("nombre")
    }


def test_cupo_horario_avisa_y_luego_bloquea():
    """20 mensajes/hora: aviso al acercarse y 429 con espera de 1 hora al superar."""
    from fastapi import HTTPException

    from app.config import settings
    from app.services import chat_limite

    original = chat_limite._ahora
    original_espera = settings.CHAT_ESPERA_LIMITE_SEGUNDOS
    settings.CHAT_ESPERA_LIMITE_SEGUNDOS = 3600
    chat_limite._envios.clear()
    chat_limite._bloqueo_hasta.clear()
    chat_limite._en_curso.clear()
    uid = "tester-cupo"
    t0 = 1_700_000_000.0
    chat_limite._ahora = lambda: t0
    try:
        for i in range(16):
            estado = chat_limite.consumir_cupo_hora(uid)
            assert estado["usados"] == i + 1
            assert estado["aviso"] is None
        aviso = chat_limite.consumir_cupo_hora(uid)
        assert aviso["aviso"]
        assert "quedan" in aviso["aviso"]
        chat_limite.consumir_cupo_hora(uid)
        chat_limite.consumir_cupo_hora(uid)
        tope = chat_limite.consumir_cupo_hora(uid)
        assert tope["usados"] == 20
        assert tope["restantes"] == 0
        try:
            chat_limite.consumir_cupo_hora(uid)
            raise AssertionError("debía bloquear el mensaje 21")
        except HTTPException as exc:
            assert exc.status_code == 429
            assert isinstance(exc.detail, dict)
            assert exc.detail["codigo"] == "chat_limite_hora"
            assert "Espera" in exc.detail["mensaje"]
            assert "hora" in exc.detail["mensaje"].lower()
            assert exc.detail["retry_after_segundos"] >= 3500
        chat_limite._ahora = lambda: t0 + 3599
        try:
            chat_limite.consumir_cupo_hora(uid)
            raise AssertionError("aún debía estar bloqueado antes de 1 hora")
        except HTTPException as exc:
            assert exc.status_code == 429
        chat_limite._ahora = lambda: t0 + 3601
        otra = chat_limite.consumir_cupo_hora(uid)
        assert otra["usados"] == 1
        assert otra["aviso"] is None
    finally:
        settings.CHAT_ESPERA_LIMITE_SEGUNDOS = original_espera
        chat_limite._ahora = original
        chat_limite._envios.clear()
        chat_limite._bloqueo_hasta.clear()


def test_una_rutina_no_repite_ejercicios():
    rutina = generar_rutina(
        "motriz",
        "fuerza",
        catalogo=CATALOGO_EJERCICIOS,
        semilla=11,
    )
    ids = _ids(rutina)
    assert ids
    assert len(ids) == len(set(ids))
    assert len(_nombres(rutina)) == len(ids)


def test_objetivos_distintos_no_repite_ejercicios():
    fuerza = generar_rutina(
        "motriz", "fuerza", catalogo=CATALOGO_EJERCICIOS, semilla=21
    )
    usados = set(_ids(fuerza)) | _nombres(fuerza)
    movilidad = generar_rutina(
        "motriz",
        "movilidad",
        catalogo=CATALOGO_EJERCICIOS,
        semilla=22,
        excluir_ids=usados,
    )
    ids_b = _ids(movilidad)
    assert ids_b
    assert not (set(_ids(fuerza)) & set(ids_b))
    assert not (_nombres(fuerza) & _nombres(movilidad))


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
