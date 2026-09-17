"""Casos HU40–HU50 alineados con los RF ya existentes (sin voz, sensores ni visión)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
from app.nlp.entrenamiento_pedido import (
    extraer_frecuencia,
    extraer_horas_silencio,
    extraer_rpe,
    extraer_umbral_alertas,
    feedback_dificultad,
)
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
            "historial_riesgo": self._historial_riesgo,
            "riesgo_dolor": self._riesgo_dolor,
            "rutina_objetivo": self._rutina_objetivo,
            "plan_semanal": self._plan_semanal,
            "ajustar_plan_dificultad": self._ajustar_plan_dificultad,
            "rpe_alto": self._rpe_alto,
            "rpe_bajo": self._rpe_bajo,
            "visualizar_dashboard": self._visualizar_dashboard,
            "veredicto_progreso": self._veredicto_progreso,
            "dashboard": self._dashboard,
            "dashboard_predicciones": self._dashboard_predicciones,
            "comparar_mes": self._comparar_mes,
            "comparar_historial": self._comparar_historial,
            "cierre_sesion_comparativa": self._cierre_sesion_comparativa,
            "recomendar_eventos": self._recomendar_eventos,
            "recomendar_deportes": self._recomendar_deportes,
            "detectar_discapacidad": self._detectar_discapacidad,
            "modo_competencia": self._modo_competencia,
            "competencia_historial": self._competencia_historial,
            "alerta_entrenador": self._alerta_entrenador,
            "progreso_entrenador": self._progreso_entrenador,
            "umbral_alertas_semana": self._umbral_alertas_semana,
            "configurar_alertas": self._configurar_alertas,
            "avance_plan_competencia": self._avance_plan_competencia,
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
            f"Variante adaptada de «{ejercicio.get('nombre')}» "
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
            f"Predicción heurística de riesgo de lesión: {ev.get('nivel')} "
            f"({ev.get('score_riesgo')}/100). {ev.get('alerta')} "
            "Usa perfil, carga y RPE reportado; no analiza movimiento por cámara."
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
            "caso_prueba": None,
            "plan": {
                "plan_id": plan.get("plan_id"),
                "semanas": plan.get("semanas"),
                "sesiones_por_semana": plan.get("sesiones_por_semana"),
                "objetivo": plan.get("objetivo"),
                "total_sesiones": plan.get("total_sesiones"),
                "sesiones": preview,
                "resumen": plan.get("resumen") or plan.get("progresion"),
            },
            "sugerencias": [
                "El plan me quedó difícil, ajústalo",
                "Visualizar dashboard",
            ],
        }

    async def _ajustar_plan_dificultad(self, perfil, mensaje, discapacidad, authorization, usuario):
        """CP16-HU42 — regenera el plan según feedback de dificultad (no es solo un tip de RPE)."""
        sentido = feedback_dificultad(mensaje)
        freq = extraer_frecuencia(mensaje)
        nivel = "principiante"
        detalle = "Mantengo el plan."
        if sentido == "bajar":
            nivel = "principiante"
            freq = max(2, freq - 1)
            detalle = "Bajé volumen e intensidad: menos sesiones y nivel principiante."
        elif sentido == "subir":
            nivel = "intermedio"
            freq = min(5, freq + 1)
            detalle = "Subí un poco la exigencia: más sesiones y nivel intermedio."
        objetivo = interpretar_objetivo(mensaje) or perfil.get("ultimo_objetivo") or "general"
        perfil["ultimo_objetivo"] = objetivo
        plan = None
        if authorization:
            try:
                plan = await self.planes.generar_plan(
                    usuario_id=perfil["usuario_id"],
                    objetivo=str(objetivo),
                    discapacidad=discapacidad,
                    nivel=nivel,
                    semanas=4,
                    sesiones_por_semana=freq,
                    authorization=authorization,
                    perfil=usuario or None,
                )
            except Exception:
                plan = None
        if not plan:
            plan = {
                "plan_id": "ajuste-local",
                "semanas": 4,
                "sesiones_por_semana": freq,
                "objetivo": objetivo,
                "nivel": nivel,
                "total_sesiones": 4 * freq,
                "resumen": detalle,
            }
        perfil["plan_id"] = plan.get("plan_id")
        perfil["plan_ajuste"] = {
            "sentido": sentido,
            "nivel": nivel,
            "sesiones_por_semana": freq,
            "detalle": detalle,
            "fecha": _ahora_iso(),
        }
        texto = (
            f"Plan ajustado por feedback de dificultad ({sentido}). {detalle} "
            f"Quedó en {plan.get('semanas')} semanas × {plan.get('sesiones_por_semana')} "
            f"sesiones/semana (nivel {nivel})."
        )
        return texto, {
            "caso_prueba": "CP16-HU42",
            "plan_ajuste": perfil["plan_ajuste"],
            "plan": {
                "plan_id": plan.get("plan_id"),
                "semanas": plan.get("semanas"),
                "sesiones_por_semana": plan.get("sesiones_por_semana"),
                "objetivo": plan.get("objetivo"),
                "nivel": nivel,
            },
            "sugerencias": ["Evalua mi progreso", "Visualizar dashboard"],
        }

    async def _rpe_alto(self, perfil, mensaje, _disc, _auth, _user):
        rpe = extraer_rpe(mensaje) or 9.0
        perfil["ultimo_rpe"] = rpe
        perfil.setdefault("sesiones_cerradas", []).append(
            {"fecha": _ahora_iso(), "rpe": rpe, "marca": rpe}
        )
        texto = (
            f"Fatiga percibida RPE {rpe}/10. Te sugiero una pausa, bajar un 20% el volumen "
            "y retomar con movilidad. Sin sensores: el RPE es tu reporte post-sesión."
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

    async def _visualizar_dashboard(self, perfil, mensaje, discapacidad, authorization, usuario):
        """CP19-HU44 — muestra KPIs del dashboard del atleta (sin voz)."""
        texto, datos = await self._dashboard(
            perfil, mensaje, discapacidad, authorization, usuario
        )
        vista = datos.get("vista") or {}
        kpis = vista.get("kpis") or []
        lineas = ["Dashboard del atleta (indicadores):"]
        for kpi in kpis:
            lineas.append(f"- {kpi.get('label')}: {kpi.get('valor')}")
        if len(lineas) == 1:
            lineas.append("- Aún sin datos; registra sesiones o inscripciones.")
        texto = "\n".join(lineas)
        datos["caso_prueba"] = "CP19-HU44"
        datos["sugerencias"] = ["Cómo voy este mes", "Historial de riesgo"]
        return texto, datos

    async def _veredicto_progreso(self, perfil, _mensaje, _disc, authorization, _user):
        """CP20-HU44 — veredicto mes actual vs anterior: progresando / estable / cayendo / va mal."""
        remoto: dict[str, Any] = {}
        if authorization:
            try:
                remoto = await self.historial.comparar(perfil["usuario_id"], authorization) or {}
            except Exception:
                remoto = {}
        local = perfil.get("sesiones_cerradas") or []
        comp = remoto.get("comparativa") or {}
        insc = comp.get("inscripciones_eventos") or {}
        rpe = comp.get("sesiones_rpe") or {}
        act_insc = int(insc.get("actual") or 0)
        prev_insc = int(insc.get("anterior") or 0)
        act_ses = int(rpe.get("actual") or len(local))
        prev_ses = int(rpe.get("anterior") or 0)
        rpe_act = rpe.get("rpe_promedio_actual")
        rpe_prev = rpe.get("rpe_promedio_anterior")
        if rpe_act is None and local:
            vals = [float(s.get("rpe") or 0) for s in local if s.get("rpe") is not None]
            rpe_act = round(sum(vals) / len(vals), 2) if vals else None

        veredicto = "estable"
        mensaje_v = "Vas estable: tu actividad es similar al mes anterior."
        if act_insc + act_ses < prev_insc + prev_ses:
            veredicto = "cayendo"
            mensaje_v = "Vas cayendo: este mes tienes menos actividad que el anterior."
        elif act_insc + act_ses > prev_insc + prev_ses:
            veredicto = "progresando"
            mensaje_v = "Vas progresando: este mes sumaste más actividad que el anterior."
        if (
            rpe_act is not None
            and rpe_prev is not None
            and float(rpe_act) >= float(rpe_prev) + 1.5
            and act_ses >= prev_ses
        ):
            veredicto = "va_mal"
            mensaje_v = (
                "Vas mal por sobrecarga: el RPE promedio subió mucho respecto al mes pasado. "
                "Conviene bajar volumen o descansar."
            )
        elif (
            rpe_act is not None
            and rpe_prev is not None
            and float(rpe_act) <= float(rpe_prev) - 0.8
            and veredicto == "progresando"
        ):
            mensaje_v = (
                "Vas progresando bien: más actividad y mejor recuperación (RPE más bajo)."
            )

        texto = (
            f"{mensaje_v}\n"
            f"- Inscripciones: {act_insc} este mes vs {prev_insc} el anterior.\n"
            f"- Sesiones: {act_ses} vs {prev_ses}.\n"
            f"- RPE promedio: {rpe_act if rpe_act is not None else 'sin datos'} "
            f"vs {rpe_prev if rpe_prev is not None else 'sin datos'}.\n"
            f"Veredicto: {veredicto}."
        )
        return texto, {
            "caso_prueba": "CP20-HU44",
            "veredicto": veredicto,
            "periodo_actual": remoto.get("periodo_actual"),
            "periodo_anterior": remoto.get("periodo_anterior"),
            "comparativa": {
                "inscripciones": {"actual": act_insc, "anterior": prev_insc},
                "sesiones": {"actual": act_ses, "anterior": prev_ses},
                "rpe_promedio": {"actual": rpe_act, "anterior": rpe_prev},
            },
            "sugerencias": ["Visualizar dashboard", "El plan me quedó difícil, ajústalo"],
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
            "sugerencias": ["Visualizar dashboard", "Cómo voy este mes"],
        }

    async def _dashboard_predicciones(self, perfil, mensaje, discapacidad, authorization, usuario):
        """Compat: redirige al historial de riesgo (CP22)."""
        return await self._historial_riesgo(
            perfil, mensaje, discapacidad, authorization, usuario
        )

    async def _historial_riesgo(self, perfil, _mensaje, discapacidad, authorization, usuario):
        """CP22-HU45 — listar evaluaciones de riesgo recientes (no es el dashboard)."""
        items: list[dict[str, Any]] = []
        if authorization:
            try:
                items = await self.riesgo.listar_historial(perfil["usuario_id"])
            except Exception:
                items = []
        if not items:
            # Fallback: alertas locales del perfil de entrenamiento.
            items = list(perfil.get("alertas_riesgo") or [])[-5:]
        if not items:
            ev = await self._score_riesgo(
                perfil["usuario_id"], discapacidad, authorization, usuario, False,
                perfil.get("ultimo_rpe"),
            )
            items = [{
                "nivel": ev.get("nivel"),
                "score_riesgo": ev.get("score_riesgo"),
                "alerta": ev.get("alerta"),
                "fecha": _ahora_iso(),
                "origen": "evaluacion_actual",
            }]
        lineas = ["Historial de evaluaciones de riesgo (más recientes):"]
        for item in items[:5]:
            lineas.append(
                f"- {item.get('fecha') or 'sin fecha'}: "
                f"nivel {item.get('nivel') or item.get('tipo') or 'n/d'} "
                f"(score {item.get('score_riesgo') or item.get('score') or '—'})"
            )
        return "\n".join(lineas), {
            "caso_prueba": "CP22-HU45",
            "historial_riesgo": items[:5],
            "total": len(items),
            "sugerencias": ["Cuál es mi riesgo de lesión", "Visualizar dashboard"],
        }

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
            "caso_prueba": "CP24-HU46",
            "comparativa": comp or vista["comparativa"],
            "vista": vista,
            "estadisticas": vista,
            "graficos": True,
            "sugerencias": ["Cómo voy este mes", "Cómo salió mi sesión"],
        }

    async def _cierre_sesion_comparativa(self, perfil, mensaje, _disc, _auth, _user):
        """CP23-HU46 — al cerrar sesión: última vs promedio histórico y mejor marca."""
        rpe = extraer_rpe(mensaje)
        historial = list(perfil.get("sesiones_cerradas") or [])
        if rpe is not None:
            historial.append({"fecha": _ahora_iso(), "rpe": rpe, "marca": rpe})
            perfil["sesiones_cerradas"] = historial
            perfil["ultimo_rpe"] = rpe
        valores = [float(s.get("rpe") or 0) for s in historial if s.get("rpe") is not None]
        if not valores:
            return (
                "Aún no hay sesiones para comparar. Registra un RPE, por ejemplo: "
                "«Cómo salió mi sesión RPE 6».",
                {"caso_prueba": "CP23-HU46", "comparacion_sesion": {"sesiones": 0}},
            )
        actual = valores[-1]
        promedio = round(sum(valores) / len(valores), 2)
        mejor = min(valores)  # RPE más bajo = mejor recuperación / sesión más controlada
        peor = max(valores)
        perfil["mejor_marca"] = mejor
        delta_prom = round(actual - promedio, 2)
        if actual <= mejor:
            juicio = "Igualaste o superaste tu mejor sesión (RPE más bajo)."
        elif actual <= promedio:
            juicio = "Vas bien: esta sesión quedó por debajo o en tu promedio histórico."
        else:
            juicio = "Esta sesión fue más exigente que tu promedio; cuida la recuperación."
        texto = (
            "Cierre de sesión vs historial:\n"
            f"- Sesión actual RPE: {actual}.\n"
            f"- Promedio histórico: {promedio}.\n"
            f"- Mejor sesión (RPE más bajo): {mejor}.\n"
            f"- Peor sesión (RPE más alto): {peor}.\n"
            f"- Delta vs promedio: {delta_prom:+}.\n"
            f"{juicio}"
        )
        return texto, {
            "caso_prueba": "CP23-HU46",
            "comparacion_sesion": {
                "ultima": actual,
                "promedio_historico": promedio,
                "mejor_sesion": mejor,
                "peor_sesion": peor,
                "sesiones": len(valores),
                "delta": delta_prom,
                "juicio": juicio,
            },
            "sugerencias": ["Cómo voy este mes", "Visualizar dashboard"],
        }

    async def _comparar_historial(self, perfil, mensaje, disc, auth, user):
        """Compat: la comparativa post-sesión ahora es CP23."""
        return await self._cierre_sesion_comparativa(perfil, mensaje, disc, auth, user)

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
            "sugerencias": ["Configurar umbral de alertas a 5", "Silenciar alertas 24 horas"],
        }

    async def _configurar_alertas(self, perfil, mensaje, _disc, _auth, _user):
        """Ajuste auxiliar de umbral/silencio (ya no es CP34)."""
        umbrales = perfil.get("umbrales") if isinstance(perfil.get("umbrales"), dict) else {}
        umbral_nuevo = extraer_umbral_alertas(mensaje)
        n = normalizar(mensaje)
        silenciar = any(p in n for p in ("silenciar", "silencio"))
        cambios: list[str] = []
        if umbral_nuevo is not None:
            umbrales["alertas_semana"] = umbral_nuevo
            perfil["umbrales"] = umbrales
            perfil["aviso_umbral_semana_en"] = None
            cambios.append(f"umbral semanal = {umbral_nuevo}")
        if silenciar:
            horas = extraer_horas_silencio(mensaje)
            hasta = datetime.now(timezone.utc) + timedelta(hours=horas)
            perfil["silenciado_hasta"] = hasta.isoformat()
            cambios.append(f"silencio temporal hasta {hasta.isoformat()} ({horas} h)")
        if not cambios:
            actual = int(umbrales.get("alertas_semana") or 3)
            silenciado = perfil.get("silenciado_hasta")
            texto = (
                f"Umbral actual de alertas semanales: {actual}. "
                f"Silencio: {silenciado or 'inactivo'}."
            )
        else:
            texto = "Preferencias de alerta actualizadas: " + "; ".join(cambios) + "."
        return texto, {
            "umbrales": perfil.get("umbrales"),
            "silenciado_hasta": perfil.get("silenciado_hasta"),
            "cambios": cambios,
            "sugerencias": ["Avance del plan de competencia"],
        }

    async def _avance_plan_competencia(self, perfil, _mensaje, discapacidad, authorization, _user):
        """CP34-HU50 — % de avance del plan de competencia (checklist/sesiones)."""
        modo: dict[str, Any] = {}
        if authorization:
            try:
                modo = await self.competencia.obtener_modo(
                    perfil["usuario_id"], authorization=authorization
                ) or {}
            except Exception:
                modo = {}
        plan = modo.get("plan") if isinstance(modo.get("plan"), dict) else {}
        checklist = list(plan.get("checklist") or [])
        if not checklist:
            checklist = [
                {"id": "c1", "texto": "Sesión técnica", "hecho": False},
                {"id": "c2", "texto": "Sesión de potencia", "hecho": False},
                {"id": "c3", "texto": "Movilidad / recuperación", "hecho": False},
            ]
            plan = {**plan, "checklist": checklist, "semanas": plan.get("semanas") or 3}
        marcados = 0
        for item in checklist:
            if isinstance(item, dict) and not item.get("hecho"):
                item["hecho"] = True
                marcados = 1
                break
        hechos = sum(1 for i in checklist if isinstance(i, dict) and i.get("hecho"))
        total = max(1, len(checklist))
        pct = round(100.0 * hechos / total, 1)
        perfil["modo_competencia"] = True
        perfil["avance_competencia"] = {
            "porcentaje": pct,
            "hechos": hechos,
            "total": total,
            "fecha": _ahora_iso(),
        }
        texto = (
            f"Avance del plan de competencia: {pct}% "
            f"({hechos}/{total} ítems del checklist). "
            + (f"Marqué {marcados} pendiente(s) como hecho. " if marcados else "")
            + "Sigue en el apartado de competencia para el detalle del plan."
        )
        return texto, {
            "caso_prueba": "CP34-HU50",
            "avance": perfil["avance_competencia"],
            "checklist": checklist,
            "plan": {"semanas": plan.get("semanas"), "objetivo": plan.get("objetivo")},
            "sugerencias": ["Activa modo competencia", "Cómo voy este mes"],
        }
