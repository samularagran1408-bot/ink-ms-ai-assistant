"""Métricas de plataforma en el chat, sin Crew ni tool-calling del LLM."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from app.crew.enrutar import rol_principal
from app.nlp.texto import normalizar
from app.services.reports_service import ReportsService
from app.services.sports_service import SportsService
from app.services.user_service import UserService

_STAFF = frozenset({"ADMIN", "ORGANIZADOR", "ENTRENADOR"})
_ADMIN_ORG = frozenset({"ADMIN", "ORGANIZADOR"})
_ADMIN_ENT = frozenset({"ADMIN", "ENTRENADOR"})
_ORG_STAFF = frozenset({"ADMIN", "ORGANIZADOR", "ENTRENADOR"})


def _nombre(item: dict[str, Any], *claves: str) -> str:
    """Primer texto no vacío entre claves típicas de Sports/Reports."""
    for clave in claves:
        valor = item.get(clave)
        if valor:
            return str(valor)
    return ""


def _entero(bloque: Any, *claves: str) -> Optional[int]:
    """Lee un entero de un dict anidado (metrics camel/snake)."""
    if not isinstance(bloque, dict):
        return None
    metrics = bloque.get("metrics") if isinstance(bloque.get("metrics"), dict) else bloque
    for clave in claves:
        valor = metrics.get(clave) if isinstance(metrics, dict) else None
        if valor is None:
            continue
        try:
            return int(valor)
        except (TypeError, ValueError):
            continue
    return None


class MetricasAgent:
    """Conteos y paneles: Sports para catálogo, Reports para KPIs de staff."""

    def __init__(self):
        """Clientes HTTP de reports, sports y users."""
        self.reports = ReportsService()
        self.sports = SportsService()
        self.users = UserService()

    async def procesar(
        self,
        comando: str,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        roles: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Resuelve el pedido o explica que el rol no cubre esa métrica."""
        rol = rol_principal(roles)
        handlers = {
            "asociaciones_por_deporte": self._asociaciones,
            "cuantos_usuarios": self._usuarios,
            "cuantos_eventos": self._eventos,
            "cuantos_deportes": self._deportes,
            "cuantas_discapacidades": self._discapacidades,
            "cuantas_rutinas": self._rutinas,
            "cuantos_atletas": self._atletas,
            "dashboard_plataforma": self._dashboard,
            "panel_organizador": self._panel_organizador,
            "panel_entrenador": self._panel_entrenador,
        }
        manejador = handlers.get(comando)
        if not manejador:
            return self._paquete("No reconozco esa métrica.", comando, {})
        return await manejador(usuario_id, mensaje, authorization, rol)

    def _paquete(
        self,
        texto: str,
        intencion: str,
        datos: dict[str, Any],
        herramientas: Optional[list[str]] = None,
    ) -> dict[str, Any]:
        """Dict de chat (motor local) con KPIs opcionales para cards."""
        return {
            "respuesta": texto,
            "intencion": intencion,
            "adaptada": False,
            "sugerencias": [],
            "datos": datos,
            "fuente": "motor_local",
            "herramientas_usadas": herramientas or ["metricas_plataforma"],
            "sintesis_llm": False,
        }

    def _denegar(self, intencion: str, detalle: str) -> dict[str, Any]:
        """Respuesta cuando el rol JWT no cubre el panel pedido."""
        return self._paquete(
            detalle,
            intencion,
            {"error": "rol_insuficiente"},
            ["metricas_plataforma"],
        )

    async def _asociaciones(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Cuenta asociaciones deporte–discapacidad, agrupadas por deporte."""
        filas = await self.sports.get_asociaciones(authorization)
        if not filas:
            panel = await self.reports.dashboard_asociaciones(authorization)
            crudo = (panel or {}).get("associations") or (panel or {}).get("asociaciones") or []
            filas = crudo if isinstance(crudo, list) else []
        if not filas:
            if rol not in _ADMIN_ENT and rol not in _STAFF:
                return self._denegar(
                    "asociaciones_por_deporte",
                    "El recuento de asociaciones lo ven entrenadores y admin "
                    "en Asociaciones. Tú puedes preguntarme las adaptaciones de un deporte concreto.",
                )
            return self._paquete(
                "No pude leer las asociaciones ahora. Revisa la página Asociaciones del panel.",
                "asociaciones_por_deporte",
                {"asociaciones": []},
            )

        por_deporte: dict[str, list[str]] = defaultdict(list)
        for item in filas:
            if not isinstance(item, dict):
                continue
            deporte = _nombre(item, "sportName", "sport_name", "deporte") or "Sin deporte"
            disc = _nombre(item, "disabilityName", "disability_name", "discapacidad") or "—"
            por_deporte[deporte].append(disc)

        lineas = [f"Hay {len(filas)} asociaciones deporte–discapacidad:"]
        kpis = []
        for deporte, discs in sorted(por_deporte.items(), key=lambda x: (-len(x[1]), x[0].lower())):
            muestra = ", ".join(discs[:6])
            extra = "" if len(discs) <= 6 else f" y {len(discs) - 6} más"
            lineas.append(f"- {deporte}: {len(discs)} ({muestra}{extra})")
            kpis.append({"titulo": deporte, "valor": len(discs), "meta": discs[:4]})
        return self._paquete(
            "\n".join(lineas),
            "asociaciones_por_deporte",
            {
                "total": len(filas),
                "por_deporte": {k: len(v) for k, v in por_deporte.items()},
                "kpis": kpis[:12],
            },
        )

    async def _usuarios(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Totales de usuarios (dashboard admin) o recuento inactivos."""
        if rol not in _ADMIN_ORG:
            return self._denegar(
                "cuantos_usuarios",
                "El recuento de usuarios es para organizador o admin. "
                "Con tu rol puedo hablarte de eventos, deportes y tu progreso.",
            )
        texto = normalizar(mensaje)
        if "inactivo" in texto:
            inactivos = await self.users.list_inactive_users(authorization)
            n = len(inactivos) if isinstance(inactivos, list) else 0
            return self._paquete(
                f"Hay {n} usuarios inactivos.",
                "cuantos_usuarios",
                {"filtro": "inactivos", "total": n, "kpis": [{"titulo": "Inactivos", "valor": n}]},
                ["listar_usuarios"],
            )
        dash = await self.reports.dashboard(authorization=authorization)
        total = _entero(dash, "total_users", "totalUsers")
        activos = _entero(dash, "active_users", "activeUsers")
        if total is None:
            todos = await self.users.list_users(authorization=authorization)
            total = len(todos) if isinstance(todos, list) else 0
        if activos is None:
            activos_lista = await self.users.list_users(authorization=authorization, solo_activos=True)
            activos = len(activos_lista) if isinstance(activos_lista, list) else total
        return self._paquete(
            f"Usuarios registrados: {total}. Activos: {activos}.",
            "cuantos_usuarios",
            {
                "total": total,
                "activos": activos,
                "kpis": [
                    {"titulo": "Usuarios", "valor": total},
                    {"titulo": "Activos", "valor": activos},
                ],
            },
            ["consultar_dashboard"],
        )

    async def _eventos(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Cuenta eventos del catálogo (activos vs todos)."""
        todos = await self.sports.get_eventos(authorization)
        activos = await self.sports.get_eventos_activos(authorization)
        n_todos = len(todos)
        n_activos = len(activos)
        return self._paquete(
            f"Hay {n_activos} eventos vigentes y {n_todos} en el catálogo (incluye cerrados).",
            "cuantos_eventos",
            {
                "total": n_todos,
                "activos": n_activos,
                "kpis": [
                    {"titulo": "Eventos vigentes", "valor": n_activos},
                    {"titulo": "En catálogo", "valor": n_todos},
                ],
            },
            ["listar_eventos"],
        )

    async def _deportes(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Cuenta deportes activos."""
        deportes = await self.sports.get_deportes_activos(authorization)
        n = len(deportes)
        nombres = [_nombre(d, "name", "nombre") for d in deportes[:8] if isinstance(d, dict)]
        extra = f" Entre ellos: {', '.join(x for x in nombres if x)}." if nombres else ""
        return self._paquete(
            f"Hay {n} deportes activos.{extra}",
            "cuantos_deportes",
            {"total": n, "kpis": [{"titulo": "Deportes activos", "valor": n}]},
            ["listar_deportes"],
        )

    async def _discapacidades(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Cuenta tipos de discapacidad activos."""
        items = await self.sports.get_discapacidades_activas(authorization)
        n = len(items)
        nombres = [_nombre(d, "name", "nombre") for d in items[:8] if isinstance(d, dict)]
        extra = f" {', '.join(x for x in nombres if x)}." if nombres else ""
        return self._paquete(
            f"Hay {n} tipos de discapacidad activos.{extra}",
            "cuantas_discapacidades",
            {"total": n, "kpis": [{"titulo": "Discapacidades", "valor": n}]},
            ["listar_discapacidades"],
        )

    async def _rutinas(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Cuenta rutinas publicadas."""
        rutinas = await self.sports.get_rutinas_publicadas(authorization)
        n = len(rutinas)
        return self._paquete(
            f"Hay {n} rutinas publicadas.",
            "cuantas_rutinas",
            {"total": n, "kpis": [{"titulo": "Rutinas publicadas", "valor": n}]},
            ["listar_rutinas_publicadas"],
        )

    async def _atletas(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Panel de atletas (espera y asistencia por evento)."""
        if rol not in _ORG_STAFF:
            return self._denegar(
                "cuantos_atletas",
                "El resumen de atletas inscritos es para entrenador, organizador o admin.",
            )
        org_id = usuario_id if rol == "ORGANIZADOR" else None
        panel = await self.reports.dashboard_atletas(
            authorization=authorization,
            organizer_id=org_id,
            all_events=rol == "ADMIN",
        )
        resumenes = panel.get("athleteSummaries") or panel.get("athlete_summaries") or []
        eventos = panel.get("events") or []
        n_eventos = len(eventos) if isinstance(eventos, list) else 0
        n_res = len(resumenes) if isinstance(resumenes, list) else 0
        lineas = [
            f"Hay datos de atletas en {n_res} eventos muestreados "
            f"(catálogo con {n_eventos} eventos)."
        ]
        for item in (resumenes if isinstance(resumenes, list) else [])[:6]:
            if not isinstance(item, dict):
                continue
            ev = item.get("event") if isinstance(item.get("event"), dict) else {}
            nombre = _nombre(ev, "name", "nombre") or "Evento"
            espera = item.get("waitlist") or []
            n_espera = len(espera) if isinstance(espera, list) else 0
            lineas.append(f"- {nombre}: {n_espera} en lista de espera")
        return self._paquete(
            "\n".join(lineas),
            "cuantos_atletas",
            {
                "eventos_total": n_eventos,
                "resumenes": n_res,
                "kpis": [{"titulo": "Eventos con ficha", "valor": n_res}],
            },
            ["consultar_dashboard"],
        )

    async def _dashboard(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """KPIs globales de Reports (admin/organizador)."""
        if rol not in _ADMIN_ORG:
            return self._denegar(
                "dashboard_plataforma",
                "El dashboard de la plataforma es para organizador o admin. "
                "Pide «mi dashboard» para ver tus métricas personales.",
            )
        dash = await self.reports.dashboard(authorization=authorization)
        if not dash:
            return self._paquete(
                "No pude leer el dashboard ahora. Ábrelo en el panel admin.",
                "dashboard_plataforma",
                {},
            )
        total_u = _entero(dash, "total_users", "totalUsers") or 0
        activos = _entero(dash, "active_users", "activeUsers") or 0
        eventos = _entero(dash, "active_events", "activeEvents") or 0
        deportes = _entero(dash, "total_sports", "totalSports") or 0
        discs = _entero(dash, "total_disabilities", "totalDisabilities") or 0
        texto = (
            f"Plataforma: {total_u} usuarios ({activos} activos), "
            f"{eventos} eventos activos, {deportes} deportes y {discs} discapacidades."
        )
        return self._paquete(
            texto,
            "dashboard_plataforma",
            {
                "metrics": dash.get("metrics") or {},
                "kpis": [
                    {"titulo": "Usuarios", "valor": total_u},
                    {"titulo": "Activos", "valor": activos},
                    {"titulo": "Eventos", "valor": eventos},
                    {"titulo": "Deportes", "valor": deportes},
                    {"titulo": "Discapacidades", "valor": discs},
                ],
            },
            ["consultar_dashboard"],
        )

    async def _panel_organizador(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Eventos, aforo y asistencia del organizador."""
        if rol not in _ADMIN_ORG:
            return self._denegar(
                "panel_organizador",
                "Ese resumen es para organizador o admin.",
            )
        org_id = usuario_id if rol == "ORGANIZADOR" else None
        panel = await self.reports.dashboard_organizador(org_id, authorization)
        eventos_n = _entero(panel, "active_events", "activeEvents")
        if eventos_n is None:
            evs = panel.get("events") or []
            eventos_n = len(evs) if isinstance(evs, list) else 0
        atletas = panel.get("athleteCount")
        if atletas is None:
            atletas = _entero(panel, "athletes")
        asistencia = panel.get("attendanceRatePercent")
        partes = [f"Eventos del panel: {eventos_n}."]
        if atletas is not None:
            partes.append(f"Atletas (ocupados): {atletas}.")
        if asistencia is not None:
            partes.append(f"Tasa de asistencia (muestra): {asistencia}%.")
        return self._paquete(
            " ".join(partes),
            "panel_organizador",
            {
                "athleteCount": atletas,
                "attendanceRatePercent": asistencia,
                "kpis": [
                    {"titulo": "Eventos", "valor": eventos_n},
                    {"titulo": "Atletas", "valor": atletas if atletas is not None else "—"},
                ],
            },
            ["consultar_dashboard"],
        )

    async def _panel_entrenador(
        self,
        usuario_id: str,
        mensaje: str,
        authorization: Optional[str],
        rol: str,
    ) -> dict[str, Any]:
        """Rutinas y atletas del entrenador."""
        if rol not in _ADMIN_ENT:
            return self._denegar(
                "panel_entrenador",
                "Ese resumen es para entrenador o admin.",
            )
        trainer_id = usuario_id if rol == "ENTRENADOR" else usuario_id
        panel = await self.reports.dashboard_entrenador(trainer_id, authorization)
        rutinas = _entero(panel, "routines") or 0
        publicadas = _entero(panel, "published") or 0
        atletas = panel.get("athleteCount")
        if atletas is None:
            atletas = _entero(panel, "athletes") or 0
        return self._paquete(
            (
                f"Tus números de entrenador: {rutinas} rutinas ({publicadas} publicadas) "
                f"y {atletas} atletas inscritos en ellas."
            ),
            "panel_entrenador",
            {
                "metrics": panel.get("metrics") or {},
                "kpis": [
                    {"titulo": "Rutinas", "valor": rutinas},
                    {"titulo": "Publicadas", "valor": publicadas},
                    {"titulo": "Atletas", "valor": atletas},
                ],
            },
            ["consultar_dashboard"],
        )
