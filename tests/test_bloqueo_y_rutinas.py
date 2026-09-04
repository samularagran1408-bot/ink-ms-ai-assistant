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
