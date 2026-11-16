"""Resumen de la base SQLite (reemplaza a Pruebas/inspeccionar_redis.py). Solo lee.

    python scripts/inspeccionar_db.py                 # usa DATA_DIR del .env (o ./data)
    python scripts/inspeccionar_db.py ruta/a/kudo.db

En Railway: `railway ssh` y luego `python scripts/inspeccionar_db.py` (DATA_DIR=/data).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config import cargar_settings  # noqa: E402


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ruta = Path(sys.argv[1]) if len(sys.argv) > 1 else cargar_settings().ruta_db
    if not ruta.exists():
        sys.exit(f"No existe {ruta}")
    db = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    print(f"Base: {ruta}\n")
    for tabla in ("contactos", "mensajes", "eventos", "solicitudes_humano", "pausas", "consumo", "usuarios"):
        n = db.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        print(f"  {tabla:<20} {n}")
    print("\nEventos por tipo:")
    for f in db.execute("SELECT tipo, COUNT(*) AS n FROM eventos GROUP BY tipo ORDER BY n DESC"):
        print(f"  {f['tipo']:<20} {f['n']}")
    print("\nÚltimos 5 contactos:")
    for f in db.execute("SELECT * FROM contactos ORDER BY COALESCE(ultimo_mensaje, primer_contacto) DESC LIMIT 5"):
        print(f"  +{f['wa_id']}  {f['nombre'] or '(sin nombre)'} · {f['disciplina'] or '-'} · {f['turno'] or '-'} · "
              f"{f['dia'] or '-'}")
    migracion = db.execute("SELECT valor FROM meta WHERE clave = 'migracion_redis'").fetchone()
    print(f"\nMigración desde Redis: {migracion[0] if migracion else 'no realizada'}")


if __name__ == "__main__":
    main()
