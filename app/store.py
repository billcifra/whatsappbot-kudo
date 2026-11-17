"""Almacenamiento en SQLite (un archivo en DATA_DIR; en Railway, el volumen montado en /data).

Guarda contactos con su perfil del embudo, el historial, los eventos para el panel, las solicitudes
de atención humana, las pausas del bot, el consumo de la IA y los usuarios del panel.
Una sola conexión protegida con un lock: el servidor corre en un único proceso.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

ESQUEMA = """
CREATE TABLE IF NOT EXISTS contactos (
    wa_id TEXT PRIMARY KEY,
    nombre TEXT,                 -- nombre que dio en la conversación
    nombre_perfil TEXT,          -- nombre de perfil de WhatsApp
    disciplina TEXT,
    turno TEXT,
    dia TEXT,
    tema TEXT,                   -- última opción del menú ('1'-'7'), 'libre' o 'nuevo'
    bienvenido INTEGER NOT NULL DEFAULT 0,
    primer_contacto REAL NOT NULL,
    ultimo_mensaje REAL          -- último mensaje DEL CLIENTE (ventana de 24 h)
);
CREATE INDEX IF NOT EXISTS idx_contactos_primer ON contactos (primer_contacto);
CREATE INDEX IF NOT EXISTS idx_contactos_ultimo ON contactos (ultimo_mensaje);

CREATE TABLE IF NOT EXISTS mensajes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_id TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('user', 'assistant', 'staff')),
    contenido TEXT NOT NULL,
    tipo TEXT NOT NULL DEFAULT 'text',   -- text, audio, menu, otro, bienvenida
    para_agente INTEGER NOT NULL DEFAULT 1,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mensajes_wa ON mensajes (wa_id, id);
CREATE INDEX IF NOT EXISTS idx_mensajes_ts ON mensajes (ts);

CREATE TABLE IF NOT EXISTS eventos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_id TEXT,
    tipo TEXT NOT NULL,          -- nuevo_usuario, menu, agente, datos_prospecto, solicitud_humana, no_soportado
    detalle TEXT,
    ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eventos_tipo ON eventos (tipo, ts);

CREATE TABLE IF NOT EXISTS solicitudes_humano (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    wa_id TEXT NOT NULL,
    mensaje TEXT,
    ts REAL NOT NULL,
    atendida REAL,               -- epoch en que se marcó atendida; NULL = pendiente
    atendida_por TEXT
);
CREATE INDEX IF NOT EXISTS idx_solicitudes_pend ON solicitudes_humano (atendida, ts);

CREATE TABLE IF NOT EXISTS pausas (
    wa_id TEXT PRIMARY KEY,
    hasta REAL NOT NULL,
    motivo TEXT
);

CREATE TABLE IF NOT EXISTS procesados (
    msg_id TEXT PRIMARY KEY,
    ts REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS consumo (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    wa_id TEXT,
    entrada INTEGER NOT NULL DEFAULT 0,
    salida INTEGER NOT NULL DEFAULT 0,
    costo_usd REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_consumo_ts ON consumo (ts);

CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario TEXT NOT NULL UNIQUE,
    nombre TEXT,
    hash TEXT NOT NULL,
    activo INTEGER NOT NULL DEFAULT 1,
    creado REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS sesiones (
    token_sha256 TEXT PRIMARY KEY,
    usuario_id INTEGER NOT NULL,
    csrf TEXT NOT NULL,
    expira REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);
"""

# Columnas agregadas después del esquema original: (tabla, columna, definición).
# Se aplican con ALTER TABLE solo si faltan, para no romper bases ya desplegadas.
COLUMNAS_NUEVAS: list[tuple[str, str, str]] = [
    ("contactos", "edad", "TEXT"),     # edad (texto libre) del alumno; sobre todo niños y jóvenes
    ("contactos", "evento", "TEXT"),   # EVENTO_ID del evento temporal que le interesó (p. ej. curso vacacional)
]

CAMPOS_PERFIL = ("nombre", "disciplina", "turno", "dia", "edad", "evento")


class Store:
    def __init__(self, ruta: Path | str):
        self._lock = threading.Lock()
        self._diferir = False
        self._db = sqlite3.connect(str(ruta), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(ESQUEMA)
        for tabla, columna, definicion in COLUMNAS_NUEVAS:
            existentes = {f["name"] for f in self._db.execute(f"PRAGMA table_info({tabla})")}
            if columna not in existentes:
                self._db.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
        self._db.commit()

    def _ejecutar(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, params)
            if not self._diferir:
                self._db.commit()
            return cur

    @contextmanager
    def en_lote(self) -> Iterator[None]:
        """Agrupa muchas escrituras en una sola transacción (todo o nada). Solo para tareas de arranque
        (migraciones, importaciones), cuando todavía no se atienden mensajes."""
        self._diferir = True
        try:
            yield
        except BaseException:
            with self._lock:
                self._db.rollback()
            raise
        else:
            with self._lock:
                self._db.commit()
        finally:
            self._diferir = False

    def _consultar(self, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(f) for f in self._db.execute(sql, params).fetchall()]

    def cerrar(self) -> None:
        with self._lock:
            self._db.close()

    # --- Meta (marcas internas, p. ej. migraciones hechas) --------------------
    def meta(self, clave: str) -> str | None:
        filas = self._consultar("SELECT valor FROM meta WHERE clave = ?", (clave,))
        return filas[0]["valor"] if filas else None

    def poner_meta(self, clave: str, valor: str) -> None:
        self._ejecutar("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?, ?)", (clave, valor))

    # --- Deduplicación (Meta reintenta webhooks) -------------------------------
    def marcar_procesado(self, msg_id: str) -> bool:
        """True si el mensaje es nuevo; False si ya se había visto."""
        try:
            self._ejecutar("INSERT INTO procesados (msg_id, ts) VALUES (?, ?)", (msg_id, time.time()))
            return True
        except sqlite3.IntegrityError:
            return False

    def limpiar_procesados(self, antes_de: float) -> None:
        self._ejecutar("DELETE FROM procesados WHERE ts < ?", (antes_de,))

    # --- Contactos y perfil del embudo ---------------------------------------------
    def contacto(self, wa_id: str) -> dict[str, Any] | None:
        filas = self._consultar("SELECT * FROM contactos WHERE wa_id = ?", (wa_id,))
        return filas[0] if filas else None

    def registrar_entrante(self, wa_id: str, nombre_perfil: str | None, ts: float | None = None) -> dict[str, Any]:
        """Crea el contacto si no existe y anota la hora de su último mensaje. Devuelve el contacto."""
        ts = ts or time.time()
        self._ejecutar(
            "INSERT INTO contactos (wa_id, nombre_perfil, primer_contacto, ultimo_mensaje) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(wa_id) DO UPDATE SET ultimo_mensaje = excluded.ultimo_mensaje, "
            "nombre_perfil = COALESCE(excluded.nombre_perfil, nombre_perfil)",
            (wa_id, nombre_perfil, ts, ts),
        )
        return self.contacto(wa_id)  # type: ignore[return-value]

    def ajustar_fechas_contacto(self, wa_id: str, primero: float, ultimo: float) -> None:
        """Amplía el rango del contacto: primer_contacto más antiguo y ultimo_mensaje más reciente."""
        self._ejecutar(
            "UPDATE contactos SET primer_contacto = MIN(primer_contacto, ?), "
            "ultimo_mensaje = MAX(COALESCE(ultimo_mensaje, 0), ?) WHERE wa_id = ?", (primero, ultimo, wa_id))

    def completar_perfil(self, wa_id: str, **datos: str) -> None:
        """Como actualizar_perfil, pero solo llena los campos que están vacíos."""
        c = self.contacto(wa_id) or {}
        self.actualizar_perfil(wa_id, **{k: v for k, v in datos.items() if not (c.get(k) or "").strip()})

    def marcar_bienvenido(self, wa_id: str) -> None:
        self._ejecutar("UPDATE contactos SET bienvenido = 1, tema = 'nuevo' WHERE wa_id = ?", (wa_id,))

    def poner_tema(self, wa_id: str, tema: str) -> None:
        self._ejecutar("UPDATE contactos SET tema = ? WHERE wa_id = ?", (tema, wa_id))

    def actualizar_perfil(self, wa_id: str, **datos: str) -> dict[str, Any]:
        """Guarda solo los campos con valor (CAMPOS_PERFIL). Devuelve el contacto."""
        cambios = {k: v.strip() for k, v in datos.items() if k in CAMPOS_PERFIL and v and v.strip()}
        if self.contacto(wa_id) is None:
            self.registrar_entrante(wa_id, None)
        if cambios:
            asignaciones = ", ".join(f"{k} = ?" for k in cambios)
            self._ejecutar(f"UPDATE contactos SET {asignaciones} WHERE wa_id = ?", (*cambios.values(), wa_id))
        return self.contacto(wa_id)  # type: ignore[return-value]

    # --- Historial ------------------------------------------------------------------
    def agregar_mensaje(self, wa_id: str, rol: str, contenido: str, tipo: str = "text",
                        para_agente: bool = True, ts: float | None = None) -> None:
        self._ejecutar(
            "INSERT INTO mensajes (wa_id, rol, contenido, tipo, para_agente, ts) VALUES (?, ?, ?, ?, ?, ?)",
            (wa_id, rol, contenido, tipo, int(para_agente), ts or time.time()),
        )

    def historial(self, wa_id: str, limite: int, desde: float = 0) -> list[dict[str, str]]:
        """Últimos mensajes que ve el agente, en orden cronológico, como {role, content}."""
        filas = self._consultar(
            "SELECT rol, contenido FROM mensajes WHERE wa_id = ? AND para_agente = 1 AND ts >= ? "
            "ORDER BY id DESC LIMIT ?", (wa_id, desde, limite))
        resultado = []
        for f in reversed(filas):
            if f["rol"] == "staff":
                resultado.append({"role": "assistant", "content": f"[Respuesta de una persona del equipo] {f['contenido']}"})
            else:
                resultado.append({"role": f["rol"], "content": f["contenido"]})
        return resultado

    def mensajes_de(self, wa_id: str, limite: int = 300) -> list[dict[str, Any]]:
        """Conversación para el panel, en orden cronológico (los importados pueden tener id mayor y hora menor)."""
        filas = self._consultar(
            "SELECT rol, contenido, tipo, ts FROM mensajes WHERE wa_id = ? ORDER BY ts DESC, id DESC LIMIT ?",
            (wa_id, limite))
        return list(reversed(filas))

    def mensajes_con_id(self, wa_id: str) -> list[dict[str, Any]]:
        return self._consultar("SELECT id, rol, contenido, tipo, ts FROM mensajes WHERE wa_id = ? ORDER BY id", (wa_id,))

    def poner_ts_mensaje(self, mensaje_id: int, ts: float) -> None:
        self._ejecutar("UPDATE mensajes SET ts = ? WHERE id = ?", (ts, mensaje_id))

    # --- Eventos (para métricas) --------------------------------------------------------
    def registrar_evento(self, wa_id: str | None, tipo: str, detalle: str | dict | None = None,
                         ts: float | None = None) -> None:
        if isinstance(detalle, dict):
            detalle = json.dumps(detalle, ensure_ascii=False)
        self._ejecutar("INSERT INTO eventos (wa_id, tipo, detalle, ts) VALUES (?, ?, ?, ?)",
                       (wa_id, tipo, detalle, ts or time.time()))

    def eventos_desde(self, tipo: str, desde: float) -> list[dict[str, Any]]:
        return self._consultar("SELECT wa_id, detalle, ts FROM eventos WHERE tipo = ? AND ts >= ? ORDER BY ts",
                               (tipo, desde))

    # --- Solicitudes de atención humana ----------------------------------------------------
    def crear_solicitud(self, wa_id: str, mensaje: str, ts: float | None = None, atendida: float | None = None,
                        atendida_por: str | None = None) -> int:
        return int(self._ejecutar(
            "INSERT INTO solicitudes_humano (wa_id, mensaje, ts, atendida, atendida_por) VALUES (?, ?, ?, ?, ?)",
            (wa_id, mensaje, ts or time.time(), atendida, atendida_por)).lastrowid)

    def solicitudes_pendientes(self, limite: int = 50) -> list[dict[str, Any]]:
        return self._consultar(
            "SELECT s.*, c.nombre, c.nombre_perfil FROM solicitudes_humano s LEFT JOIN contactos c ON c.wa_id = s.wa_id "
            "WHERE s.atendida IS NULL ORDER BY s.ts DESC LIMIT ?", (limite,))

    def solicitudes_de(self, wa_id: str, limite: int = 10) -> list[dict[str, Any]]:
        return self._consultar("SELECT * FROM solicitudes_humano WHERE wa_id = ? ORDER BY ts DESC LIMIT ?",
                               (wa_id, limite))

    def marcar_atendida(self, solicitud_id: int, usuario: str) -> bool:
        return self._ejecutar(
            "UPDATE solicitudes_humano SET atendida = ?, atendida_por = ? WHERE id = ? AND atendida IS NULL",
            (time.time(), usuario, solicitud_id)).rowcount > 0

    # --- Pausas del bot --------------------------------------------------------------------
    def pausar(self, wa_id: str, horas: float, motivo: str = "") -> None:
        self._ejecutar("INSERT OR REPLACE INTO pausas (wa_id, hasta, motivo) VALUES (?, ?, ?)",
                       (wa_id, time.time() + horas * 3600, motivo))

    def reactivar(self, wa_id: str) -> bool:
        return self._ejecutar("DELETE FROM pausas WHERE wa_id = ?", (wa_id,)).rowcount > 0

    def pausa_de(self, wa_id: str) -> dict[str, Any] | None:
        filas = self._consultar("SELECT * FROM pausas WHERE wa_id = ? AND hasta > ?", (wa_id, time.time()))
        return filas[0] if filas else None

    def esta_pausado(self, wa_id: str) -> bool:
        return self.pausa_de(wa_id) is not None

    def pausas_activas(self) -> list[dict[str, Any]]:
        return self._consultar(
            "SELECT p.wa_id, p.hasta, p.motivo, c.nombre, c.nombre_perfil FROM pausas p "
            "LEFT JOIN contactos c ON c.wa_id = p.wa_id WHERE p.hasta > ? ORDER BY p.hasta", (time.time(),))

    # --- Consumo de la IA ------------------------------------------------------------------
    def registrar_consumo(self, wa_id: str | None, entrada: int, salida: int, costo: float) -> None:
        self._ejecutar("INSERT INTO consumo (ts, wa_id, entrada, salida, costo_usd) VALUES (?, ?, ?, ?, ?)",
                       (time.time(), wa_id, entrada, salida, costo))

    def resumen_consumo(self, desde: float) -> dict[str, Any]:
        c = self._consultar(
            "SELECT COUNT(*) AS llamadas, COALESCE(SUM(costo_usd), 0) AS costo, "
            "COALESCE(SUM(entrada), 0) AS entrada, COALESCE(SUM(salida), 0) AS salida FROM consumo WHERE ts >= ?",
            (desde,))[0]
        m = self._consultar(
            "SELECT COUNT(*) AS mensajes, COUNT(DISTINCT wa_id) AS clientes FROM mensajes "
            "WHERE rol = 'user' AND ts >= ?", (desde,))[0]
        return {**c, **m}

    # --- Consultas para el panel ------------------------------------------------------------
    def ts_mensajes_cliente(self, desde: float) -> list[float]:
        return [f["ts"] for f in self._consultar("SELECT ts FROM mensajes WHERE rol = 'user' AND ts >= ?", (desde,))]

    def ts_primer_contacto(self, desde: float) -> list[float]:
        return [f["primer_contacto"] for f in
                self._consultar("SELECT primer_contacto FROM contactos WHERE primer_contacto >= ?", (desde,))]

    def ts_solicitudes(self, desde: float) -> list[float]:
        return [f["ts"] for f in self._consultar("SELECT ts FROM solicitudes_humano WHERE ts >= ?", (desde,))]

    def contar_contactos_desde(self, desde: float) -> int:
        return int(self._consultar("SELECT COUNT(*) AS n FROM contactos WHERE primer_contacto >= ?", (desde,))[0]["n"])

    def perfiles_desde(self, desde: float) -> list[dict[str, Any]]:
        """Perfil del embudo de los contactos con actividad desde `desde`."""
        return self._consultar(
            "SELECT nombre, disciplina, turno, dia FROM contactos WHERE COALESCE(ultimo_mensaje, primer_contacto) >= ?",
            (desde,))

    def prospectos(self, desde: float = 0, hasta: float | None = None, limite: int = 2000) -> list[dict[str, Any]]:
        hasta = hasta if hasta is not None else time.time() + 86400
        return self._consultar(
            "SELECT c.*, (SELECT COUNT(*) FROM mensajes m WHERE m.wa_id = c.wa_id AND m.rol = 'user') AS mensajes, "
            "(SELECT COUNT(*) FROM solicitudes_humano s WHERE s.wa_id = c.wa_id) AS solicitudes "
            "FROM contactos c WHERE c.primer_contacto >= ? AND c.primer_contacto < ? "
            "ORDER BY COALESCE(c.ultimo_mensaje, c.primer_contacto) DESC LIMIT ?", (desde, hasta, limite))

    def conversaciones(self, limite: int = 200) -> list[dict[str, Any]]:
        """Contactos por último mensaje, con su pausa (si tiene) y el último texto de la conversación."""
        return self._consultar(
            "SELECT c.wa_id, c.nombre, c.nombre_perfil, c.disciplina, c.ultimo_mensaje, "
            "p.hasta AS pausa_hasta, p.motivo AS pausa_motivo, "
            "(SELECT m.contenido FROM mensajes m WHERE m.wa_id = c.wa_id ORDER BY m.id DESC LIMIT 1) AS ultimo_texto, "
            "(SELECT COUNT(*) FROM solicitudes_humano s WHERE s.wa_id = c.wa_id AND s.atendida IS NULL) AS pendientes "
            "FROM contactos c LEFT JOIN pausas p ON p.wa_id = c.wa_id AND p.hasta > ? "
            "ORDER BY COALESCE(c.ultimo_mensaje, c.primer_contacto) DESC LIMIT ?", (time.time(), limite))

    def contar_contactos(self) -> int:
        return int(self._consultar("SELECT COUNT(*) AS n FROM contactos")[0]["n"])

    # --- Usuarios y sesiones del panel ---------------------------------------------------------
    def crear_usuario(self, usuario: str, nombre: str, hash_clave: str) -> int:
        try:
            return int(self._ejecutar("INSERT INTO usuarios (usuario, nombre, hash, creado) VALUES (?, ?, ?, ?)",
                                      (usuario, nombre, hash_clave, time.time())).lastrowid)
        except sqlite3.IntegrityError:
            raise ValueError(f"El usuario '{usuario}' ya existe.") from None

    def usuario(self, usuario: str) -> dict[str, Any] | None:
        filas = self._consultar("SELECT * FROM usuarios WHERE usuario = ?", (usuario,))
        return filas[0] if filas else None

    def usuarios(self) -> list[dict[str, Any]]:
        return self._consultar("SELECT id, usuario, nombre, activo, creado FROM usuarios ORDER BY usuario")

    def cambiar_clave(self, usuario: str, hash_clave: str) -> bool:
        ok = self._ejecutar("UPDATE usuarios SET hash = ?, activo = 1 WHERE usuario = ?", (hash_clave, usuario)).rowcount > 0
        self.cerrar_sesiones_de(usuario)
        return ok

    def desactivar_usuario(self, usuario: str) -> bool:
        ok = self._ejecutar("UPDATE usuarios SET activo = 0 WHERE usuario = ?", (usuario,)).rowcount > 0
        self.cerrar_sesiones_de(usuario)
        return ok

    def crear_sesion(self, token_sha256: str, usuario_id: int, csrf: str, expira: float) -> None:
        self._ejecutar("DELETE FROM sesiones WHERE expira < ?", (time.time(),))
        self._ejecutar("INSERT INTO sesiones (token_sha256, usuario_id, csrf, expira) VALUES (?, ?, ?, ?)",
                       (token_sha256, usuario_id, csrf, expira))

    def sesion(self, token_sha256: str) -> dict[str, Any] | None:
        """Sesión vigente de un usuario activo, con sus datos; None si no existe o venció."""
        filas = self._consultar(
            "SELECT s.csrf, s.expira, u.id AS usuario_id, u.usuario, u.nombre FROM sesiones s "
            "JOIN usuarios u ON u.id = s.usuario_id WHERE s.token_sha256 = ? AND s.expira > ? AND u.activo = 1",
            (token_sha256, time.time()))
        return filas[0] if filas else None

    def cerrar_sesion(self, token_sha256: str) -> None:
        self._ejecutar("DELETE FROM sesiones WHERE token_sha256 = ?", (token_sha256,))

    def cerrar_sesiones_de(self, usuario: str) -> None:
        self._ejecutar("DELETE FROM sesiones WHERE usuario_id IN (SELECT id FROM usuarios WHERE usuario = ?)", (usuario,))
