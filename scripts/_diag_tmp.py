"""Diagnóstico temporal de las quejas reportadas."""
import json
import httpx

BASE = "http://localhost:3008"
USUARIO = "e68b3227-a44d-472e-b5c5-2825fcfcc090"

with httpx.Client(base_url=BASE, timeout=60.0) as c:
    print("=" * 70)
    print("A. RUTINAS: ¿cambian las recomendaciones segun discapacidad?")
    print("=" * 70)
    for disc in ("visual", "auditiva", "motriz", "cognitiva", "intelectual", "multiple", "general"):
        r = c.post("/api/ai/rutinas/generar", json={
            "usuario_id": USUARIO, "tipo": "general", "objetivo": "general",
            "discapacidad": disc, "semilla": 1,
        }).json()
        print(f"\n--- {disc} ---")
        print(f"  nombre        : {r['nombre']}")
        print(f"  recomendaciones: {r['recomendaciones']}")
        print(f"  posicion      : {r['posicion_predominante']}")
        print(f"  ejercicios    : {[e['nombre'] for e in r['ejercicios']]}")
        print(f"  posiciones    : {sorted({e['posicion'] for e in r['ejercicios']})}")
        print(f"  avisos        : {r['avisos_seguridad'][:2]}")
        print(f"  nota_llm      : {r.get('nota_personalizada')}")

    print("\n" + "=" * 70)
    print("B. CHAT: preguntas fuera del guion")
    print("=" * 70)
    fuera = [
        "¿Cuál es la capital de Francia?",
        "cuentame un chiste",
        "que tal si hacemos ejercicio en la playa",
        "tengo 45 años y diabetes, puedo entrenar?",
        "asdkjhasd",
        "¿Puedo entrenar si estoy embarazada?",
        "cual es el mejor deporte para mi",
        "quien creo inklusport",
        "necesito bajar 10 kilos",
        "hola como estas hoy",
    ]
    for q in fuera:
        d = c.post("/api/ai/chat/", json={"mensaje": q, "usuario_id": "diag", "disability_type": "visual"}).json()
        print(f"\n  P: {q}")
        print(f"     intencion={d['intencion']} conf={d['confianza']} fuente={d['fuente']}")
        print(f"     R: {d['respuesta'][:250]}")

    print("\n" + "=" * 70)
    print("C. COMPETENCIA por discapacidad")
    print("=" * 70)
    d = c.get(f"/api/ai/competencia/analizar/{USUARIO}").json()
    print(json.dumps({k: d[k] for k in ("estadisticas", "ventajas", "desventajas", "recomendaciones", "usuario", "filtro")}, ensure_ascii=False, indent=2))
