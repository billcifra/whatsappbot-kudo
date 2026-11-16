"""Autenticación del panel: contraseñas con scrypt, sesiones en SQLite, CSRF y bloqueo por intentos fallidos.

Solo usa la biblioteca estándar. La cookie lleva un token aleatorio; en la base se guarda su sha256, así que
una copia de la base no permite entrar con sesiones vigentes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict
from typing import Any

from ..store import Store

COOKIE_SESION = "panel_sesion"
COOKIE_CSRF_ENTRAR = "panel_csrf_entrar"
MAX_FALLOS = 5
BLOQUEO_SEG = 15 * 60
CLAVE_MIN = 10
_N, _R, _P, _LARGO = 2 ** 14, 8, 1, 32


def _b64(datos: bytes) -> str:
    return base64.b64encode(datos).decode()


def hash_clave(clave: str) -> str:
    sal = secrets.token_bytes(16)
    h = hashlib.scrypt(clave.encode(), salt=sal, n=_N, r=_R, p=_P, dklen=_LARGO)
    return f"scrypt${_N}${_R}${_P}${_b64(sal)}${_b64(h)}"


def verificar_clave(clave: str, guardado: str) -> bool:
    try:
        _, n, r, p, sal, h = guardado.split("$")
        calculado = hashlib.scrypt(clave.encode(), salt=base64.b64decode(sal), n=int(n), r=int(r), p=int(p),
                                   dklen=len(base64.b64decode(h)))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calculado, base64.b64decode(h))


# Hash de relleno: se verifica contra él cuando el usuario no existe, para que la demora sea la misma.
_HASH_RELLENO = hash_clave(secrets.token_urlsafe(16))


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Bloqueos:
    """Intentos fallidos por usuario, en memoria (se reinicia con el proceso)."""

    def __init__(self) -> None:
        self._fallos: dict[str, list[float]] = defaultdict(list)

    def bloqueado(self, usuario: str) -> bool:
        ahora = time.time()
        self._fallos[usuario] = [t for t in self._fallos[usuario] if ahora - t < BLOQUEO_SEG]
        return len(self._fallos[usuario]) >= MAX_FALLOS

    def fallo(self, usuario: str) -> None:
        self._fallos[usuario].append(time.time())

    def limpiar(self, usuario: str) -> None:
        self._fallos.pop(usuario, None)


def autenticar(store: Store, bloqueos: Bloqueos, usuario: str, clave: str) -> tuple[dict[str, Any] | None, str]:
    """Devuelve (usuario, '') si las credenciales son correctas, o (None, motivo)."""
    usuario = usuario.strip().lower()
    if bloqueos.bloqueado(usuario):
        return None, "Demasiados intentos fallidos. Espera 15 minutos e inténtalo de nuevo."
    u = store.usuario(usuario) if usuario else None
    ok = verificar_clave(clave, u["hash"] if u else _HASH_RELLENO)
    if not u or not ok or not u["activo"]:
        bloqueos.fallo(usuario)
        return None, "Usuario o contraseña incorrectos."
    bloqueos.limpiar(usuario)
    return u, ""


def crear_sesion(store: Store, usuario_id: int, horas: float) -> str:
    """Crea la sesión y devuelve el token que va en la cookie."""
    token = secrets.token_urlsafe(32)
    store.crear_sesion(_sha(token), usuario_id, secrets.token_urlsafe(24), time.time() + horas * 3600)
    return token


def sesion(store: Store, token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    return store.sesion(_sha(token))


def cerrar_sesion(store: Store, token: str | None) -> None:
    if token:
        store.cerrar_sesion(_sha(token))


def csrf_valido(esperado: str | None, recibido: str | None) -> bool:
    return bool(esperado) and bool(recibido) and hmac.compare_digest(str(esperado), str(recibido))


def nuevo_csrf() -> str:
    return secrets.token_urlsafe(24)
