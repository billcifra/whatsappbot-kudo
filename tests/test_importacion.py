"""Importación del histórico de Google Sheets."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from app.importacion_sheets import fecha_utc, importar
from app.main import _importar_si_corresponde
from app.migracion import migrar_desde_redis
from app.store import Store
from conftest import armar
from test_store import RedisFalso

EQUIPO = "59179598641"


def ts(texto: str) -> float:
    return datetime.strptime(texto, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()


INTERESADOS = [
    ["59169987019", "Hola quiero información", "2025-06-20 08:09:43", "nombre", "disciplina_interesada", "turno_preferido", ""],
    ["59160000001", "[NUEVO USUARIO] Hola, vi el anuncio", "2026-01-10 13:00:00"],
    ["59160000001", "Juan", "2026-01-10 13:01:00"],
    ["59160000001", "[DATOS PROSPECTO]", "2026-01-10 13:01:05", "Juan", "", "", ""],
    ["59160000001", "bjj en la noche", "2026-01-10 13:02:00", "Juan", "", ""],
    ["59160000001", "[DATOS PROSPECTO]", "2026-01-10 13:02:05", "Juan", "BJJ", "noche", "lunes"],
    ["TEST", "Prueba manual", "2025-06-01 10:00:00"],
    [EQUIPO, "cual es la direccion?", "2026-11-14 12:27:00"],
    ["59160000002", "sin fecha", "ayer"],
]
SOLICITUDES = [
    ["59160000001", "quiero hablar con alguien", "2026-01-10 13:05:00"],
    [EQUIPO, "prueba", "2026-01-11 10:00:00"],
]


def test_fechas_en_utc():
    assert fecha_utc("2026-01-10 13:00:00") == ts("2026-01-10 13:00:00")
    assert fecha_utc("10/01/2026") is None


def test_importa_contactos_eventos_y_solicitudes(tmp_path):
    st = Store(tmp_path / "t.db")
    r = importar(st, INTERESADOS, SOLICITUDES, {EQUIPO})
    assert r["contactos_nuevos"] == 2 and r["solicitudes"] == 1
    assert r["descartadas: número del equipo"] == 2
    assert r["descartadas: sin teléfono / TEST / encabezado"] == 1 and r["descartadas: sin fecha válida"] == 1
    assert st.contacto(EQUIPO) is None

    c = st.contacto("59160000001")
    assert (c["nombre"], c["disciplina"], c["turno"], c["dia"]) == ("Juan", "BJJ", "noche", "lunes")
    assert c["bienvenido"] == 1
    assert c["primer_contacto"] == ts("2026-01-10 13:00:00")
    assert c["ultimo_mensaje"] == ts("2026-01-10 13:05:00")
    # la fila con encabezados como datos no deja "nombre" como nombre
    assert st.contacto("59169987019")["nombre"] is None

    assert [e["detalle"] for e in st.eventos_desde("nuevo_usuario", 0)] == ["Hola, vi el anuncio"]
    assert len(st.eventos_desde("datos_prospecto", 0)) == 2
    assert len(st.eventos_desde("agente", 0)) == 3
    assert [m["contenido"] for m in st.mensajes_de("59160000001")] == ["Hola, vi el anuncio", "Juan", "bjj en la noche"]
    assert st.historial("59160000001", 10) == []   # lo importado no entra al contexto del agente
    assert st.solicitudes_pendientes() == []       # las históricas quedan atendidas
    assert st.solicitudes_de("59160000001")[0]["atendida_por"] == "histórico"


def test_no_se_repite(tmp_path):
    st = Store(tmp_path / "t.db")
    importar(st, INTERESADOS, SOLICITUDES, {EQUIPO})
    assert importar(st, INTERESADOS, SOLICITUDES, {EQUIPO}) == {}
    assert len(st.eventos_desde("agente", 0)) == 3


def test_no_pisa_redis_y_le_pone_hora_real(tmp_path):
    st = Store(tmp_path / "t.db")
    redis = RedisFalso({"ctx:59160000001": json.dumps({
        "last_seen": ts("2026-11-01 12:00:00"), "nombre": "Juan Pérez", "disciplina_raw": "Kudo",
        "history": [{"role": "assistant", "content": "Bienvenido"},
                    {"role": "user", "content": "bjj en la noche"},
                    {"role": "assistant", "content": "¡Genial!"}]})})
    migrar_desde_redis(st, redis)
    importar(st, INTERESADOS, SOLICITUDES, {EQUIPO})
    c = st.contacto("59160000001")
    assert (c["nombre"], c["disciplina"], c["turno"], c["dia"]) == ("Juan Pérez", "Kudo", "noche", "lunes")
    assert c["primer_contacto"] == ts("2026-01-10 13:00:00")
    msgs = st.mensajes_de("59160000001")
    hora = {m["contenido"]: m["ts"] for m in msgs}
    assert hora["bjj en la noche"] == ts("2026-01-10 13:02:00")
    assert hora["¡Genial!"] == ts("2026-01-10 13:02:01")
    # "Juan" no estaba en Redis y es anterior: se agrega desde la hoja; "bjj en la noche" no se duplica
    assert [m["contenido"] for m in msgs].count("bjj en la noche") == 1
    assert "Juan" in hora
    # el agente sigue viendo solo lo de Redis
    assert [h["content"] for h in st.historial("59160000001", 10)] == ["Bienvenido", "bjj en la noche", "¡Genial!"]


def test_falla_a_medias_no_deja_nada(tmp_path):
    st = Store(tmp_path / "t.db")
    filas = INTERESADOS + [["59160000003", None, "2026-01-01 00:00:00"]]   # provoca un error al procesar
    with pytest.raises(Exception):
        importar(st, filas, SOLICITUDES, {EQUIPO})
    assert st.contar_contactos() == 0 and st.meta("importacion_sheets") is None


class SheetsConDatos:
    activo = True

    def leer(self, hoja):
        return INTERESADOS if hoja == "Interesados" else SOLICITUDES

    def anotar(self, hoja, fila):
        pass

    async def esperar(self):
        pass


def test_arranque_importa_solo_con_la_variable(settings):
    settings.numeros_personal = [EQUIPO]
    svc, *_rest, store = armar(settings)
    svc.sheets = SheetsConDatos()
    asyncio.run(_importar_si_corresponde(svc))
    assert store.contar_contactos() == 0
    settings.importar_historico_sheets = True
    settings.migrar_desde_redis_url = "redis://pendiente"
    asyncio.run(_importar_si_corresponde(svc))
    assert store.contar_contactos() == 0          # espera a que termine la migración de Redis
    settings.migrar_desde_redis_url = ""
    asyncio.run(_importar_si_corresponde(svc))
    assert store.contar_contactos() == 2
