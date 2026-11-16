"""SQLite, métricas del panel, gráficos y migración desde Redis."""

from __future__ import annotations

import json
import time
from datetime import date
from zoneinfo import ZoneInfo

from app.migracion import migrar_desde_redis
from app.panel import graficos, metricas
from app.store import Store


def test_perfil_solo_pisa_campos_con_valor(tmp_path):
    st = Store(tmp_path / "t.db")
    st.registrar_entrante("591", "Perfil")
    st.actualizar_perfil("591", nombre="Ana", disciplina="BJJ")
    c = st.actualizar_perfil("591", nombre="", turno="noche")
    assert (c["nombre"], c["disciplina"], c["turno"], c["dia"]) == ("Ana", "BJJ", "noche", None)


def test_historial_filtra_y_traduce_respuestas_del_equipo(tmp_path):
    st = Store(tmp_path / "t.db")
    st.agregar_mensaje("591", "user", "hola", para_agente=False)
    st.agregar_mensaje("591", "assistant", "bienvenida")
    st.agregar_mensaje("591", "user", "1 · Horarios", tipo="menu", para_agente=False)
    st.agregar_mensaje("591", "staff", "te escribe Manuel")
    st.agregar_mensaje("591", "user", "gracias")
    assert st.historial("591", 10) == [
        {"role": "assistant", "content": "bienvenida"},
        {"role": "assistant", "content": "[Respuesta de una persona del equipo] te escribe Manuel"},
        {"role": "user", "content": "gracias"},
    ]
    assert len(st.historial("591", 2)) == 2
    assert len(st.mensajes_de("591")) == 5


def test_pausas_y_solicitudes(tmp_path):
    st = Store(tmp_path / "t.db")
    st.pausar("591", 1, "x")
    assert st.esta_pausado("591") and len(st.pausas_activas()) == 1
    assert st.reactivar("591") and not st.esta_pausado("591")
    sid = st.crear_solicitud("591", "ayuda")
    assert st.marcar_atendida(sid, "ana") and not st.marcar_atendida(sid, "ana")
    assert st.solicitudes_pendientes() == []


def test_normalizacion_del_embudo():
    assert metricas.disciplina("Jiu-Jitsu brasileño") == "BJJ"
    assert metricas.disciplina("kick boxing") == "Kick Boxing"
    assert metricas.disciplina("KUDO niños") == "Kudo"
    assert metricas.disciplina("yoga") == "Otra" and metricas.disciplina("") is None
    assert metricas.turno("en la noche") == "Noche" and metricas.turno("Mañana") == "Mañana"
    assert metricas.dia("el miércoles") == "Miércoles" and metricas.dia("sábado 10:30") == "Sábado"
    assert metricas.conteo(["BJJ", "Kudo", "BJJ", None], metricas.DISCIPLINAS) == [("Kudo", 1), ("BJJ", 2)]


def test_serie_diaria_en_hora_local():
    z = ZoneInfo("America/La_Paz")
    hoy = date(2026, 11, 15)
    # 02:00 UTC del 15 = 22:00 del 14 en La Paz
    ts = metricas.inicio_de(date(2026, 11, 14), z) + 22 * 3600
    serie = metricas.serie_diaria([ts], 3, z, hoy)
    assert serie == [(date(2026, 11, 13), 0), (date(2026, 11, 14), 1), (date(2026, 11, 15), 0)]


def test_graficos_svg():
    svg = graficos.columnas([(date(2026, 11, d), d % 3) for d in range(1, 31)], "mensajes", "Mensajes")
    assert svg.startswith("<svg") and "<title>" in svg and 'class="g-barra"' in svg
    assert "Sin datos" in graficos.columnas([(date(2026, 11, 1), 0)], "x", "x")
    barras = graficos.barras([("BJJ <script>", 3)], "prospectos", "Disciplina")
    assert "&lt;script&gt;" in barras and "<script>" not in barras


class RedisFalso:
    def __init__(self, datos):
        self.datos = datos

    def scan_iter(self, patron):
        return [k for k in self.datos if k.startswith(patron[:-1])]

    def get(self, k):
        return self.datos.get(k)


def test_migracion_desde_redis(tmp_path):
    st = Store(tmp_path / "t.db")
    ahora = time.time()
    redis = RedisFalso({
        "ctx:59171111111": json.dumps({
            "last_seen": ahora, "tema": "libre", "nombre": "Juan", "disciplina_raw": "BJJ", "turno_raw": "noche",
            "history": [{"role": "assistant", "content": "Bienvenido"}, {"role": "user", "content": "Juan"},
                        {"role": "assistant", "content": "¡Hola Juan!"}]}),
        "ctx:59172222222": "esto no es json",
        "bienvenido:59171111111": "1",
        "bienvenido:59173333333": "1",
    })
    r = migrar_desde_redis(st, redis)
    assert r == {"contactos": 1, "mensajes": 3, "saludados": 1}
    c = st.contacto("59171111111")
    assert c["nombre"] == "Juan" and c["disciplina"] == "BJJ" and c["bienvenido"] == 1 and c["tema"] == "libre"
    assert [h["content"] for h in st.historial("59171111111", 10)] == ["Bienvenido", "Juan", "¡Hola Juan!"]
    assert st.contacto("59173333333")["bienvenido"] == 1
    # no se repite
    assert migrar_desde_redis(st, redis) == {"contactos": 0, "mensajes": 0, "saludados": 0}
