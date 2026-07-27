"""Verificación end-to-end del asistente de IA.

Recorre todos los endpoints y comprueba lo que el servicio debe garantizar:
respuestas distintas según la intención, rutinas que no se repiten, eventos
recomendados y quices generados y evaluados automáticamente.

Uso:
    python scripts/prueba_e2e.py [--base http://localhost:3008] [--usuario <id>]
"""

import argparse
import json
import sys

import httpx

PREGUNTAS = [
    "Hola",
    "¿Qué puedes hacer?",
    "¿Qué rutinas hay para mí?",
    "¿Qué eventos hay disponibles?",
    "¿Cómo me inscribo a un evento?",
    "¿Qué deportes puedo practicar?",
    "¿Cómo se adapta la natación para discapacidad visual?",
    "Me duele el hombro cuando entreno",
    "¿Cuántas veces por semana debo entrenar?",
    "No tengo ganas de entrenar",
    "¿Qué debo comer antes de entrenar?",
    "Quiero ser entrenador verificado",
    "Quiero organizar un evento",
    "¿Cómo funciona el quiz de aptitud?",
    "¿Qué material necesito para empezar?",
    "¿Cómo estiro después de entrenar?",
    "¿Qué es InkluSport?",
    "¿La aplicación es accesible con lector de pantalla?",
    "Quiero ver mi progreso",
    "Gracias",
]

# Preguntas que antes caían en el fallback genérico o se clasificaban mal.
# Ninguna debe quedar sin respuesta útil.
PREGUNTAS_ABIERTAS = [
    "¿Cuál es la capital de Francia?",
    "cuéntame un chiste",
    "¿Puedo entrenar si estoy embarazada?",
    "tengo 45 años y diabetes, ¿puedo entrenar?",
    "necesito bajar 10 kilos",
    "¿qué tal si hacemos ejercicio en la playa?",
    "¿cómo respiro al hacer fuerza?",
    "¿cuánto debo descansar entre sesiones?",
    "por dónde empiezo, nunca he entrenado",
    "¿quién ganó el mundial de 2022?",
]

DISCAPACIDADES = ("visual", "auditiva", "motriz", "cognitiva", "intelectual", "multiple")

fallos: list[str] = []


def comprobar(condicion: bool, mensaje: str) -> None:
    if condicion:
        print(f"    OK  {mensaje}")
    else:
        fallos.append(mensaje)
        print(f"    FALLA {mensaje}")


def titulo(texto: str) -> None:
    print(f"\n{'=' * 78}\n{texto}\n{'=' * 78}")


def probar_estado(cliente: httpx.Client) -> None:
    titulo("1. Estado del servicio")
    salud = cliente.get("/api/ai/health").json()
    print(json.dumps(salud, ensure_ascii=False, indent=2))
    comprobar(salud["status"] == "healthy", "El servicio responde como healthy")
    comprobar(
        salud["motor_local"]["ejercicios_en_catalogo"] >= 30,
        "El catálogo tiene al menos 30 ejercicios",
    )
    comprobar(salud["motor_local"]["intenciones"] >= 20, "Hay al menos 20 intenciones")

    diagnostico = cliente.get("/api/ai/diagnostico").json()
    print("\nDiagnóstico de dependencias:")
    for nombre, datos in diagnostico["servicios"].items():
        print(f"  {nombre}: {datos}")
    print(f"  mongodb: {diagnostico['mongodb']}")
    print(f"  llm: modo={diagnostico['llm']['modo']} proveedor={diagnostico['llm']['proveedor']} "
          f"modelo={diagnostico['llm']['modelo']}")

    if not salud["llm"]["configurado"]:
        print("\n  AVISO: no hay LLM configurado. Pon LLM_API_KEY en "
              "ink-ms-ai-assistant/.env (clave gratuita en https://openrouter.ai/keys). "
              "Sin LLM el chat responde el dominio deportivo, pero no preguntas ajenas.")
    comprobar(
        salud["llm"]["disponible"],
        "El LLM responde (necesario para las preguntas abiertas del chat)",
    )
    for nombre in ("users", "sports"):
        comprobar(
            diagnostico["servicios"].get(nombre, {}).get("alcanzable") is True,
            f"El microservicio {nombre} es alcanzable",
        )


def probar_chat(cliente: httpx.Client) -> None:
    titulo("2. Chatbot: una respuesta distinta por intención")
    respuestas = []
    intenciones = []

    for pregunta in PREGUNTAS:
        datos = cliente.post(
            "/api/ai/chat/",
            json={"mensaje": pregunta, "usuario_id": "prueba-e2e", "disability_type": "visual"},
        ).json()
        respuestas.append(datos["respuesta"])
        intenciones.append(datos["intencion"])
        primera_linea = datos["respuesta"].splitlines()[0]
        print(f"  · {pregunta}")
        print(f"      intención={datos['intencion']} (conf. {datos['confianza']}) "
              f"fuente={datos['fuente']}")
        print(f"      {primera_linea[:120]}")

    comprobar(len(set(respuestas)) >= 15, "Las respuestas no se repiten entre intenciones")
    comprobar(len(set(intenciones)) >= 15, "Se detectan al menos 15 intenciones distintas")
    comprobar(
        intenciones.count("fallback") == 0,
        "Ninguna respuesta cae en el fallback genérico antiguo",
    )
    comprobar(
        "no_entendido" not in intenciones,
        "Ninguna pregunta del dominio queda sin entender",
    )

    print("\n  Comprobando que el chat trae datos reales de eventos:")
    datos = cliente.post(
        "/api/ai/chat/",
        json={"mensaje": "¿Qué eventos hay disponibles?", "usuario_id": "prueba-e2e",
              "disability_type": "visual"},
    ).json()
    print("  " + datos["respuesta"].replace("\n", "\n  "))
    comprobar(
        bool(datos.get("datos", {}).get("eventos")),
        "La respuesta sobre eventos incluye eventos reales",
    )

    print("\n  Comprobando variación de redacción al repetir el saludo:")
    saludos = []
    for _ in range(3):
        saludos.append(
            cliente.post(
                "/api/ai/chat/",
                json={"mensaje": "Hola", "usuario_id": "prueba-rotacion"},
            ).json()["respuesta"]
        )
    for saludo in saludos:
        print(f"      {saludo[:100]}")
    comprobar(len(set(saludos)) > 1, "El saludo se redacta de varias maneras")


def probar_preguntas_abiertas(cliente: httpx.Client) -> None:
    titulo("2b. Chatbot: preguntas fuera del guion")
    sin_entender = []
    fuentes = []

    for pregunta in PREGUNTAS_ABIERTAS:
        datos = cliente.post(
            "/api/ai/chat/",
            json={"mensaje": pregunta, "usuario_id": "prueba-abierta",
                  "disability_type": "visual"},
        ).json()
        fuentes.append(datos["fuente"])
        if datos["intencion"] == "no_entendido":
            sin_entender.append(pregunta)
        print(f"  · {pregunta}")
        print(f"      intención={datos['intencion']} fuente={datos['fuente']}")
        print(f"      {datos['respuesta'][:180]}")

    comprobar(
        not sin_entender,
        f"Todas las preguntas abiertas reciben respuesta útil "
        f"(sin resolver: {sin_entender})",
    )
    comprobar(
        "llm" in fuentes,
        "El LLM responde al menos una pregunta abierta (¿hay LLM_API_KEY configurada?)",
    )


def probar_rutinas_por_discapacidad(cliente: httpx.Client, usuario: str) -> None:
    titulo("3b. Rutinas: cada discapacidad recibe una sesión distinta")
    firmas: dict[str, tuple] = {}
    recomendaciones: dict[str, str] = {}

    for discapacidad in DISCAPACIDADES:
        rutina = cliente.post(
            "/api/ai/rutinas/generar",
            json={
                "usuario_id": usuario,
                "tipo": "general",
                "objetivo": "general",
                "discapacidad": discapacidad,
                # Semilla fija: si aun así cambian, es por la discapacidad y no por azar
                "semilla": 1,
            },
        ).json()
        firmas[discapacidad] = tuple(e["id"] for e in rutina["ejercicios"])
        recomendaciones[discapacidad] = str(rutina["recomendaciones"])
        posiciones = sorted({e["posicion"] for e in rutina["ejercicios"]})
        print(f"\n  {discapacidad}: {rutina['nombre']}")
        print(f"      posiciones={posiciones} series={[e['series'] for e in rutina['ejercicios']]}")
        print(f"      {', '.join(e['nombre'] for e in rutina['ejercicios'][:4])}...")

    repetidas = [
        f"{a} == {b}"
        for i, a in enumerate(DISCAPACIDADES)
        for b in DISCAPACIDADES[i + 1:]
        if firmas[a] == firmas[b]
    ]
    comprobar(
        not repetidas,
        f"Ninguna pareja de discapacidades recibe la misma rutina (repetidas: {repetidas})",
    )
    comprobar(
        len(set(recomendaciones.values())) == len(DISCAPACIDADES),
        "Las recomendaciones son específicas de cada discapacidad",
    )

    for discapacidad in ("motriz", "multiple"):
        rutina = cliente.post(
            "/api/ai/rutinas/generar",
            json={"usuario_id": usuario, "tipo": "en silla de ruedas",
                  "objetivo": "resistencia", "discapacidad": discapacidad},
        ).json()
        posiciones = {e["posicion"] for e in rutina["ejercicios"]}
        comprobar(
            "de_pie" not in posiciones,
            f"La rutina de {discapacidad} en silla no incluye ejercicios de pie",
        )


def probar_rutinas(cliente: httpx.Client, usuario: str) -> None:
    titulo("3. Rutinas: distintas en cada llamada y adaptadas")
    firmas = set()
    for indice in range(4):
        rutina = cliente.post(
            "/api/ai/rutinas/generar",
            json={
                "usuario_id": usuario,
                "tipo": "fuerza",
                "objetivo": "ganar fuerza",
                "duracion_minutos": 35,
            },
        ).json()
        nombres = [e["nombre"] for e in rutina["ejercicios"]]
        firmas.add(tuple(nombres))
        print(f"  Rutina {indice + 1}: {rutina['nombre']} "
              f"({rutina['duracion_estimada_minutos']} min, {len(nombres)} ejercicios)")
        for bloque in rutina["bloques"]:
            print(f"      {bloque['bloque']}: {', '.join(e['nombre'] for e in bloque['ejercicios'])}")

    comprobar(len(firmas) > 1, "Las rutinas cambian entre llamadas")

    motriz = cliente.post(
        "/api/ai/rutinas/generar",
        json={"usuario_id": usuario, "tipo": "en silla de ruedas",
              "objetivo": "resistencia", "discapacidad": "motriz"},
    ).json()
    posiciones = {e["posicion"] for e in motriz["ejercicios"]}
    print(f"\n  Rutina para discapacidad motriz · posiciones usadas: {sorted(posiciones)}")
    for ejercicio in motriz["ejercicios"][:3]:
        print(f"      {ejercicio['nombre']} -> {ejercicio['adaptaciones'][:110]}")
    comprobar("de_pie" not in posiciones, "La rutina motriz no incluye ejercicios de pie")
    comprobar(
        all(e["adaptaciones"] for e in motriz["ejercicios"]),
        "Todos los ejercicios llevan adaptación",
    )

    objetivos = {}
    for objetivo in ("fuerza", "flexibilidad", "equilibrio", "resistencia"):
        rutina = cliente.post(
            "/api/ai/rutinas/generar",
            json={"usuario_id": usuario, "tipo": objetivo, "objetivo": objetivo, "semilla": 5},
        ).json()
        objetivos[objetivo] = tuple(e["id"] for e in rutina["ejercicios"])
        print(f"  objetivo={objetivo:14} -> {', '.join(e['nombre'] for e in rutina['ejercicios'][:3])}...")
    comprobar(len(set(objetivos.values())) > 1, "El objetivo cambia los ejercicios elegidos")


def probar_eventos(cliente: httpx.Client, usuario: str) -> None:
    titulo("4. Recomendación de eventos")
    datos = cliente.get(f"/api/ai/recomendacion/eventos/{usuario}?limite=3").json()
    print(f"  Perfil: {datos['usuario']}")
    print(f"  Mensaje: {datos['mensaje']}")
    print(f"  Eventos disponibles: {datos.get('total_eventos_disponibles')} · "
          f"compatibles: {datos.get('eventos_compatibles')}")
    for recomendacion in datos["recomendaciones"]:
        print(f"\n  - {recomendacion['evento']} ({recomendacion['deporte']})")
        print(f"      fecha={recomendacion['fecha']} lugar={recomendacion['ubicacion']} "
              f"cupos={recomendacion['cupos_disponibles']} puntaje={recomendacion['puntaje']}")
        print(f"      razón: {recomendacion['razon']}")
        for adaptacion in recomendacion["adaptaciones"]:
            print(f"      adaptación ({adaptacion['discapacidad']}): {adaptacion['adaptacion']}")

    comprobar(bool(datos["recomendaciones"]), "Se recomiendan eventos")
    comprobar(
        datos.get("total_eventos_disponibles", 0) > 0,
        "Hay eventos publicados en ink-ms-sports",
    )
    if datos["recomendaciones"]:
        comprobar(
            any(r["compatible_discapacidad"] for r in datos["recomendaciones"]),
            "Al menos un evento recomendado tiene adaptaciones para el perfil",
        )


def probar_competencia(cliente: httpx.Client, usuario: str) -> None:
    titulo("5. Análisis de competencia")
    datos = cliente.get(f"/api/ai/competencia/analizar/{usuario}").json()
    print(f"  Usuario (desde ink-ms-users): {json.dumps(datos['usuario'], ensure_ascii=False)}")
    print(f"  Estadísticas: {json.dumps(datos['estadisticas'], ensure_ascii=False, indent=4)}")
    print("\n  Deportes compatibles (desde ink-ms-sports):")
    for deporte in datos.get("deportes_compatibles", []):
        print(f"    - {deporte['nombre']}")
        for adaptacion in deporte["adaptaciones"]:
            print(f"        {adaptacion['discapacidad']}: {adaptacion['adaptacion']}")
    print(f"\n  Ventajas:")
    for item in datos["ventajas"]:
        print(f"    + {item}")
    print(f"  Desventajas:")
    for item in datos["desventajas"]:
        print(f"    - {item}")
    print(f"  Recomendaciones:")
    for item in datos["recomendaciones"]:
        print(f"    > {item}")

    comprobar(
        datos["estadisticas"]["eventos_en_sistema"] > 0,
        "El análisis ve los eventos de ink-ms-sports",
    )
    comprobar(
        bool(datos["usuario"].get("fullName")) and datos["usuario"]["fullName"] != "Usuario",
        "El análisis lee el perfil real de ink-ms-users",
    )
    comprobar(
        bool(datos["usuario"].get("disability")),
        "El análisis conoce la discapacidad del perfil",
    )
    comprobar(
        bool(datos.get("deportes_compatibles")),
        "El análisis identifica los deportes compatibles con la discapacidad",
    )
    comprobar(
        any(d.get("adaptaciones") for d in datos.get("deportes_compatibles", [])),
        "El análisis trae las adaptaciones registradas de cada deporte",
    )
    comprobar(
        len(datos["ventajas"]) >= 2 and len(datos["recomendaciones"]) >= 2,
        "El análisis es sustantivo, no dos frases genéricas",
    )
    comprobar(
        datos["estadisticas"]["deportes_en_catalogo"] > 0,
        "El análisis ve el catálogo de deportes",
    )


def probar_quiz(
    cliente: httpx.Client, usuario: str, rol: str, ruta: str, umbral: float,
    mongo_uri: str = "",
) -> None:
    titulo(f"6. Quiz de {rol}")
    primero = cliente.post(
        f"/api/ai/quiz/{ruta}/generar",
        json={"usuario_id": usuario, "num_preguntas": 8, "dificultad": "media"},
    ).json()
    segundo = cliente.post(
        f"/api/ai/quiz/{ruta}/generar",
        json={"usuario_id": usuario, "num_preguntas": 8, "dificultad": "media"},
    ).json()

    print(f"  quiz_id={primero['quiz_id']} preguntas={primero['num_preguntas']} "
          f"umbral={primero['umbral_aprobacion']}")
    print(f"  contexto={json.dumps(primero['contexto'], ensure_ascii=False)}")
    for pregunta in primero["preguntas"][:3]:
        print(f"\n    [{pregunta['tema']}] {pregunta['enunciado']}")
        for opcion in pregunta["opciones"]:
            print(f"       {opcion['id']}) {opcion['texto']}")

    comprobar(primero["num_preguntas"] == 8, "Genera el número de preguntas pedido")
    comprobar(primero["umbral_aprobacion"] == umbral, f"El umbral de {rol} es {umbral}")
    comprobar(
        {p["id"] for p in primero["preguntas"]} != {p["id"] for p in segundo["preguntas"]},
        "Dos quices consecutivos no traen las mismas preguntas",
    )
    comprobar(
        all("correcta" not in p for p in primero["preguntas"]),
        "Las preguntas se entregan sin la respuesta correcta",
    )

    correctas = _respuestas_correctas(primero["quiz_id"], mongo_uri)
    if correctas is None:
        print("    (No se localizó el quiz en MongoDB: se evalúa con respuestas fijas. "
              "Usa --mongo-uri si el servicio guarda en otra instancia)")
        respuestas = [{"pregunta_id": p["id"], "opcion_id": "a"} for p in primero["preguntas"]]
        esperado_aprobado = None
    else:
        respuestas = [
            {"pregunta_id": pid, "opcion_id": letra} for pid, letra in correctas.items()
        ]
        esperado_aprobado = True

    evaluacion = cliente.post(
        f"/api/ai/quiz/{ruta}/evaluar",
        json={"usuario_id": usuario, "quiz_id": primero["quiz_id"], "respuestas": respuestas},
    ).json()
    print(f"\n  Evaluación: score={evaluacion['score']} correctas={evaluacion['correctas']}/"
          f"{evaluacion['total']} aprobado={evaluacion['aprobado']}")
    print(f"  Registrado en ink-ms-users: {evaluacion['score_registrado_en_users']}")
    print(f"  Siguiente paso: {evaluacion['siguiente_paso']}")
    if evaluacion["temas_a_reforzar"]:
        print(f"  Temas a reforzar: {evaluacion['temas_a_reforzar']}")

    if esperado_aprobado:
        comprobar(evaluacion["score"] == 100.0, "Respondiendo todo bien el puntaje es 100")
        comprobar(evaluacion["aprobado"] is True, "El quiz se marca como aprobado")
        comprobar(
            evaluacion["score_registrado_en_users"] is True,
            "El puntaje se registra en ink-ms-users",
        )

    repetida = cliente.post(
        f"/api/ai/quiz/{ruta}/evaluar",
        json={"usuario_id": usuario, "quiz_id": primero["quiz_id"], "respuestas": respuestas},
    )
    comprobar(repetida.status_code == 400, "No se puede evaluar dos veces el mismo quiz")

    alias = cliente.post(f"/api/ai/{ruta}/generar", json={"usuario_id": usuario})
    comprobar(alias.status_code == 200, f"El alias /api/ai/{ruta}/generar responde")


def _respuestas_correctas(quiz_id: str, uri_preferida: str = "") -> dict[str, str] | None:
    """Lee del almacén el quiz generado para poder comprobar el flujo completo.

    Se prueban varias URIs porque el servicio puede estar guardando en la
    instancia local o en la de Docker, que además pide credenciales.
    """
    try:
        from pymongo import MongoClient

        from app.config import settings
    except ImportError:
        return None

    candidatas = [uri_preferida] if uri_preferida else []
    candidatas += [settings.MONGODB_URI, *settings.MONGODB_URI_ALTERNATIVAS]

    for uri in candidatas:
        try:
            cliente = MongoClient(uri, serverSelectionTimeoutMS=2000)
            documento = cliente[settings.MONGODB_DB].quizzes_verificacion.find_one(
                {"quiz_id": quiz_id}
            )
        except Exception:
            continue
        if documento:
            return {p["id"]: p["correcta"] for p in documento["preguntas"]}
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:3008")
    parser.add_argument("--usuario", default="e68b3227-a44d-472e-b5c5-2825fcfcc090")
    parser.add_argument(
        "--mongo-uri",
        default="",
        help="MongoDB donde el servicio guarda los quices, para verificar el flujo de aprobación",
    )
    argumentos = parser.parse_args()

    # Timeout amplio: con el LLM local en CPU una respuesta abierta puede tardar.
    with httpx.Client(base_url=argumentos.base, timeout=180.0) as cliente:
        probar_estado(cliente)
        probar_chat(cliente)
        probar_preguntas_abiertas(cliente)
        probar_rutinas(cliente, argumentos.usuario)
        probar_rutinas_por_discapacidad(cliente, argumentos.usuario)
        probar_eventos(cliente, argumentos.usuario)
        probar_competencia(cliente, argumentos.usuario)
        probar_quiz(cliente, argumentos.usuario, "ORGANIZADOR", "organizer", 70.0,
                    argumentos.mongo_uri)
        probar_quiz(cliente, argumentos.usuario, "ENTRENADOR", "trainer", 75.0,
                    argumentos.mongo_uri)

    titulo("Resultado")
    if fallos:
        print(f"{len(fallos)} comprobación(es) fallida(s):")
        for fallo in fallos:
            print(f"  - {fallo}")
        return 1
    print("Todas las comprobaciones pasaron.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    raise SystemExit(main())
