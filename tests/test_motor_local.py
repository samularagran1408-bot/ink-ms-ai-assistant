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
    """Comprueba que se quitan acentos, mayúsculas y signos de interrogación."""
    assert normalizar("¿Qué rutinas hay?") == "que rutinas hay"
    assert normalizar("Adaptación FÍSICA") == "adaptacion fisica"


def test_intenciones_reconocen_frases_naturales():
    """Clasifica frases reales del usuario a la intención esperada."""
    esperado = {
        "¿Qué rutinas hay para mí?": "rutinas",
        "Hola!": "saludo",
        "buenas tardes": "saludo",
        "me duele el hombro al entrenar": "lesiones",
        "cuantas veces por semana debo entrenar": "frecuencia",
        "¿Qué eventos hay disponibles?": "eventos",
        "Evento más reciente en iniciar": "eventos",
        "cuál es el próximo evento": "eventos",
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
        "Exporta el dashboard a PDF": "exportar_pdf",
        "Lista los usuarios inactivos": "listar_usuarios",
        "exportar como pdf": "exportar_pdf",
        "exporta como pdf": "exportar_pdf",
        "crea un evento de natación": "crear_evento",
        "mi progreso": "progreso",
        "Crea un deporte de running": "crear_deporte",
        "Publica una rutina de fuerza": "crear_rutina",
        "¿Qué adaptaciones tiene la natación?": "adaptaciones",
    }
    fallos = []
    for mensaje, intencion in esperado.items():
        obtenida = clasificar(mensaje)["nombre"]
        if obtenida != intencion:
            fallos.append(f"{mensaje!r}: esperaba {intencion}, obtuvo {obtenida}")
    assert not fallos, "Intenciones mal clasificadas:\n" + "\n".join(fallos)


def test_mensaje_fuera_de_dominio_no_se_clasifica():
    """Una pregunta ajena al deporte no debe asignar intención local."""
    assert clasificar("¿cuál es la capital de Francia?")["nombre"] is None


def test_pedidos_admin_pdf_e_inactivos():
    """Detecta pedidos de PDF, auditoría e inactivos sin confundirlos entre sí."""
    from app.nlp.admin_pedido import (
        filtrar_usuarios,
        pide_exportar_pdf,
        pide_inactivos,
        pide_pdf_auditoria,
    )

    assert pide_exportar_pdf("exporta como pdf")
    assert pide_exportar_pdf("Exporta el dashboard a PDF")
    assert pide_pdf_auditoria("exportar los audit logs a PDF")
    assert not pide_pdf_auditoria("exporta como pdf")
    assert pide_inactivos("Lista los usuarios inactivos")
    assert not pide_inactivos("Lista los usuarios activos")

    usuarios = [
        {"fullName": "Ana", "isActive": True},
        {"fullName": "Luis", "isActive": False},
        {"fullName": "Mia", "isActive": False},
    ]
    inactivos = filtrar_usuarios(usuarios, solo_inactivos=True)
    assert [u["fullName"] for u in inactivos] == ["Luis", "Mia"]
    activos = filtrar_usuarios(usuarios, solo_activos=True)
    assert [u["fullName"] for u in activos] == ["Ana"]


def test_canonizacion_de_discapacidad():
    """Unifica etiquetas de discapacidad (visual, física→motriz, etc.)."""
    assert canonizar("Discapacidad Visual") == "visual"
    assert canonizar("fisica") == "motriz"
    assert canonizar("Pérdida parcial o total de visión") == "visual"
    assert canonizar(None) == "general"
    assert coincide("visual", "Discapacidad Visual") is True
    assert coincide("visual", "Discapacidad Auditiva") is False


def test_rutinas_distintas_en_llamadas_sucesivas():
    """Sin semilla, sucesivas llamadas no deben repetir siempre los mismos ejercicios."""
    firmas = set()
    for _ in range(8):
        rutina = generar_rutina(discapacidad="visual", objetivo_texto="fuerza")
        firmas.add(tuple(e["id"] for e in rutina["ejercicios"]))
    assert len(firmas) > 1, "El motor devolvió siempre la misma combinación de ejercicios"


def test_rutina_reproducible_con_semilla():
    """La misma semilla produce la misma rutina (útil para pruebas y debugging)."""
    a = generar_rutina(discapacidad="visual", objetivo_texto="fuerza", semilla=99)
    b = generar_rutina(discapacidad="visual", objetivo_texto="fuerza", semilla=99)
    assert [e["id"] for e in a["ejercicios"]] == [e["id"] for e in b["ejercicios"]]


def test_rutina_motriz_excluye_ejercicios_de_pie():
    """Con discapacidad motriz no deben entrar ejercicios en posición de pie."""
    rutina = generar_rutina(discapacidad="motriz", objetivo_texto="fuerza")
    posiciones = {e["posicion"] for e in rutina["ejercicios"]}
    assert "de_pie" not in posiciones
    assert rutina["ejercicios"], "La rutina no debería quedar vacía"


def test_rutina_tiene_los_tres_bloques_y_adaptaciones():
    """Toda rutina trae calentamiento, principal, vuelta a la calma y adaptaciones."""
    rutina = generar_rutina(discapacidad="auditiva", objetivo_texto="resistencia")
    fases = [b["fase"] for b in rutina["bloques"]]
    assert fases == ["calentamiento", "principal", "vuelta_a_la_calma"]
    assert all(e["adaptaciones"] for e in rutina["ejercicios"])
    assert rutina["duracion_estimada_minutos"] > 0


def test_objetivo_influye_en_la_seleccion():
    """Fuerza y flexibilidad no deben devolver la misma combinación de ejercicios."""
    fuerza = generar_rutina(discapacidad="general", objetivo_texto="ganar fuerza", semilla=1)
    flexibilidad = generar_rutina(discapacidad="general", objetivo_texto="flexibilidad", semilla=1)
    assert [e["id"] for e in fuerza["ejercicios"]] != [e["id"] for e in flexibilidad["ejercicios"]]


def test_catalogo_de_ejercicios_es_consistente():
    """Ids únicos, fase válida, series e instrucciones en cada ejercicio."""
    identificadores = [e["id"] for e in CATALOGO_EJERCICIOS]
    assert len(identificadores) == len(set(identificadores)), "Hay ids duplicados"
    fases = {"calentamiento", "principal", "vuelta_a_la_calma"}
    for ejercicio in CATALOGO_EJERCICIOS:
        assert ejercicio["fase"] in fases
        assert ejercicio["series"] >= 1
        assert ejercicio["instrucciones"]


def test_interpreta_objetivos_libres():
    """Reflejos, velocidad y agilidad son claves propias, no un alias de fuerza."""
    from app.motor.rutinas import interpretar_objetivo, interpretar_objetivos

    assert interpretar_objetivo("reflejos") == "reflejos"
    assert interpretar_objetivo("quiero mejorar mis reflejos") == "reflejos"
    assert interpretar_objetivo("velocidad") == "velocidad"
    assert interpretar_objetivo("agilidad") == "agilidad"
    assert interpretar_objetivo("potencia") == "potencia"
    assert interpretar_objetivo("coordinacion") == "coordinacion"
    assert interpretar_objetivo("fuerza") == "fuerza"
    prim, sec = interpretar_objetivos("reflejos", "agilidad")
    assert prim == "reflejos"
    assert sec == "agilidad"


def test_rutina_de_reflejos_elige_ejercicios_de_reaccion():
    """Una sesión de reflejos no se disfraza de hipertrofia."""
    from app.motor.rutinas import generar_rutina

    por_id = {e["id"]: e for e in CATALOGO_EJERCICIOS}
    reflejos = generar_rutina(
        "motriz", "reflejos", catalogo=CATALOGO_EJERCICIOS, semilla=7
    )
    fuerza = generar_rutina(
        "motriz", "fuerza", catalogo=CATALOGO_EJERCICIOS, semilla=7
    )
    assert reflejos["objetivo_clave"] == "reflejos"
    assert "reflejo" in reflejos["objetivo"].lower()
    principales = [
        e["id"] for e in reflejos["ejercicios"] if e.get("fase") == "principal" and e.get("id")
    ]
    tagged = [
        i for i in principales
        if "reflejos" in (por_id.get(i, {}).get("objetivos") or [])
    ]
    assert tagged, "La sesión de reflejos debe incluir ejercicios etiquetados así"
    assert reflejos["objetivo_clave"] != fuerza["objetivo_clave"]


def test_rutina_de_velocidad_no_cae_en_general():
    """Velocidad es un objetivo de primera clase."""
    from app.motor.rutinas import generar_rutina

    rutina = generar_rutina(
        "motriz", "velocidad", catalogo=CATALOGO_EJERCICIOS, semilla=9
    )
    assert rutina["objetivo_clave"] == "velocidad"
    assert "velocidad" in rutina["objetivo"].lower()


def test_banco_de_quiz_es_consistente():
    """Cada banco tiene ids únicos, ≥20 preguntas y una respuesta correcta válida."""
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


def test_mapa_corporal_marca_rodilla_izquierda():
    """Extrae zonas de dolor y marca limitación lumbar en el mapa corporal."""
    from app.motor.cuerpo import extraer_zonas, mapa_corporal, debe_dibujar

    assert "rodilla_izq" in extraer_zonas("me duele la rodilla izquierda")
    assert "rodilla_der" not in extraer_zonas("me duele la rodilla izquierda")
    assert set(extraer_zonas("dolor de hombros")) >= {"hombro_izq", "hombro_der"}
    assert debe_dibujar("me duele el hombro", None, "lesiones")
    mapa = mapa_corporal("pinchazo", "limitación lumbar")
    assert "lumbar" in mapa["zonas_dolor"]
    assert mapa["limitacion"] == "limitación lumbar"


def test_barajado_de_opciones_conserva_la_respuesta_correcta():
    """Tras barajar, el id marcado como correcto sigue apuntando al mismo texto."""
    from app.agents.quiz_agent import QuizAgent

    azar = random.Random(7)
    for pregunta in BANCOS["ORGANIZADOR"][:10]:
        texto_correcto = pregunta["opciones"][pregunta["correcta_indice"]]
        barajada = QuizAgent._barajar_opciones(pregunta, azar)
        elegida = next(o for o in barajada["opciones"] if o["id"] == barajada["correcta"])
        assert elegida["texto"] == texto_correcto


def test_quiz_se_arma_del_banco_sin_llm():
    """La generación de aptitud no depende de métodos LLM ni de catálogo extra."""
    from app.agents.quiz_agent import QuizAgent

    assert not hasattr(QuizAgent, "_preguntas_llm")
    assert not hasattr(QuizAgent, "_contexto_catalogo")
    agent = QuizAgent()
    assert not hasattr(agent, "llm")
    azar = random.Random(3)
    preguntas = agent._muestrear(BANCOS["ENTRENADOR"], 8, "media", azar)
    assert len(preguntas) == 8


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
