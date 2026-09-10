"""Criterios de ranking de eventos (fecha vs inscritos) sin dejarlo al LLM."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from app.nlp.texto import normalizar

_MESES = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

# Un solo evento por fecha más cercana a hoy (hoy o futuro).
_PROXIMO = (
    "mas reciente en iniciar",
    "mas reciente a iniciar",
    "reciente en iniciar",
    "proximo a iniciar",
    "el proximo evento",
    "proximo evento",
    "cual es el proximo",
    "el mas proximo",
    "el mas reciente",
    "evento mas reciente",
    "mas cercano",
    "el que inicia",
    "que inicia primero",
    "el que empieza",
    "que empieza primero",
    "el mas pronto",
    "cual inicia",
    "cuando inicia el siguiente",
)

_INSCRITOS = (
    "mas inscrito",
    "mas inscripcion",
    "con mas gente",
    "mas popular",
    "mas lleno",
    "mas cupo ocupado",
)


def fecha_evento(valor: Any) -> Optional[date]:
    """Interpreta eventDate de sports (ISO, datetime o [año, mes, día])."""
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, str):
        try:
            return datetime.fromisoformat(valor[:10]).date()
        except ValueError:
            return None
    if isinstance(valor, (list, tuple)) and len(valor) >= 3:
        try:
            return date(int(valor[0]), int(valor[1]), int(valor[2]))
        except (TypeError, ValueError):
            return None
    return None


def formatear_fecha_es(dia: date) -> str:
    """«21 de septiembre de 2026»."""
    return f"{dia.day} de {_MESES[dia.month]} de {dia.year}"


def criterio_ranking_evento(mensaje: str) -> str:
    """``proximo`` | ``mas_inscritos`` | ``lista`` según la pregunta literal."""
    texto = normalizar(mensaje)
    if not texto:
        return "lista"
    if any(p in texto for p in _INSCRITOS):
        return "mas_inscritos"
    if any(p in texto for p in _PROXIMO):
        return "proximo"
    return "lista"


def _campo(evento: dict[str, Any], *claves: str) -> Any:
    for clave in claves:
        valor = evento.get(clave)
        if valor not in (None, ""):
            return valor
    return None


def inscritos_evento(evento: dict[str, Any]) -> Optional[int]:
    """Inscritos ≈ aforo − cupos libres."""
    maximo = _campo(evento, "maxCapacity", "max_capacity")
    quedan = _campo(evento, "availableCapacity", "available_capacity", "cupos_disponibles")
    try:
        max_n = int(maximo) if maximo is not None else None
        quedan_n = int(quedan) if quedan is not None else None
    except (TypeError, ValueError):
        return None
    if max_n is None or quedan_n is None:
        return None
    return max(0, max_n - quedan_n)


def proximo_a_iniciar(
    eventos: list[dict[str, Any]], hoy: Optional[date] = None
) -> Optional[dict[str, Any]]:
    """El de fecha ≥ hoy más cercana; si todos pasaron, el que inició más tarde."""
    hoy = hoy or date.today()
    con_fecha: list[tuple[date, dict[str, Any]]] = []
    for evento in eventos:
        dia = fecha_evento(_campo(evento, "eventDate", "fecha"))
        if dia:
            con_fecha.append((dia, evento))
    futuros = sorted((p for p in con_fecha if p[0] >= hoy), key=lambda p: p[0])
    if futuros:
        return futuros[0][1]
    pasados = sorted((p for p in con_fecha if p[0] < hoy), key=lambda p: p[0], reverse=True)
    return pasados[0][1] if pasados else None


def evento_mas_inscritos(eventos: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    """El de más inscripciones; no usar si la pregunta era por fecha."""
    mejor: Optional[tuple[int, dict[str, Any]]] = None
    for evento in eventos:
        n = inscritos_evento(evento)
        if n is None:
            continue
        if mejor is None or n > mejor[0]:
            mejor = (n, evento)
    return mejor[1] if mejor else None


def linea_evento(evento: dict[str, Any]) -> str:
    """Una línea con nombre, fecha, lugar y cupos."""
    nombre = _campo(evento, "name", "nombre") or "Evento"
    deporte = _campo(evento, "sportName", "deporte")
    dia = fecha_evento(_campo(evento, "eventDate", "fecha"))
    lugar = _campo(evento, "location", "ubicacion")
    inscritos = inscritos_evento(evento)
    maximo = _campo(evento, "maxCapacity", "max_capacity")
    quedan = _campo(evento, "availableCapacity", "available_capacity", "cupos_disponibles")
    partes = [str(nombre)]
    if deporte:
        partes.append(f"({deporte})")
    if dia:
        partes.append(f"el {formatear_fecha_es(dia)} [{dia.isoformat()}]")
    if lugar:
        partes.append(f"en {lugar}")
    if inscritos is not None and maximo is not None:
        partes.append(f"· {inscritos}/{maximo} inscritos ({quedan} cupos libres)")
    elif quedan is not None:
        partes.append(f"· {quedan} cupos libres")
    return " ".join(str(p) for p in partes)


def bloque_hechos_eventos(
    eventos: list[dict[str, Any]], hoy: Optional[date] = None
) -> str:
    """Hechos ya calculados para el prompt: hoy, próximo por fecha, más inscritos."""
    hoy = hoy or date.today()
    lineas = [
        f"- Hoy: {formatear_fecha_es(hoy)} ({hoy.isoformat()})",
    ]
    proximo = proximo_a_iniciar(eventos, hoy)
    if proximo:
        lineas.append(
            "- Próximo a iniciar (fecha más cercana ≥ hoy; NO es el de más inscritos): "
            + linea_evento(proximo)
        )
    popular = evento_mas_inscritos(eventos)
    if popular:
        lineas.append(
            "- El de más inscritos (úsalo SOLO si preguntan popularidad o inscripciones): "
            + linea_evento(popular)
        )
    ordenados = sorted(
        eventos,
        key=lambda e: fecha_evento(_campo(e, "eventDate", "fecha")) or date.max,
    )
    lineas.append("- Eventos ordenados por fecha de inicio:")
    for evento in ordenados[:12]:
        lineas.append(f"  · {linea_evento(evento)}")
    return "\n".join(lineas)
