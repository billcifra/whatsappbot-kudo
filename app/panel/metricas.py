"""Cálculo de métricas para el panel: series diarias en hora local y normalización del embudo.

La disciplina, el turno y el día llegan como texto libre del agente ("BJJ", "jiu jitsu", "en la
noche"…): se agrupan en categorías fijas para poder contarlas.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

DISCIPLINAS = ["Kudo", "BJJ", "Kick Boxing", "Defensa personal", "Otra"]
TURNOS = ["Mañana", "Tarde", "Noche", "Otro"]
DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo", "Otro"]

_CLAVES_DISCIPLINA = [
    ("Kick Boxing", ("kick", "boxing", "boxeo")),
    ("BJJ", ("bjj", "jiu", "jitsu", "brazil", "brasil", "grappling")),
    ("Kudo", ("kudo", "daido")),
    ("Defensa personal", ("defensa",)),
]
_CLAVES_TURNO = [
    ("Mañana", ("manana", "matutin", " am ", "a.m")),
    ("Tarde", ("tarde", "vespertin", " pm ", "p.m")),
    ("Noche", ("noche", "nocturn")),
]
_CLAVES_DIA = [
    ("Lunes", ("lunes",)), ("Martes", ("martes",)), ("Miércoles", ("miercoles",)), ("Jueves", ("jueves",)),
    ("Viernes", ("viernes",)), ("Sábado", ("sabado", "fin de semana", "finde")), ("Domingo", ("domingo",)),
]


def _simple(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return f" {sin_tildes.lower().strip()} "


def _categoria(texto: str | None, claves: list[tuple[str, tuple[str, ...]]], otra: str) -> str | None:
    if not texto or not texto.strip():
        return None
    t = _simple(texto)
    for nombre, palabras in claves:
        if any(p in t for p in palabras):
            return nombre
    return otra


def disciplina(texto: str | None) -> str | None:
    return _categoria(texto, _CLAVES_DISCIPLINA, "Otra")


def turno(texto: str | None) -> str | None:
    return _categoria(texto, _CLAVES_TURNO, "Otro")


def dia(texto: str | None) -> str | None:
    return _categoria(texto, _CLAVES_DIA, "Otro")


def conteo(valores: list[str | None], orden: list[str]) -> list[tuple[str, int]]:
    """Cuenta por categoría en el orden fijo dado, omitiendo las vacías."""
    c = Counter(v for v in valores if v)
    return [(cat, c[cat]) for cat in orden if c[cat]]


def serie_diaria(marcas: list[float], dias: int, zona: ZoneInfo, hoy: date) -> list[tuple[date, int]]:
    """Cantidad por día local para los últimos `dias` días (incluye hoy y los días en cero)."""
    c = Counter(datetime.fromtimestamp(ts, zona).date() for ts in marcas)
    inicio = hoy - timedelta(days=dias - 1)
    return [(inicio + timedelta(days=i), c[inicio + timedelta(days=i)]) for i in range(dias)]


def inicio_de(fecha: date, zona: ZoneInfo) -> float:
    return datetime(fecha.year, fecha.month, fecha.day, tzinfo=zona).timestamp()
