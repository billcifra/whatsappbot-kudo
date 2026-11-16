"""Importa el histórico de Google Sheets a una base SQLite desde la terminal.

En Railway no hace falta: el servidor lo hace solo al arrancar con IMPORTAR_HISTORICO_SHEETS=true.
Este script sirve para probar con los datos reales en local.

    python scripts/importar_sheets.py --simular           # lee las hojas, importa a una base temporal y muestra conteos
    python scripts/importar_sheets.py                     # importa a DATA_DIR/kudo.db (local)
    python scripts/importar_sheets.py --base otra.db
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.config import cargar_settings  # noqa: E402
from app.importacion_sheets import importar  # noqa: E402
from app.sheets import INTERESADOS, SOLICITUDES, Sheets  # noqa: E402
from app.store import Store  # noqa: E402


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base", help="ruta de la base SQLite (por defecto DATA_DIR/kudo.db)")
    p.add_argument("--simular", action="store_true", help="importa a una base temporal que se descarta")
    a = p.parse_args()

    s = cargar_settings()
    sheets = Sheets(s.google_sheet_key, s.google_credentials_json)
    if not sheets.activo:
        sys.exit("Falta GOOGLE_SHEET_KEY o las credenciales de Google.")
    interesados, solicitudes = sheets.leer(INTERESADOS), sheets.leer(SOLICITUDES)
    print(f"Leídas {len(interesados)} filas de {INTERESADOS} y {len(solicitudes)} de {SOLICITUDES}.")

    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / "simulacion.db" if a.simular else Path(a.base) if a.base else s.ruta_db
        store = Store(ruta)
        resultado = importar(store, interesados, solicitudes, set(s.numeros_personal))
        for k, v in sorted(resultado.items()):
            print(f"  {k:<40} {v}")
        print(f"  {'contactos en la base':<40} {store.contar_contactos()}")
        store.cerrar()
        print("Simulación: no se guardó nada." if a.simular else f"Base: {ruta}")


if __name__ == "__main__":
    main()
