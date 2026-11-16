"""Usuarios del panel web. Se corre donde está la base (en Railway: `railway ssh` o `railway run`):

    python -m app.panel.usuarios crear ana --nombre "Ana Pérez"
    python -m app.panel.usuarios listar
    python -m app.panel.usuarios clave ana          # cambia la contraseña y cierra sus sesiones
    python -m app.panel.usuarios desactivar ana     # ya no puede entrar; se cierran sus sesiones

La contraseña se pide por teclado. Para automatizar, --clave-stdin la lee de la entrada estándar.
Usa el DATA_DIR del .env o del entorno, igual que el servidor. Sin consola, el primer usuario se crea
con PANEL_USUARIO_INICIAL y PANEL_CLAVE_INICIAL.
"""

from __future__ import annotations

import argparse
import getpass
import re
import sys

from ..config import cargar_settings
from ..store import Store
from .auth import CLAVE_MIN, hash_clave

USUARIO_VALIDO = re.compile(r"^[a-z0-9._-]{3,40}$")


def _pedir_clave(desde_stdin: bool) -> str:
    if desde_stdin:
        clave = sys.stdin.readline().rstrip("\r\n")
    else:
        clave = getpass.getpass("Contraseña: ")
        if clave != getpass.getpass("Repítela: "):
            sys.exit("Las contraseñas no coinciden.")
    if len(clave) < CLAVE_MIN:
        sys.exit(f"La contraseña debe tener al menos {CLAVE_MIN} caracteres.")
    return clave


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m app.panel.usuarios", description="Usuarios del panel web")
    p.add_argument("accion", choices=["crear", "listar", "clave", "desactivar"])
    p.add_argument("usuario", nargs="?")
    p.add_argument("--nombre", default="")
    p.add_argument("--clave-stdin", action="store_true", help="Lee la contraseña de la entrada estándar")
    a = p.parse_args(argv)

    s = cargar_settings()
    store = Store(s.ruta_db)

    if a.accion == "listar":
        filas = store.usuarios()
        for u in filas:
            print(f"{u['usuario']:<20} {u['nombre'] or '':<25} {'activo' if u['activo'] else 'desactivado'}")
        if not filas:
            print("No hay usuarios. Crea uno con: python -m app.panel.usuarios crear <usuario>")
        return

    usuario = (a.usuario or "").strip().lower()
    if not USUARIO_VALIDO.match(usuario):
        sys.exit("Usuario inválido: 3 a 40 caracteres, solo letras minúsculas, números, punto, guion o guion bajo.")

    if a.accion == "crear":
        clave = _pedir_clave(a.clave_stdin)
        try:
            store.crear_usuario(usuario, a.nombre.strip() or usuario, hash_clave(clave))
        except ValueError as e:
            sys.exit(str(e))
        print(f"Usuario '{usuario}' creado.")
    elif a.accion == "clave":
        if not store.usuario(usuario):
            sys.exit(f"No existe el usuario '{usuario}'.")
        store.cambiar_clave(usuario, hash_clave(_pedir_clave(a.clave_stdin)))
        print(f"Contraseña de '{usuario}' cambiada; se cerraron sus sesiones.")
    elif a.accion == "desactivar":
        if not store.desactivar_usuario(usuario):
            sys.exit(f"No existe el usuario '{usuario}'.")
        print(f"Usuario '{usuario}' desactivado; se cerraron sus sesiones.")


if __name__ == "__main__":
    main()
