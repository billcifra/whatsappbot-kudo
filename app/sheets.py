"""Copia secundaria de los registros en Google Sheets (hojas Interesados y SolicitudesHumano).

SQLite es la fuente de verdad. Cada fila se escribe en segundo plano (en un hilo, con reintentos):
si Google falla, solo queda un log y el bot sigue respondiendo.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from .reintentos import con_reintentos

log = logging.getLogger("sheets")

INTERESADOS = "Interesados"
SOLICITUDES = "SolicitudesHumano"


class Sheets:
    def __init__(self, sheet_key: str, credenciales_json: str):
        self._key, self._cred = sheet_key, credenciales_json
        self._hojas: dict[str, Any] = {}
        self._tareas: set[asyncio.Task] = set()
        self.activo = bool(sheet_key and credenciales_json)
        if not self.activo:
            log.warning("Google Sheets desactivado (falta GOOGLE_SHEET_KEY o GOOGLE_CREDENTIALS_JSON)")

    def _hoja(self, nombre: str):
        if nombre not in self._hojas:
            import gspread
            from google.oauth2.service_account import Credentials

            scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
            creds = Credentials.from_service_account_info(json.loads(self._cred), scopes=scope)
            self._hojas[nombre] = gspread.authorize(creds).open_by_key(self._key).worksheet(nombre)
        return self._hojas[nombre]

    def _escribir(self, hoja: str, fila: list[str]) -> None:
        con_reintentos(f"Registro en hoja {hoja}", lambda: self._hoja(hoja).append_row(fila))

    def leer(self, hoja: str) -> list[list[str]]:
        """Todas las filas de una hoja (bloqueante: llamar en un hilo)."""
        return self._hoja(hoja).get_all_values()

    def anotar(self, hoja: str, fila: list[str]) -> None:
        """Agenda la escritura de una fila sin esperar a que termine."""
        if not self.activo:
            return
        try:
            tarea = asyncio.get_running_loop().create_task(asyncio.to_thread(self._escribir, hoja, fila))
        except RuntimeError:  # sin bucle de eventos (scripts): se escribe directo
            self._escribir(hoja, fila)
            return
        self._tareas.add(tarea)
        tarea.add_done_callback(self._tareas.discard)

    async def esperar(self) -> None:
        """Espera las escrituras pendientes (al apagar el servidor)."""
        if self._tareas:
            await asyncio.gather(*self._tareas, return_exceptions=True)
