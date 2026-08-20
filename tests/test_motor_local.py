"""Pruebas del motor local: intenciones, rutinas y quices.

Cubren lo que debe funcionar sin LLM y sin los demás microservicios.
Ejecutar con `pytest` o directamente con `python tests/test_motor_local.py`.
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.data.ejercicios import CATALOGO_EJERCICIOS  # noqa: E402
from app.data.quiz_banco import BANCOS  # noqa: E402
from app.motor.rutinas import generar_rutina  # noqa: E402
from app.nlp.discapacidad import canonizar, coincide  # noqa: E402
from app.nlp.intenciones import clasificar  # noqa: E402
from app.nlp.texto import normalizar  # noqa: E402


def test_normalizacion_quita_acentos_y_signos():
    assert normalizar("¿Qué rutinas hay?") == "que rutinas hay"
    assert normalizar("Adaptación FÍSICA") == "adaptacion fisica"


def test_intenciones_reconocen_frases_naturales():
    esperado = {
        "¿Qué rutinas hay para mí?": "rutinas",
        "Hola!": "saludo",
        "buenas tardes": "saludo",
        "me duele el hombro al entrenar": "lesiones",
        "cuantas veces por semana debo entrenar": "frecuencia",
        "¿Qué eventos hay disponibles?": "eventos",
        "¿cómo me inscribo a un evento?": "inscripcion",
        "quiero ser entrenador verificado": "verificacion_entrenador",
        "¿qué deportes puedo practicar?": "deportes",
        "¿cómo se adapta la natación?": "adaptaciones",
        "no tengo ganas de entrenar": "motivacion",
        "¿qué material necesito?": "equipamiento",
        "¿qué es InkluSport?": "plataforma",
        "quiero hacer el quiz de organizador": "quiz",
        "¿cómo estiro después de entrenar?": "estiramiento",
        "¿qué debo comer antes de entrenar?": "nutricion",
        "gracias!": "agradecimiento",
        "adiós": "despedida",
        "crea un evento de natación": "crear_evento",
        "mi progreso": "progreso",
    }
    fallos = []
    for mensaje, intencion in esperado.items():
        obtenida = clasificar(mensaje)["nombre"]
        if obtenida != intencion:
            fallos.append(f"{mensaje!r}: esperaba {intencion}, obtuvo {obtenida}")
    assert not fallos, "Intenciones mal clasificadas:\n" + "\n".join(fallos)


def test_mensaje_fuera_de_dominio_no_se_clasifica():
    assert clasificar("¿cuál es la capital de Francia?")["nombre"] is None


def test_canonizacion_de_discapacidad():
    assert canonizar("Discapacidad Visual") == "visual"
    assert canonizar("fisica") == "motriz"
    assert canonizar("Pérdida parcial o total de visión") == "visual"
    assert canonizar(None) == "general"
    assert coincide("visual", "Discapacidad Visual") is True
    assert coincide("visual", "Discapacidad Auditiva") is False


def test_rutinas_distintas_en_llamadas_sucesivas():
    firmas = set()
    for _ in range(8):
        rutina = generar_rutina(discapacidad="visual", objetivo_texto="fuerza")
        firmas.add(tuple(e["id"] for e in rutina["ejercicios"]))
    assert len(firmas) > 1, "El motor devolvió siempre la misma combinación de ejercicios"


def test_rutina_reproducible_con_semilla():
    a = generar_rutina(discapacidad="visual", objetivo_texto="fuerza", semilla=99)
    b = generar_rutina(discapacidad="visual", objetivo_texto="fuerza", semilla=99)
    assert [e["id"] for e in a["ejercicios"]] == [e["id"] for e in b["ejercicios"]]


def test_rutina_motriz_excluye_ejercicios_de_pie():
    rutina = generar_rutina(discapacidad="motriz", objetivo_texto="fuerza")
    posiciones = {e["posicion"] for e in rutina["ejercicios"]}
    assert "de_pie" not in posiciones
    assert rutina["ejercicios"], "La rutina no debería quedar vacía"


def test_rutina_tiene_los_tres_bloques_y_adaptaciones():
    rutina = generar_rutina(discapacidad="auditiva", objetivo_texto="resistencia")
    fases = [b["fase"] for b in rutina["bloques"]]
    assert fases == ["calentamiento", "principal", "vuelta_a_la_calma"]
    assert all(e["adaptaciones"] for e in rutina["ejercicios"])
    assert rutina["duracion_estimada_minutos"] > 0


def test_objetivo_influye_en_la_seleccion():
    fuerza = generar_rutina(discapacidad="general", objetivo_texto="ganar fuerza", semilla=1)
    flexibilidad = generar_rutina(discapacidad="general", objetivo_texto="flexibilidad", semilla=1)
    assert [e["id"] for e in fuerza["ejercicios"]] != [e["id"] for e in flexibilidad["ejercicios"]]


def test_catalogo_de_ejercicios_es_consistente():
    identificadores = [e["id"] for e in CATALOGO_EJERCICIOS]
    assert len(identificadores) == len(set(identificadores)), "Hay ids duplicados"
    fases = {"calentamiento", "principal", "vuelta_a_la_calma"}
    for ejercicio in CATALOGO_EJERCICIOS:
        assert ejercicio["fase"] in fases
        assert ejercicio["series"] >= 1
        assert ejercicio["instrucciones"]


def test_banco_de_quiz_es_consistente():
    for rol, banco in BANCOS.items():
        identificadores = [p["id"] for p in banco]
        assert len(identificadores) == len(set(identificadores)), f"ids duplicados en {rol}"
        assert len(banco) >= 20, f"El banco de {rol} es demasiado pequeño"
        for pregunta in banco:
            opciones = pregunta["opciones"]
            assert len(opciones) >= 3
            assert len(set(opciones)) == len(opciones), f"opciones repetidas en {pregunta['id']}"
            assert 0 <= pregunta["correcta_indice"] < len(opciones)
            assert pregunta["explicacion"]


def test_barajado_de_opciones_conserva_la_respuesta_correcta():
    from app.agents.quiz_agent import QuizAgent

    azar = random.Random(7)
    for pregunta in BANCOS["ORGANIZADOR"][:10]:
        texto_correcto = pregunta["opciones"][pregunta["correcta_indice"]]
        barajada = QuizAgent._barajar_opciones(pregunta, azar)
        elegida = next(o for o in barajada["opciones"] if o["id"] == barajada["correcta"])
        assert elegida["texto"] == texto_correcto


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
