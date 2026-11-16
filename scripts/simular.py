"""Chat por terminal contra el agente REAL de OpenAI, sin WhatsApp ni Google Sheets.

Reemplaza a Pruebas/test_agente.py y Pruebas/test_embudo.py: sirve para ver cómo responde el bot
(bienvenida, menú 1-7, embudo, herramientas) antes de desplegar. Usa una base aparte
(data/simulador.db) para no mezclar con la real. Gasta tokens de OpenAI.

    python scripts/simular.py                       # interactivo; "salir" para terminar
    python scripts/simular.py "Hola" "Juan" "bjj"   # manda esos mensajes en orden
    python scripts/simular.py --nuevo ...           # empieza con la base vacía
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from app.agente import AgenteKudo  # noqa: E402
from app.config import cargar_settings  # noqa: E402
from app.main import Servicio  # noqa: E402
from app.sheets import Sheets  # noqa: E402
from app.store import Store  # noqa: E402
from app.transcripcion import Transcriptor  # noqa: E402
from app.whatsapp import MensajeEntrante  # noqa: E402

TELEFONO = "59170000000"


class WhatsAppConsola:
    def __init__(self, personal: set[str]):
        self.personal = personal

    async def enviar_texto(self, para, texto):
        quien = "AVISO AL EQUIPO" if para in self.personal else "BOT"
        print(f"\n[{quien} → {para}]\n{texto}")
        return True

    async def enviar_menu(self, para, cuerpo=""):
        print("\n[BOT] (menú interactivo: Horarios · Precios · Disciplinas · Inscripción · Ubicación · "
              "¿Qué es Kudo? · Venta de Guantes)")
        return True

    async def marcar_leido_y_escribiendo(self, msg_id):
        pass

    async def descargar_media(self, media_id):
        return None, ""

    async def cerrar(self):
        pass


async def principal(mensajes: list[str], nuevo: bool) -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    s = cargar_settings()
    ruta = s.data_dir / "simulador.db"
    if nuevo and ruta.exists():
        ruta.unlink()
    store = Store(ruta)
    svc = Servicio(s, store, AgenteKudo(s.modelo), WhatsAppConsola(set(s.numeros_personal)),
                   Sheets("", ""), Transcriptor(s.openai_api_key))
    print(f"Simulador con el número {TELEFONO} · base {ruta} · modelo {s.modelo}")
    n = 0

    async def mandar(texto: str) -> None:
        nonlocal n
        n += 1
        print(f"\n[CLIENTE] {texto}")
        await svc.procesar(MensajeEntrante(f"sim.{time.time()}.{n}", TELEFONO, "Simulado", "text", texto))

    if mensajes:
        for m in mensajes:
            await mandar(m)
    else:
        while True:
            try:
                texto = input("\nTú: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if texto.lower() in ("salir", "exit", "quit"):
                break
            if texto:
                await mandar(texto)
    c = store.contacto(TELEFONO) or {}
    print("\nPerfil guardado:", {k: c.get(k) for k in ("nombre", "disciplina", "turno", "dia")})
    print("Consumo:", store.resumen_consumo(0))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("mensajes", nargs="*")
    p.add_argument("--nuevo", action="store_true", help="borra data/simulador.db antes de empezar")
    a = p.parse_args()
    asyncio.run(principal(a.mensajes, a.nuevo))
