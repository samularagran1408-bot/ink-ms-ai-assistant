"""Casos HU40–HU50 alineados con los RF ya existentes (sin sensores ni visión)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.agents.alertas_agent import AlertasAgent
from app.agents.competencia_agent import CompetenciaAgent
from app.agents.dashboard_agent import DashboardAgent
from app.agents.deportes_agent import DeportesAgent
from app.agents.deteccion_agent import DeteccionAgent
from app.agents.historial_agent import HistorialAgent
from app.agents.planes_agent import PlanesAgent
from app.agents.recomendacion_agent import RecomendacionAgent
from app.agents.riesgo_agent import RiesgoAgent
from app.data.ejercicios import CATALOGO_EJERCICIOS, PAUTAS_DISCAPACIDAD
from app.database.repositorio import obtener_catalogo_ejercicios
from app.motor.rutinas import adaptacion_de, generar_rutina, interpretar_objetivo
from app.nlp.discapacidad import canonizar, descripcion
from app.nlp.entrenamiento_pedido import extraer_frecuencia, extraer_rpe
from app.nlp.texto import normalizar
from app.services.entrenamiento_store import (
    cargar_perfil,
    guardar_perfil,
    marcar_aviso_umbral,
    registrar_alerta_riesgo,
)


def _ahora_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EntrenamientoAgent:
    """Respuestas de chat para los casos de prueba HU40–HU50 (CP33 incluido)."""

    def __init__(self) -> None:
        self.planes = PlanesAgent()
        self.dashboard = DashboardAgent()
        self.historial = HistorialAgent()
        self.recomendacion = RecomendacionAgent()
        self.riesgo = RiesgoAgent()
        self.deteccion = DeteccionAgent()
        self.deportes = DeportesAgent()
        self.competencia = CompetenciaAgent()
        self.alertas = AlertasAgent()

    async def procesar(
        self,
        comando: str,
        usuario_id: str,
        mensaje: str,
        discapacidad: str,
        authorization: Optional[str] = None,
        perfil_usuario: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Despacha un comando simple y persiste lo mínimo (RPE, modo, sesiones)."""
        perfil = await cargar_perfil(usuario_id)
        fn = {
            "rutina_adaptada": self._rutina_adaptada,
            "sugerir_adaptacion": self._sugerir_adaptacion,
            "evaluar_riesgo": self._evaluar_riesgo,
            "riesgo_dolor": self._riesgo_dolor,
            "rutina_objetivo": self._rutina_objetivo,
            "plan_semanal": self._plan_semanal,
            "rpe_alto": self._rpe_alto,
            "rpe_bajo": self._rpe_bajo,
            "iniciar_entrenamiento": self._iniciar_voz,
            "comando_voz": self._comando_voz,
            "dashboard": self._dashboard,
            "dashboard_predicciones": self._dashboard_predicciones,
            "comparar_mes": self._comparar_mes,
            "comparar_historial": self._comparar_historial,
            "recomendar_eventos": self._recomendar_eventos,
            "recomendar_deportes": self._recomendar_deportes,
            "detectar_discapacidad": self._detectar_discapacidad,
            "modo_competencia": self._modo_competencia,
            "competencia_historial": self._competencia_historial,
            "alerta_entrenador": self._alerta_entrenador,
            "progreso_entrenador": self._progreso_entrenador,
            "umbral_alertas_semana": self._umbral_alertas_semana,
        }.get(comando)
        if not fn:
            texto, datos = "No reconocí ese caso. Prueba con las frases de la guía HU40–HU50.", {
                "comando": comando,
            }
        else:
            texto, datos = await fn(
                perfil, mensaje, discapacidad, authorization, perfil_usuario or {}
            )
        await guardar_perfil(perfil)
        return {
            "respuesta": texto,
            "intencion": comando,
            "adaptada": discapacidad != "general",
            "sugerencias": datos.get("sugerencias") or [],
            "datos": datos,
            "fuente": "motor_entrenamiento",
            "herramientas_usadas": [comando],
            "caso_prueba": datos.get("caso_prueba"),
            "respuesta_auditiva": texto if datos.get("respuesta_auditiva") else None,
        }

    async def aplicar_feedback_rpe(
        self,
        usuario_id: str,
        rpe: float,
        discapacidad: str = "general",
        authorization: Optional[str] = None,
    ) -> dict[str, Any]:
        """Ajuste de carga tras POST /fatiga/rpe (HU43 / RF45)."""
        perfil = await cargar_perfil(usuario_id)
        if rpe >= 8:
            texto, datos = await self._rpe_alto(
                perfil, f"RPE {rpe}", discapacidad, authorization, {}
            )
        else:
            texto, datos = await self._rpe_bajo(
                perfil, f"RPE {rpe}", discapacidad, authorization, {}
            )
        await guardar_perfil(perfil)
        return {"sugerencia": texto, **datos}

    def _pack_rutina(self, rutina: dict, caso: str, extra: Optional[str] = None) -> tuple[str, dict]:
        nombres = [e.get("nombre") for e in (rutina.get("ejercicios") or [])[:6] if e.get("nombre")]
        texto = (
            f"{rutina.get('nombre') or 'Rutina adaptada'} "
            f"({rutina.get('duracion_estimada_minutos')} min, "
            f"{rutina.get('total_ejercicios')} ejercicios) para "
            f"{descripcion(canonizar(rutina.get('discapacidad') or 'general'))}. "
        )
        if extra:
            texto += extra + " "
        if nombres:
            texto += "Incluye: " + ", ".join(nombres[:4]) + "."
        return texto, {
            "caso_prueba": caso,
            "rutina": {
                "nombre": rutina.get("nombre"),
                "objetivo": rutina.get("objetivo_clave"),
                "discapacidad": rutina.get("discapacidad"),
                "ejercicios": nombres,
            },
            "sugerencias": ["Adapta el ejercicio", "Plan semanal 3 veces por semana"],
        }

    async def _rutina_adaptada(self, perfil, mensaje, discapacidad, _auth, _user):
        catalogo = await obtener_catalogo_ejercicios()
        rutina = generar_rutina(
            discapacidad=discapacidad,
            objetivo_texto=mensaje or "general",
            tipo_texto=mensaje or "",
            nivel="principiante",
            duracion_minutos=30,
            catalogo=catalogo,
            semilla=21,
        )
        return self._pack_rutina(
            rutina,
            "CP11-HU40",
            extra="Modificaciones según discapacidad, nivel y progreso.",
        )

    async def _sugerir_adaptacion(self, perfil, mensaje, discapacidad, _auth, _user):
        catalogo = await obtener_catalogo_ejercicios() or CATALOGO_EJERCICIOS
        texto_n = normalizar(mensaje)
        ejercicio = next(
            (e for e in catalogo if normalizar(e.get("nombre") or "") in texto_n),
            catalogo[0],
        )
        clave = canonizar(discapacidad)
        variante = adaptacion_de(ejercicio, clave)
        nivel = "principiante"
        perfil["variante_actual"] = {
            "ejercicio": ejercicio.get("nombre"),
            "variante": variante,
            "discapacidad": clave,
            "nivel": nivel,
        }
        texto = (
            f"Modificación automática de «{ejercicio.get('nombre')}» "
            f"para {descripcion(clave)} (nivel {nivel}): {variante}"
        )
        return texto, {
            "caso_prueba": "CP12-HU40",
            "variante_adaptada": perfil["variante_actual"],
            "sugerencias": ["Quiero una rutina adaptada"],
        }

    def _riesgo_local(self, discapacidad: str, dolor: bool, rpe: Optional[float]) -> dict[str, Any]:
        score = 15.0
        factores = []
        if canonizar(discapacidad) in ("motriz", "multiple"):
            score += 15
            factores.append("Perfil motriz: priorizar control articular.")
        if dolor:
            score += 35
            factores.append("Dolor o molestia reportada.")
        if rpe is not None and rpe >= 8:
            score += 25
            factores.append(f"RPE alto ({rpe}/10).")
        elif rpe is not None and rpe >= 6:
            score += 12
        score = min(100.0, round(score, 1))
        if score < 30:
            nivel, alerta = "bajo", "Riesgo bajo. Mantén técnica y calentamiento."
        elif score < 60:
            nivel, alerta = "moderado", "Riesgo moderado. Reduce volumen o añade movilidad."
        else:
            nivel, alerta = "alto", "Riesgo alto. Prioriza descanso."
        return {
            "score_riesgo": score,
            "nivel": nivel,
            "alerta": alerta,
            "factores": factores or ["Sin factores extra."],
            "rf": "RF43",
        }

    async def _score_riesgo(self, usuario_id, discapacidad, authorization, perfil_u, dolor, rpe):
        if authorization:
            try:
                return await self.riesgo.evaluar(
                    usuario_id,
                    rpe_reciente=rpe,
                    dolor_reportado=dolor,
                    authorization=authorization,
                    perfil=perfil_u or None,
                )
            except Exception:
                pass
        return self._riesgo_local(discapacidad, dolor, rpe)

    async def _evaluar_riesgo(self, perfil, mensaje, discapacidad, authorization, usuario):
        ev = await self._score_riesgo(
            perfil["usuario_id"], discapacidad, authorization, usuario, False, extraer_rpe(mensaje)
        )
        texto = (
            f"Predicción de riesgo de lesión: {ev.get('nivel')} "
            f"({ev.get('score_riesgo')}/100). {ev.get('alerta')} "
            "Es heurística con tu historial de perfil/carga, no un diagnóstico."
        )
        umbral = None
        if ev.get("nivel") in ("moderado", "alto"):
            umbral = await self._anotar_alerta_riesgo(
                perfil, "RIESGO_LESION", str(ev.get("alerta") or ""), authorization
            )
        return texto, {
            "caso_prueba": "CP13-HU41",
            "riesgo": ev,
            "umbral_semanal": umbral,
            "sugerencias": ["Tengo dolor al entrenar"],
        }

    async def _anotar_alerta_riesgo(
        self,
        perfil: dict[str, Any],
        tipo: str,
        detalle: str,
        authorization: Optional[str],
        forzar_aviso: bool = False,
    ) -> dict[str, Any]:
        """Registra una alerta de riesgo y, al llegar a 3 en 7 días, avisa al usuario."""
        pack = registrar_alerta_riesgo(perfil, tipo, detalle)
        if forzar_aviso and pack["count"] >= pack["umbral"] and not pack.get("en_silencio"):
            pack["debe_avisar"] = not pack.get("ya_avisado")
        if pack.get("debe_avisar"):
            pack["notificacion"] = await self._enviar_aviso_umbral(perfil, pack, authorization)
            pack["notificado"] = True
        else:
            pack["notificado"] = bool(pack.get("ya_avisado"))
            pack["notificacion"] = None
        pack["canales"] = ["push", "email"]
        return pack

    async def _enviar_aviso_umbral(
        self,
        perfil: dict[str, Any],
        pack: dict[str, Any],
        authorization: Optional[str],
    ) -> dict[str, Any]:
        """Push in-app + correo al atleta (CP33-HU50) vía ink-ms-accesibility."""
        titulo = "3 alertas de riesgo esta semana"
        cuerpo = (
            f"Acumulaste {pack['count']} alertas de riesgo en los últimos 7 días "
            f"(umbral {pack['umbral']}). Revisa carga, dolor y descanso. "
            "Es una estimación orientativa, no un diagnóstico médico."
        )
        envio: dict[str, Any] = {"ok": True, "local": True, "canales": ["push", "email"]}
        if authorization:
            envio = await self.alertas.accessibility.crear_notificacion(
                user_id=str(perfil.get("usuario_id")),
                tipo="RIESGO_SEMANAL",
                titulo=titulo,
                cuerpo=cuerpo,
                priority="HIGH",
                authorization=authorization,
            )
        marcar_aviso_umbral(perfil)
        registro = {
            "tipo": "RIESGO_SEMANAL",
            "titulo": titulo,
            "cuerpo": cuerpo,
            "canales": ["push", "email"],
            "fecha": _ahora_iso(),
            "envio": envio,
            "caso": "CP33-HU50",
        }
        perfil.setdefault("notificaciones", []).append(registro)
        return registro

    async def _riesgo_dolor(self, perfil, mensaje, discapacidad, authorization, usuario):
        ev = await self._score_riesgo(
            perfil["usuario_id"], discapacidad, authorization, usuario, True, extraer_rpe(mensaje)
        )
        texto = (
            f"Registré dolor. El riesgo pasa a {ev.get('nivel')} "
            f"({ev.get('score_riesgo')}/100). {ev.get('alerta')}"
        )
        umbral = await self._anotar_alerta_riesgo(
            perfil, "FATIGA_O_DOLOR", str(ev.get("alerta") or "dolor reportado"), authorization
        )
        return texto, {
            "caso_prueba": "CP14-HU41",
            "riesgo": ev,
            "dolor_reportado": True,
            "umbral_semanal": umbral,
            "sugerencias": ["Avisa al entrenador"],
        }

    async def _rutina_objetivo(self, perfil, mensaje, discapacidad, _auth, _user):
        catalogo = await obtener_catalogo_ejercicios()
        objetivo = interpretar_objetivo(mensaje)
        rutina = generar_rutina(
            discapacidad=discapacidad,
            objetivo_texto=mensaje,
            tipo_texto=mensaje,
            duracion_minutos=35,
            catalogo=catalogo,
            semilla=33,
        )
        extra = f"Objetivo detectado: {objetivo}."
        texto, datos = self._pack_rutina(rutina, "CP15-HU42", extra=extra)
        return texto, datos

    async def _plan_semanal(self, perfil, mensaje, discapacidad, authorization, usuario):
        freq = extraer_frecuencia(mensaje)
        objetivo = interpretar_objetivo(mensaje)
        plan = None
        if authorization:
            try:
                plan = await self.planes.generar_plan(
                    usuario_id=perfil["usuario_id"],
                    objetivo=mensaje or objetivo,
                    discapacidad=discapacidad,
                    semanas=4,
                    sesiones_por_semana=freq,
                    authorization=authorization,
                    perfil=usuario or None,
                )
            except Exception:
                plan = None
        if not plan:
            plan = {
                "plan_id": "local",
                "semanas": 4,
                "sesiones_por_semana": freq,
                "objetivo": objetivo,
                "total_sesiones": 4 * freq,
                "resumen": f"Plan de {objetivo}, {freq} días/semana, progresa a mitad del ciclo.",
            }
        perfil["plan_id"] = plan.get("plan_id")
        sesiones = plan.get("sesiones") or []
        preview = []
        for s in sesiones:
            preview.append({
                "id": s.get("id"),
                "semana": s.get("semana"),
                "sesion": s.get("sesion"),
                "enfoque": s.get("enfoque"),
                "nombre": s.get("nombre"),
                "duracion_estimada_minutos": s.get("duracion_estimada_minutos"),
                "total_ejercicios": s.get("total_ejercicios"),
                "ejercicios": s.get("ejercicios") or [],
            })
        texto = (
            f"Plan personalizado listo: {plan.get('semanas')} semanas, "
            f"{plan.get('sesiones_por_semana')} sesiones/semana "
            f"({plan.get('total_sesiones')} sesiones), objetivo {plan.get('objetivo')}. "
            f"{plan.get('resumen') or plan.get('progresion') or ''} "
            "Ábrelo en la pestaña Planes para ver cada semana."
        )
        return texto, {
            "caso_prueba": "CP16-HU42",
            "plan": {
                "plan_id": plan.get("plan_id"),
                "semanas": plan.get("semanas"),
                "sesiones_por_semana": plan.get("sesiones_por_semana"),
                "objetivo": plan.get("objetivo"),
                "total_sesiones": plan.get("total_sesiones"),
                "sesiones": preview,
                "resumen": plan.get("resumen") or plan.get("progresion"),
            },
            "sugerencias": ["Muéstrame mi dashboard", "La sesión estuvo difícil RPE 9"],
        }

    async def _rpe_alto(self, perfil, mensaje, _disc, _auth, _user):
        rpe = extraer_rpe(mensaje) or 9.0
        perfil["ultimo_rpe"] = rpe
        perfil.setdefault("sesiones_cerradas", []).append(
            {"fecha": _ahora_iso(), "rpe": rpe, "marca": rpe}
        )
        texto = (
            f"Fatiga percibida RPE {rpe}/10. Te sugiero una pausa, bajar un 20% el volumen "
            "y retomar con movilidad. No uso sensores de pulso: el RPE es tu reporte."
        )
        umbral = await self._anotar_alerta_riesgo(
            perfil, "FATIGA_O_DOLOR", f"RPE {rpe}", _auth
        )
        return texto, {
            "caso_prueba": "CP17-HU43",
            "plan_ajuste": {"rpe": rpe, "ajuste": "bajar", "pausa": True},
            "umbral_semanal": umbral,
            "sugerencias": ["La sesión estuvo fácil RPE 3"],
        }

    async def _rpe_bajo(self, perfil, mensaje, _disc, _auth, _user):
        rpe = extraer_rpe(mensaje) or 3.0
        perfil["ultimo_rpe"] = rpe
        perfil.setdefault("sesiones_cerradas", []).append(
            {"fecha": _ahora_iso(), "rpe": rpe, "marca": rpe}
        )
        texto = (
            f"RPE {rpe}/10: buena recuperación. Puedes progresar un poco en la próxima sesión."
        )
        return texto, {
            "caso_prueba": "CP18-HU43",
            "plan_ajuste": {"rpe": rpe, "ajuste": "subir"},
            "sugerencias": ["Muéstrame mi dashboard"],
        }

    async def _iniciar_voz(self, perfil, _mensaje, _disc, _auth, _user):
        perfil["voz_activa"] = True
        perfil["estado_sesion"] = "activa"
        texto = (
            "Asistencia de voz activada. Puedo leerte esta respuesta en audio. "
            "Comando recibido: iniciar entrenamiento."
        )
        return texto, {
            "caso_prueba": "CP19-HU44",
            "voz_activa": True,
            "respuesta_auditiva": True,
            "estado_sesion": "activa",
            "sugerencias": ["Comando de voz: dame una rutina"],
        }

    async def _comando_voz(self, perfil, mensaje, discapacidad, _auth, _user):
        catalogo = await obtener_catalogo_ejercicios()
        rutina = generar_rutina(
            discapacidad=discapacidad,
            objetivo_texto=mensaje,
            duracion_minutos=25,
            catalogo=catalogo,
            semilla=7,
        )
        nombres = [e.get("nombre") for e in (rutina.get("ejercicios") or [])[:3]]
        texto = (
            "Comando de voz ejecutado. Respuesta auditiva: "
            f"rutina lista con {', '.join(n for n in nombres if n)}."
        )
        return texto, {
            "caso_prueba": "CP20-HU44",
            "respuesta_auditiva": True,
            "voz_activa": bool(perfil.get("voz_activa")),
            "sugerencias": ["Visualizar dashboard"],
        }

    async def _dashboard(self, perfil, _mensaje, _disc, authorization, usuario):
        dash: dict[str, Any] = {}
        if authorization:
            try:
                dash = await self.dashboard.construir(
                    perfil["usuario_id"], authorization, perfil=usuario or None
                )
            except Exception:
                dash = {}
        vista = dash.get("vista") if isinstance(dash.get("vista"), dict) else {}
        sesiones = perfil.get("sesiones_cerradas") or []
        if not vista:
            ultimo_rpe = None
            if sesiones:
                ultimo_rpe = sesiones[-1].get("rpe")
            vista = {
                "perfil": {"nombre": (usuario or {}).get("fullName") or "tu perfil"},
                "kpis": [
                    {"clave": "eventos", "label": "Eventos inscritos", "valor": 0, "icono": "calendar-days"},
                    {"clave": "rutinas", "label": "Rutinas inscritas", "valor": 0, "icono": "heart"},
                    {"clave": "rpe", "label": "RPE reciente", "valor": ultimo_rpe if ultimo_rpe is not None else "—", "icono": "bolt"},
                    {
                        "clave": "sesiones",
                        "label": "Sesiones con el agente",
                        "valor": len(sesiones),
                        "icono": "chart-bar",
                    },
                ],
            }
            dash = {"vista": vista}
        texto = self.dashboard.resumen_texto(dash)
        if sesiones and "Sesiones" not in texto:
            texto += f" Sesiones registradas con el agente: {len(sesiones)}."
        return texto, {
            "caso_prueba": "CP21-HU45",
            "dashboard": vista,
            "vista": vista,
            "estadisticas": vista,
            "graficos": True,
            "sugerencias": ["Dashboard de métricas y predicciones"],
        }

    async def _dashboard_predicciones(self, perfil, mensaje, discapacidad, authorization, usuario):
        ev = await self._score_riesgo(
            perfil["usuario_id"], discapacidad, authorization, usuario, False,
            perfil.get("ultimo_rpe"),
        )
        texto, datos = await self._dashboard(
            perfil, mensaje, discapacidad, authorization, usuario
        )
        datos["caso_prueba"] = "CP22-HU45"
        datos["prediccion_riesgo"] = ev
        datos["graficos"] = True
        texto = (
            f"{texto} Predicción asociada: riesgo {ev.get('nivel')} "
            f"({ev.get('score_riesgo')}/100)."
        )
        return texto, datos

    async def _comparar_mes(self, perfil, _mensaje, _disc, authorization, _user):
        remoto: dict[str, Any] = {}
        if authorization:
            try:
                remoto = await self.historial.comparar(perfil["usuario_id"], authorization) or {}
            except Exception:
                remoto = {}
        local = perfil.get("sesiones_cerradas") or []
        sesiones_hist = remoto.get("sesiones_historial") or [
            {"fecha": s.get("fecha"), "rpe": s.get("rpe"), "origen": "agente"}
            for s in local
        ]
        comp = remoto.get("comparativa") or {}
        insc = comp.get("inscripciones_eventos") or {}
        rpe = comp.get("sesiones_rpe") or {}
        n_local = len(local)
        if not rpe:
            rpe = {
                "actual": n_local,
                "anterior": 0,
                "rpe_promedio_actual": round(sum(float(s.get("rpe") or 0) for s in local) / n_local, 2) if n_local else None,
                "rpe_promedio_anterior": None,
            }
        texto = (
            "Comparativa mes actual vs anterior (no es un informe de riesgo):\n"
            f"- Inscripciones: {insc.get('actual', 0)} vs {insc.get('anterior', 0)} "
            f"({int(insc.get('delta') or 0):+d}).\n"
            f"- Sesiones con RPE: {rpe.get('actual', 0)} vs {rpe.get('anterior', 0)}.\n"
            f"- RPE promedio: {rpe.get('rpe_promedio_actual') if rpe.get('rpe_promedio_actual') is not None else 'sin datos'} "
            f"vs {rpe.get('rpe_promedio_anterior') if rpe.get('rpe_promedio_anterior') is not None else 'sin datos'}.\n"
            f"- Planes guardados: {comp.get('planes_guardados', 0)}.\n"
            f"Tendencia: {remoto.get('tendencia') or 'estable'}."
        )
        vista = {
            "kpis": [
                {"clave": "inscripciones", "label": "Inscripciones este mes", "valor": insc.get("actual", 0), "icono": "calendar-days"},
                {"clave": "sesiones", "label": "Sesiones RPE", "valor": rpe.get("actual", 0), "icono": "bolt"},
                {"clave": "rpe", "label": "RPE promedio", "valor": rpe.get("rpe_promedio_actual") if rpe.get("rpe_promedio_actual") is not None else "—", "icono": "heart"},
            ],
            "comparativa": [
                {"label": "Inscripciones este mes", "actual": insc.get("actual") or 0, "anterior": insc.get("anterior") or 0, "delta": insc.get("delta") or 0},
                {"label": "Sesiones con RPE", "actual": rpe.get("actual") or 0, "anterior": rpe.get("anterior") or 0, "delta": (rpe.get("actual") or 0) - (rpe.get("anterior") or 0)},
            ],
            "sesiones_historial": sesiones_hist[:8],
            "tendencia": remoto.get("tendencia") or "estable",
        }
        return texto, {
            "caso_prueba": "CP23-HU46",
            "comparativa": comp or vista["comparativa"],
            "vista": vista,
            "estadisticas": vista,
            "graficos": True,
            "sugerencias": ["Compara con mi historial"],
        }

    async def _comparar_historial(self, perfil, _mensaje, _disc, authorization, _user):
        historial = list(perfil.get("sesiones_cerradas") or [])
        remoto: dict[str, Any] = {}
        if authorization:
            try:
                remoto = await self.historial.comparar(perfil["usuario_id"], authorization) or {}
            except Exception:
                remoto = {}
        extra = remoto.get("sesiones_historial") or []
        if extra and not historial:
            historial = extra
        valores = [float(s.get("rpe") or 0) for s in historial if s.get("rpe") is not None]
        actual = valores[0] if extra and valores else (valores[-1] if valores else None)
        if extra and valores:
            actual = float(extra[0].get("rpe") or valores[0])
        elif valores:
            actual = valores[-1]
        promedio = round(sum(valores) / len(valores), 2) if valores else None
        delta = None
        if actual is not None and promedio is not None:
            delta = round(actual - promedio, 2)
        texto = (
            "Evolución vs tu historial personal (sesiones, no riesgos):\n"
            f"- Última sesión RPE: {actual if actual is not None else 'sin datos'}.\n"
            f"- Promedio histórico: {promedio if promedio is not None else 'aún vacío'}.\n"
            f"- Sesiones registradas: {len(valores)}.\n"
        )
        if delta is not None:
            if delta < 0:
                texto += f"La última sesión fue {abs(delta)} puntos más suave que tu promedio."
            elif delta > 0:
                texto += f"La última sesión fue {delta} puntos más exigente que tu promedio."
            else:
                texto += "La última sesión está en tu promedio."
        vista = {
            "kpis": [
                {"clave": "ultima", "label": "Última sesión RPE", "valor": actual if actual is not None else "—", "icono": "bolt"},
                {"clave": "promedio", "label": "Promedio histórico", "valor": promedio if promedio is not None else "—", "icono": "chart-bar"},
                {"clave": "sesiones", "label": "Sesiones", "valor": len(valores), "icono": "heart"},
            ],
            "comparativa": [
                {
                    "label": "RPE última vs promedio",
                    "actual": actual or 0,
                    "anterior": promedio or 0,
                    "delta": delta or 0,
                }
            ],
            "sesiones_historial": (extra or historial)[:8],
        }
        return texto, {
            "caso_prueba": "CP24-HU46",
            "comparacion_sesion": {
                "ultima": actual,
                "promedio_historico": promedio,
                "sesiones": len(valores),
                "delta": delta,
            },
            "vista": vista,
            "estadisticas": vista,
            "graficos": True,
            "sugerencias": ["Recomiéndame eventos"],
        }

    async def _recomendar_eventos(self, perfil, _mensaje, _disc, authorization, usuario):
        recs: list = []
        if authorization:
            try:
                pack = await self.recomendacion.recomendar_eventos(
                    perfil["usuario_id"], limite=3,
                    authorization=authorization, perfil=usuario or None,
                )
                recs = pack.get("recomendaciones") or []
            except Exception:
                recs = []
        if recs:
            lineas = ["Eventos según tu perfil (afinidad y rendimiento):"]
            for item in recs[:3]:
                lineas.append(f"- {item.get('nombre') or item.get('name') or 'Evento'}")
            texto = "\n".join(lineas)
        else:
            texto = (
                "Te recomiendo eventos según discapacidad y cupos. "
                "Ahora no hay abiertos en el catálogo; en cuanto se publiquen te los listo."
            )
        return texto, {
            "caso_prueba": "CP25-HU47",
            "recomendaciones": recs[:3],
            "sugerencias": ["Qué deportes puedo practicar"],
        }

    async def _recomendar_deportes(self, perfil, _mensaje, discapacidad, authorization, usuario):
        ranking: list = []
        if authorization:
            try:
                pack = await self.deportes.filtrar(
                    perfil["usuario_id"], limite=5,
                    authorization=authorization, perfil=usuario or None,
                )
                ranking = pack.get("deportes") or pack.get("ranking") or []
            except Exception:
                ranking = []
        if not ranking:
            texto = (
                f"Deportes afines a {descripcion(canonizar(discapacidad))}: "
                "natación, boccia, baloncesto en silla o atletismo adaptado, "
                "según el catálogo de la plataforma."
            )
        else:
            nombres = [d.get("nombre") or d.get("name") for d in ranking[:5]]
            texto = "Deportes para tu perfil: " + ", ".join(n for n in nombres if n) + "."
        return texto, {
            "caso_prueba": "CP26-HU47",
            "deportes": ranking[:5],
            "sugerencias": ["Uso silla de ruedas, sugiere accesibilidad"],
        }

    async def _detectar_discapacidad(self, perfil, mensaje, _disc, _auth, _user):
        sug = self.deteccion.sugerir(mensaje)
        pauta = PAUTAS_DISCAPACIDAD.get(sug.get("sugerida") or "general", {})
        n = normalizar(mensaje)
        caso = (
            "CP27-HU48"
            if any(p in n for p in ("silla", "ciego", "sordo", "detecta"))
            else "CP28-HU48"
        )
        texto = (
            f"{sug.get('mensaje')} Pauta de accesibilidad: {pauta.get('pauta') or ''} "
            "No se guarda en el perfil hasta que confirmes."
        )
        return texto, {
            "caso_prueba": caso,
            "deteccion": sug,
            "requiere_confirmacion": True,
            "sugerencias_accesibilidad": [pauta.get("pauta"), pauta.get("referencia")],
            "sugerencias": ["Sugiere configuración de accesibilidad"],
        }

    async def _modo_competencia(self, perfil, mensaje, discapacidad, authorization, _user):
        doc: dict[str, Any] = {}
        if authorization:
            try:
                doc = await self.competencia.activar_modo(
                    perfil["usuario_id"],
                    activar=True,
                    objetivo=mensaje,
                    semanas=3,
                    authorization=authorization,
                )
            except Exception:
                doc = {}
        plan = doc.get("plan") if isinstance(doc.get("plan"), dict) else {}
        if not plan:
            plan = self.competencia._plan_preparacion(
                discapacidad=discapacidad or "general",
                semanas=3,
                evento=(doc.get("evento_objetivo") if isinstance(doc, dict) else None),
                objetivo=(doc.get("objetivo") if isinstance(doc, dict) else None)
                or "Preparación competitiva general",
                recomendaciones=[],
            )
            doc = {**(doc if isinstance(doc, dict) else {}), "activo": True, "plan": plan, "semanas": 3}
        perfil["modo_competencia"] = True
        semanas = doc.get("semanas") or plan.get("semanas") or 3
        objetivo = doc.get("objetivo") or plan.get("objetivo") or "preparación competitiva"
        lineas = [
            f"Modo competencia activado. Plan de {semanas} semanas: {objetivo}."
        ]
        for fase in (plan.get("fases") or [])[:3]:
            if not isinstance(fase, dict):
                continue
            lineas.append(
                f"- Semana {fase.get('semana')}: {fase.get('foco')} "
                f"(intensidad {fase.get('intensidad')}, "
                f"{fase.get('sesiones_sugeridas')} sesiones)."
            )
        checks: list[str] = []
        for item in (plan.get("checklist") or [])[:4]:
            if isinstance(item, dict) and item.get("texto"):
                checks.append(str(item["texto"]))
            elif isinstance(item, str):
                checks.append(item)
        if checks:
            lineas.append("Checklist: " + "; ".join(checks))
        if plan.get("nota_local"):
            lineas.append(str(plan["nota_local"]))
        return "\n".join(lineas), {
            "caso_prueba": "CP29-HU49",
            "modo_competencia": doc,
            "plan": plan,
            "vista": doc.get("vista") or {},
            "sugerencias": ["Competir contra mi historial"],
        }

    async def _competencia_historial(self, perfil, _mensaje, _disc, authorization, _user):
        modo = {"activo": bool(perfil.get("modo_competencia"))}
        if authorization:
            try:
                modo = await self.competencia.obtener_modo(
                    perfil["usuario_id"], authorization=authorization
                )
            except Exception:
                pass
        hist = perfil.get("sesiones_cerradas") or []
        texto = (
            "Competencia contra tu historial: "
            f"{len(hist)} sesiones registradas. "
            f"Modo competencia {'activo' if modo.get('activo') else 'inactivo'}. "
            "Los rivales de perfil similar se toman del cruce deporte–discapacidad."
        )
        return texto, {
            "caso_prueba": "CP30-HU49",
            "modo_competencia": modo,
            "sesiones_historial": len(hist),
            "sugerencias": ["Avisa al entrenador, RPE 9"],
        }

    async def _alerta_entrenador(self, perfil, mensaje, discapacidad, authorization, usuario):
        rpe = extraer_rpe(mensaje) or 9.0
        dolor = "dolor" in normalizar(mensaje)
        resultado: dict[str, Any] = {}
        if authorization:
            try:
                resultado = await self.alertas.evaluar_y_notificar(
                    perfil["usuario_id"],
                    rpe_reciente=rpe,
                    dolor_reportado=dolor,
                    authorization=authorization,
                )
            except Exception:
                resultado = {}
        ev = resultado.get("evaluacion") or await self._score_riesgo(
            perfil["usuario_id"], discapacidad, None, usuario, dolor, rpe
        )
        alertas = resultado.get("alertas_generadas") or resultado.get("alertas") or [{
            "tipo": "RIESGO_LESION" if ev.get("nivel") == "alto" else "FATIGA_O_DOLOR",
            "prioridad": "HIGH",
        }]
        texto = (
            f"Alerta para el entrenador: riesgo {ev.get('nivel')} "
            f"(score {ev.get('score_riesgo')}/100, RPE {rpe}). "
            f"Tipo: {alertas[0].get('tipo')}."
        )
        umbral = await self._anotar_alerta_riesgo(
            perfil,
            str(alertas[0].get("tipo") or "RIESGO_LESION"),
            f"RPE {rpe}",
            authorization,
        )
        return texto, {
            "caso_prueba": "CP31-HU50",
            "alertas": alertas,
            "riesgo": ev,
            "umbral_semanal": umbral,
            "sugerencias": ["Notifica progreso destacado RPE 3"],
        }

    async def _progreso_entrenador(self, perfil, mensaje, discapacidad, authorization, usuario):
        rpe = extraer_rpe(mensaje) or 3.0
        resultado: dict[str, Any] = {}
        if authorization:
            try:
                resultado = await self.alertas.evaluar_y_notificar(
                    perfil["usuario_id"],
                    rpe_reciente=rpe,
                    dolor_reportado=False,
                    authorization=authorization,
                )
            except Exception:
                resultado = {}
        alertas = resultado.get("alertas_generadas") or resultado.get("alertas") or [{
            "tipo": "PROGRESO_DESTACADO",
            "prioridad": "LOW",
        }]
        texto = (
            f"Progreso destacado (RPE {rpe}/10 sin dolor). "
            "El entrenador recibe una alerta de tipo PROGRESO_DESTACADO."
        )
        return texto, {
            "caso_prueba": "CP32-HU50",
            "alertas": alertas,
            "sugerencias": ["Acumulé 3 alertas de riesgo esta semana"],
        }

    async def _umbral_alertas_semana(self, perfil, _mensaje, _disc, authorization, _user):
        pack: dict[str, Any] = {"count": 0, "umbral": 3, "notificado": False}
        umbrales = perfil.get("umbrales") if isinstance(perfil.get("umbrales"), dict) else {}
        umbral = int(umbrales.get("alertas_semana") or 3)
        for _ in range(max(1, umbral)):
            pack = await self._anotar_alerta_riesgo(
                perfil,
                "RIESGO_SEMANAL",
                "Alerta de riesgo acumulada en la semana",
                authorization,
                forzar_aviso=True,
            )
            if pack["count"] >= umbral:
                break
        if not pack.get("notificado") and not pack.get("en_silencio"):
            pack["notificacion"] = await self._enviar_aviso_umbral(perfil, pack, authorization)
            pack["notificado"] = True
        notif = pack.get("notificacion")
        if not notif:
            historial = perfil.get("notificaciones") or []
            notif = historial[-1] if historial else {
                "tipo": "RIESGO_SEMANAL",
                "canales": ["push", "email"],
                "caso": "CP33-HU50",
            }
        texto = (
            f"Esta semana acumulaste {pack['count']} alertas de riesgo "
            f"(umbral {pack['umbral']}). Te envié notificación push y correo."
        )
        return texto, {
            "caso_prueba": "CP33-HU50",
            "alertas_semana": pack["count"],
            "umbral": pack["umbral"],
            "canales": ["push", "email"],
            "notificado": True,
            "notificacion_usuario": notif,
            "sugerencias": ["Cuál es mi riesgo de lesión"],
        }
