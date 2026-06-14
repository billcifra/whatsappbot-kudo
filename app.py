# ---------------------------------------------
# Configuración e importación de dependencias
# ---------------------------------------------
from flask import Flask, request
import requests
import os
import time
from dotenv import load_dotenv
from openai import OpenAI
import gspread
from google.oauth2.service_account import Credentials
import json
# ✅ Agents SDK
from agents import Agent, Runner, function_tool

# Cargar variables de entorno desde archivo .env
load_dotenv()

# Inicialización de la app Flask
app = Flask(__name__)

# ✅ Config memoria (30 minutos)
TTL_SEGUNDOS = 1800
MAX_TURNOS = 20  # 20 turnos (user+assistant). Ajusta si quieres.
SILENCIO_RE_ENGANCHE = 7200  # 2 horas — umbral para mensaje contextual de retorno

# ---------------------------------------------
# ✅ Persistencia del contexto de conversación (Redis)
# ---------------------------------------------
# El contexto por usuario se guarda en Redis con TTL de 30 min, de modo que el historial
# y el embudo SOBREVIVEN a reinicios/deploys (antes vivían solo en RAM y se perdían).
# Si no hay REDIS_URL (p. ej. en local sin Redis) se usa un fallback en memoria — útil
# para desarrollo, pero ese fallback NO persiste entre reinicios.
REDIS_URL = os.getenv("REDIS_URL")
CTX_PREFIX = "ctx:"                  # clave del contexto de conversación (TTL 30 min)
BIENVENIDO_PREFIX = "bienvenido:"    # marca de "ya saludado" (TTL largo)
BIENVENIDO_TTL = 60 * 60 * 24 * 60   # 60 días


class _MemoriaLocal:
    """Fallback en RAM con la interfaz mínima de redis-py (solo desarrollo local)."""
    def __init__(self):
        self._store = {}  # key -> (expira_epoch | None, valor)

    def get(self, key):
        item = self._store.get(key)
        if not item:
            return None
        expira, valor = item
        if expira is not None and time.time() > expira:
            self._store.pop(key, None)
            return None
        return valor

    def setex(self, key, ttl, valor):
        self._store[key] = (time.time() + ttl, valor)

    def delete(self, key):
        self._store.pop(key, None)

    def keys(self, pattern):
        prefijo = pattern[:-1] if pattern.endswith("*") else pattern
        return [k for k in list(self._store) if k.startswith(prefijo) and self.get(k) is not None]


def _conectar_backend():
    """Conecta a Redis si hay REDIS_URL; si falla o no está, cae a memoria local."""
    if REDIS_URL:
        try:
            import redis
            kwargs = {"decode_responses": True}
            if REDIS_URL.startswith("rediss://"):
                kwargs["ssl_cert_reqs"] = None  # Heroku Redis: TLS con cert autofirmado
            cliente = redis.from_url(REDIS_URL, **kwargs)
            cliente.ping()
            print("[INFO] Persistencia: Redis conectado.")
            return cliente
        except Exception as e:
            print("[ERROR] No se pudo conectar a Redis; usando memoria local:", e)
            return _MemoriaLocal()
    print("[WARN] REDIS_URL no definido — usando memoria local (NO persiste reinicios).")
    return _MemoriaLocal()


_backend = _conectar_backend()


def cargar_contexto(phone):
    """Devuelve el contexto del usuario desde el backend (o None si no existe/expiró)."""
    raw = _backend.get(CTX_PREFIX + phone)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def guardar_contexto(phone, ctx):
    """Persiste el contexto con TTL de 30 min (renueva la expiración en cada escritura)."""
    _backend.setex(CTX_PREFIX + phone, TTL_SEGUNDOS, json.dumps(ctx, ensure_ascii=False))


def marcar_bienvenido(phone):
    """Marca (con TTL largo) que el usuario ya recibió la bienvenida, para no repetirla."""
    _backend.setex(BIENVENIDO_PREFIX + phone, BIENVENIDO_TTL, "1")


def ya_bienvenido(phone):
    return bool(_backend.get(BIENVENIDO_PREFIX + phone))

# ---------------------------------------------
# 📅 Feriados / días SIN clases de prueba
# ---------------------------------------------
# Días en los que el dojo NO dicta clases (feriados, cierres, etc.).
# El agente NO debe coordinar ni confirmar clases de prueba en estas fechas.
# Formato: "YYYY-MM-DD": "motivo". Edita esta lista para agregar o quitar feriados.
FERIADOS = {
    "2026-06-04": "Feriado (jueves) — sin clases",
    "2026-06-05": "Feriado (viernes) — sin clases",
}

# Cargar credenciales desde variables de entorno
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.getenv("PHONE_NUMBER_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_SHEET_KEY = os.getenv("GOOGLE_SHEET_KEY")
credentials_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS_JSON"))

# Cliente de Google Sheets
scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_info(credentials_dict, scopes=scope)
gs_client = gspread.authorize(creds)
solicitudes_sheet = gs_client.open_by_key(GOOGLE_SHEET_KEY).worksheet("SolicitudesHumano")
interesados_sheet = gs_client.open_by_key(GOOGLE_SHEET_KEY).worksheet("Interesados")

# ---------------------------------------------
# Respuestas directas del menú numérico (1–7)
# ---------------------------------------------

# CTA estándar hacia la clase de prueba gratuita. Se envía como mensaje de cierre
# en las respuestas del menú para impulsar la conversión en CADA interacción.
CTA_PRUEBA = ("🎁 Tu *primera clase es GRATIS*, sin compromiso.\n"
              "¿Te coordino tu clase de prueba? 🥋 Dime qué día te viene bien.")

# Cada opción es una LISTA de mensajes cortos (chunks). El webhook los envía como
# mensajes separados para que sean fáciles de escanear en el celular, y cierra con
# el CTA a la clase de prueba. Los horarios se conservan EXACTOS (no inventar/alterar).
respuestas_directas = {
    "1": [
        "👉 *Horarios — Kudo* 🥋\n\n"
        "📍 *Niños (6 a 13 años)*\n"
        "• Mar y Jue: 8:30–10:00 y 16:30–18:00\n"
        "• Sáb: 10:30–12:00\n\n"
        "📍 *Jóvenes y Adultos*\n"
        "• Lun y Mié: 8:30–10:00\n"
        "• Mar y Jue: 19:30–21:00\n"
        "• Sáb: 9:00–10:30",

        "👉 *Horarios — BJJ y Kick Boxing* 🥋\n\n"
        "📍 *Brazilian Jiu-Jitsu (Jóvenes y Adultos)*\n"
        "• Lun, Mié y Vie: 17:00–18:30 y 19:30–21:00\n\n"
        "📍 *BJJ Kids*\n"
        "• Lun, Mié y Vie: 18:30–19:30\n\n"
        "📍 *Kick Boxing*\n"
        "• Mar y Jue: 7:00–8:30 y 18:00–19:30\n\n"
        "⛔ BJJ y Kick Boxing no abren sábados ni domingos.",

        CTA_PRUEBA,
    ],
    "2": [
        "👉 *Precios* 💰\n\n"
        "Bs. *250/mes* por persona (3 clases por semana).\n\n"
        "¿Prefieres venir 1 día, 2 días o solo sábados? Podemos coordinar una opción a tu medida. 😊",
        CTA_PRUEBA,
    ],
    "3": [
        "👉 *Disciplinas que ofrecemos* 🥋\n\n"
        "🥋 *Kudo* — qué es: https://www.youtube.com/watch?v=NqcE1J7z2eE\n"
        "🥋 *Brazilian Jiu-Jitsu* — qué es: https://www.youtube.com/watch?v=tztK3dJksk0\n"
        "🥋 *Kick Boxing* — qué es: https://www.youtube.com/watch?v=Sh9cVUidnr0",
        CTA_PRUEBA,
    ],
    "4": [
        "👉 *¿Cómo inscribirte?* 📝\n\n"
        "¡Súper fácil! Ven al dojo y te inscribimos en el momento.\n"
        "📍 Calle Cañada Strongest N.º 1847, a pasos de la plaza del estudiante, La Paz.",

        "🎁 Pero primero puedes venir a una *clase de prueba GRATIS*, sin compromiso. "
        "Es la mejor forma de conocernos.\n\n"
        "👉 ¿Qué día podrías venir? Dime el día y te confirmo el horario exacto. 🗓️",
    ],
    "5": [
        "📍 *Ubicación*\n"
        "Calle Cañada Strongest N.º 1847, a pasos de la plaza del estudiante, La Paz, Bolivia.\n\n"
        "🗺️ Mapa: https://maps.app.goo.gl/CeW1sAW77AgTzriA6?g_st=ipc",
        CTA_PRUEBA,
    ],
    "6": [
        "*¿Qué es Kudo?* 🥋\n\n"
        "Es un arte marcial japonés moderno y completo: combina golpes a contacto pleno, "
        "lanzamientos, controles y sumisiones en el suelo. Un *Budo* con valores de respeto y "
        "superación personal, creado por el maestro *Azuma Takashi* y practicado en más de 50 países.",

        "Su filosofía se basa en 3 conceptos:\n"
        "• *Transitoriedad* — nada es permanente\n"
        "• *Interdependencia* — todo está conectado\n"
        "• *Mente abierta* — humildad y aprendizaje\n\n"
        "📹 Videos:\n"
        "🎥 ¿Qué es Kudo?: https://www.youtube.com/watch?v=NqcE1J7z2eE\n"
        "🎥 Highlights: https://www.youtube.com/watch?v=JtTWeISoAFA\n"
        "🎥 Mundial 2023: https://www.youtube.com/watch?v=jfcne0M5qEU",

        CTA_PRUEBA,
    ],
    "7": [
        "🥊 *Guantillas para MMA*\n\n"
        "¡Nuevas y de alta calidad! Ideales para MMA, cualquier arte marcial y entrenamiento "
        "en sacos, pads y manoplas. Diseño ergonómico para todas las edades.\n\n"
        "💰 1 par: Bs. 90 · 2 o más: Bs. 80 c/u\n"
        "⏰ Ventas: Lun a Vie, 14:00–15:30\n"
        "📍 Entrega: Cañada Strongest 1847 (Ed. Sarawi), Dojo \"KUDO BOLIVIA\".",
        CTA_PRUEBA,
    ],
}

# Opciones del menú principal, presentadas como LISTA INTERACTIVA de WhatsApp.
# El `id` de cada fila coincide con la clave de `respuestas_directas`, de modo que
# tocar una opción produce exactamente el mismo efecto que escribir el número (1-7).
MENU_ROWS = [
    {"id": "1", "title": "Horarios", "description": "Días y horas por disciplina"},
    {"id": "2", "title": "Precios", "description": "Mensualidad y opciones"},
    {"id": "3", "title": "Disciplinas", "description": "Kudo, BJJ y Kick Boxing"},
    {"id": "4", "title": "Inscripción", "description": "Cómo empezar + clase gratis"},
    {"id": "5", "title": "Ubicación", "description": "Dónde estamos"},
    {"id": "6", "title": "¿Qué es Kudo?", "description": "Conoce el arte marcial"},
    {"id": "7", "title": "Venta de Guantes", "description": "Guantillas de MMA en venta"},
]
MENU_BODY = "📋 ¿Sobre qué te gustaría saber? Toca una opción 👇"

# Mensajes de conversión para leads de publicidad
BIENVENIDA = (
    "¡Hola! 👋 Bienvenido/a a *KUDO Bolivia*, tu centro de artes marciales en La Paz.\n\n"
    "🥋 Entrenamos *Kudo*, *Brazilian Jiu-Jitsu*, *Kick Boxing* y *Defensa Personal*.\n"
    "🎁 *¡Tu primera clase es completamente GRATIS!* Sin compromiso.\n\n"
    "Para ayudarte mejor, ¿cómo te llamas? 😊"
)

# Lista de números a notificar en caso de solicitud de atención humana
notificar_humanos = ["59179598641", "59176785574"]

# Prompt del sistema del agente (definido a nivel de módulo para instanciar el agente una sola vez)
SYSTEM_PROMPT = (
    "Eres un asistente virtual del centro de artes marciales *KUDO Bolivia*, ubicado "
    "en la calle Cañada Strongest N.º 1847, a media cuadra de la plaza del estudiante, en La Paz, Bolivia. "
    "Tu objetivo es brindar información clara, respetuosa y profesional a todas las personas que "
    "consultan por WhatsApp.\n"
    "\n"
    "🏆 En *KUDO Bolivia* se imparten las siguientes disciplinas: *Kudo*, *Jiu-Jitsu Brasileño "
    "(BJJ)*, *Kick Boxing* y *Defensa Personal (clases privadas)*.\n"
    "\n"
    "🥋 *¿Qué es Kudo?*\n"
    "Kudo es un arte marcial japonés moderno y completo que combina golpes a contacto pleno, "
    "lanzamientos, controles y técnicas de sumisión en el suelo. Se considera un *Budo* "
    "contemporáneo con valores educativos, espirituales y de respeto, promoviendo la formación "
    "del carácter, la superación personal y la cortesía (*Reigi*).\n"
    "\n"
    "Fue creado por el maestro *Azuma Takashi* y se practica en más de 50 países. Cada cuatro "
    "años se celebra un Campeonato Mundial, que reúne a los mejores representantes del mundo.\n"
    "\n"
    "Su filosofía se basa en tres conceptos fundamentales:\n"
    "• *Transitoriedad* (nada es permanente),\n"
    "• *Interdependencia* (todo está conectado),\n"
    "• *Mente abierta* (humildad, imparcialidad y aprendizaje continuo).\n"
    "\n"
    "📌 *Sobre KUDO Bolivia:*\n"
    "KUDO Bolivia fue oficialmente constituida en abril de 2021. Su director (*Branch Chief*) es "
    "el Sensei *José Manuel Rioja Claure*, 2º DAN en Kudo. Desde su creación, el equipo boliviano "
    "ha participado en eventos internacionales, incluyendo el Panamericano en Brasil y el "
    "Campeonato Mundial en Japón en 2023.\n"
    "\n"
    "📹 Videos recomendados:\n"
    "• ¿Qué es Kudo?: https://www.youtube.com/watch?v=NqcE1J7z2eE&\n"
    "• Highlights: https://www.youtube.com/watch?v=JtTWeISoAFA&\n"
    "• Mundial 2023: https://www.youtube.com/watch?v=jfcne0M5qEU\n"
    "\n"
    "🌐 Sitio oficial de la Federación Internacional de Kudo (KIF): https://ku-do.org/\n"
    "📘 Facebook oficial KUDO Bolivia: https://www.facebook.com/profile.php?id=100032041972221\n"
    "🗓️ Calendario de eventos KIF: https://ku-do.org/news/\n"
    "\n"
    "🥋 *¿Qué es el Jiu-Jitsu Brasileño (BJJ)?*\n"
    "El BJJ es un arte marcial especializado en el combate cuerpo a cuerpo en el suelo, "
    "utilizando técnicas como llaves articulares, estrangulamientos y controles. Se basa en la "
    "técnica y la estrategia más que en la fuerza, permitiendo neutralizar o someter al oponente "
    "con eficiencia.\n"
    "\n"
    "🎥 Video explicativo: https://www.youtube.com/watch?v=tztK3dJksk0\n"
    "\n"
    "🧍‍♂️ *Edades y niveles:*\n"
    "Ofrecemos clases para todas las edades, desde niños hasta adultos. Se aceptan niños desde los "
    "6 años o próximos a cumplirlos. No se necesita experiencia previa.\n\n"
    "🕒 *Horarios generales de referencia:*\n"
    "📍 *Kudo Niños (6 a 13 años)*\n"
    "   🕗 *Turno mañana:*\n"
    "     • Martes y Jueves: 8:30–10:00\n"
    "     • Sábados: 10:30–12:00\n"
    "   🌆 *Turno tarde:*\n"
    "     • Martes y Jueves: 16:30–18:00\n"
    "     • Sábados: 10:30–12:00\n"
    "\n"
    "📍 *Kudo Jóvenes y Adultos*\n"
    "   🕗 *Turno mañana:*\n"
    "     • Lunes y Miercoles: 8:30–10:00\n"
    "     • Sábados: 9:00–10:30\n"
    "   🌙 *Turno noche:*\n"
    "     • Martes y Jueves: 19:30–21:00\n"
    "     • Sábados: 9:00–10:30\n"
    "\n"
    "📍 *Brazilian Jiu-Jitsu Jóvenes y Adultos*\n"
    "   🌆 *Turno tarde:*\n"
    "     • Lunes, Miércoles y Viernes: 17:00–18:30\n"
    "   🌙 *Turno noche:*\n"
    "     • Lunes, Miércoles y Viernes: 19:30–21:00\n"
    "     ⛔ Brazilian Jiu-Jitsu NO tiene clases los sábados ni domingos.\n"
    "\n"
    "📍 *Brazilian Jiu-Jitsu Kids*\n"
    "     • Lunes, Miércoles y Viernes: 18:30–19:30\n"
    "     ⛔ Brazilian Jiu-Jitsu Kids NO tiene clases los sábados ni domingos.\n"
    "\n"
    "📍 *Kick Boxing*\n"
    "   🕗 *Turno mañana:*\n"
    "     • Martes y Jueves: 7:00–8:30\n"
    "   🌙 *Turno noche:*\n"
    "     • Martes y Jueves: 18:00–19:30\n"
    "     ⛔ Kick Boxing NO tiene clases los sábados ni domingos.\n"
    "\n"
    "🔔 *Resumen de SÁBADOS:* las ÚNICAS disciplinas con clases los sábados son "
    "Kudo Niños (10:30–12:00) y Kudo Jóvenes y Adultos (9:00–10:30). "
    "Brazilian Jiu-Jitsu (Adultos y Kids) y Kick Boxing NO abren los sábados.\n"
    "\n"
    "💰 *Precios:* Bs. 250 mensual por persona (3 clases por semana). "
    "Si alguien prefiere asistir solo un día, dos días o únicamente los sábados, "
    "es posible coordinar una configuración diferente con descuento; "
    "debe acercarse al dojo para consultarlo directamente.\n\n"
    "🆓 *Clase de prueba GRATUITA:*\n"
    "¡Todas nuestras disciplinas ofrecen una clase de prueba completamente GRATIS, sin compromiso!\n\n"
    "🧥 *Indumentaria:*\n"
    "Para las primeras clases se recomienda ropa deportiva cómoda. Para entrenamientos regulares "
    "se utilizan implementos básicos como *gi* (kimono), guantes, protector facial y otros, según "
    "la disciplina.\n\n"
    "📝 *Inscripción:* Puedes inscribirte acercándote al dojo. ¡Estamos disponibles para "
    "recibirte!\n\n"
    "📍📍 *Ubicación:* Calle Cañada Strongest N.º 1847 - a pasos de la plaza del estudiante, La Paz, "
    "Bolivia.\n\n"
    "🥊 *VENTA DE EQUIPAMIENTO (Guantillas de MMA):*\n"
    "Tenemos a la venta guantillas para MMA nuevas, de alta calidad y diseño ergonómico, perfectas para todas las edades. "
    "Son ideales para MMA, cualquier Arte Marcial, entrenamiento en sacos, pads/manoplas, gobernadoras y wall pads.\n"
    "💰 *Precios:*\n"
    "- 1 par: Bs. 90\n"
    "- 2 pares o más: Bs. 80 cada par.\n"
    "⏰ *Horario de atención para ventas:* Lunes a viernes de 14:00 a 15:30.\n"
    "📍 *Lugar de entrega:* Calle Cañada Strongest 1847 (Ed. Sarawi) – Dojo \"KUDO BOLIVIA\", a media cuadra de la plaza del estudiante.\n"
    "\n"
    "📌 Puedes ver el mapa en Google Maps:  \n"
    "https://maps.app.goo.gl/CeW1sAW77AgTzriA6?g_st=ipc\n\n"
    "👨‍🏫 *Profesores de Jiu-Jitsu en KUDO Bolivia:* "
    "• *Prof. Nelson Escobar* – cinturón negro 2.º grado de Brazilian Jiu-Jitsu (BJJ), "
    "representante de PS Phoenix International BJJ y Altitud MMA, con más de 22 años de trayectoria "
    "dedicados al entrenamiento. Con formación que incluye experiencias nacionales e internacionales "
    "en Bolivia, Brasil, Argentina, Cuba, España, Portugal y Francia, registrado en la International "
    "Brazilian Jiu Jitsu Federation (IBJJF). "
    "Más de 20 años de campeonatos nacionales e internacionales, con medallas y competencias en "
    "Bolivia, Brasil y Portugal con más de 15 años de experiencia en la enseñanza del BJJ. "
    "🔹 Dicta clases en los siguientes horarios: "
    "- Lunes, Miércoles y Viernes: 19:30–21:00 "
    "- Lunes, Miércoles y Viernes: 18:30–19:30 (BJJ Kids) "
    "• *Prof. Joaquín Carvajal* – 11 años de experiencia en Brazilian Jiu Jitsu Cinturón marrón, "
    "1er grado Campeón y vice campeón nacional en BJJ (gi y nogi). Artes marciales complementarias: "
    "Lucha Olímpica, Judo y MMA. "
    "🔹 Dicta clases en los siguientes horarios: "
    "- Lunes, Miércoles y Viernes: 17:00–18:30 "
    "\n"
    "📌 Si el usuario pregunta por el profesor de alguna clase de Jiu-Jitsu, responde con el nombre "
    "del instructor y una breve descripción basada en la lista proporcionada. Si no hay información "
    "suficiente, invita cordialmente a conocer al equipo en el dojo. "
    "📝 Si alguien pregunta por temas como horarios, precios, inscripción o ubicación, ofrece la "
    "respuesta y, cuando quieras mostrar el menú de opciones, NO escribas la lista numerada. "
    "En su lugar, termina tu mensaje con el token especial [[MENU]] en una línea aparte: el sistema "
    "mostrará automáticamente un menú con botones que el usuario puede tocar (Horarios, Precios, "
    "Disciplinas, Inscripción, Ubicación, ¿Qué es Kudo?, Venta de Guantes). Usa [[MENU]] cuando "
    "ofrezcas opciones, pero NO lo uses si estás en medio del embudo haciendo una pregunta concreta "
    "(por ejemplo pidiendo el nombre, la disciplina, el turno o el día).\n"
    "\n"
    "📌 Siempre responde en español neutro, con cortesía y como si formaras parte del equipo de "
    "*KUDO Bolivia*. Si no conoces la respuesta exacta, invita amablemente a visitar el dojo para "
    "obtener más información. Si el usuario escribe una lista de números como '1, 3, 4', responde "
    "a cada opción en orden. Cada número corresponde al menú que se muestra. No inventes ni combines "
    "si no está especificado.\n"
    "\n"
    "👤 *Manejo de nombres propios:*\n"
    "Si el usuario envía únicamente un nombre propio (por ejemplo 'Augusto', 'María José', 'Juan'), "
    "sin ninguna pregunta ni petición, interprétalo como que se está presentando o respondiendo a un "
    "saludo previo. NUNCA preguntes '¿a qué te refieres con [nombre]?' ni pidas que aclare. En su "
    "lugar, salúdalo cordialmente por su nombre, dale la bienvenida a KUDO Bolivia, invítalo a su "
    "clase de prueba gratuita y ofrécele el menú de opciones para orientarlo. "
    "Ejemplo: '¡Mucho gusto, Augusto! 👋 Bienvenido a KUDO Bolivia. ¿Sobre qué tema te gustaría "
    "información? Recuerda que tu primera clase es GRATIS.' y termina el mensaje con [[MENU]].\n"
    "🔁 Cuando el usuario solicite la opción 3 (*Disciplinas*), sola o combinada con otras, debes "
    "incluir también los enlaces de video explicativo de *Kudo* y *BJJ* en tu respuesta.\n"
    "\n"
    "🎯 *REGLA OBLIGATORIA – Clase de prueba gratuita:*\n"
    "En CADA respuesta que des, busca el momento más natural para mencionar e invitar activamente "
    "a la clase de prueba gratuita. No importa el tema (horarios, precios, disciplinas, ubicación, "
    "curiosidad general): siempre cierra con una invitación como '¡Te esperamos para tu primera "
    "clase GRATIS, sin compromiso!' o '¡Ven a probar una clase gratis y conoce el dojo!'. "
    "Esta invitación es prioritaria porque el bot se usa en campañas de publicidad y el objetivo "
    "es convertir el interés en una visita al dojo.\n"
    "\n"
    "✍️ *ESTILO – Mensajes breves para WhatsApp:*\n"
    "Responde de forma BREVE y fácil de escanear en el celular: idealmente 2 a 4 líneas, máximo "
    "~60 palabras. Ve directo al grano, usa viñetas si listas varias cosas y evita párrafos largos. "
    "Si el usuario pide algo extenso (ej: todos los horarios), da primero lo esencial de su "
    "disciplina o turno de interés y ofrece el resto si lo necesita. Cierra SIEMPRE con la "
    "invitación breve a la clase de prueba gratuita.\n"
    "\n"
    "👤 *PERSONALIZACIÓN:*\n"
    "Cuando en PERFIL_DEL_PROSPECTO tengas el nombre del usuario, úsalo con naturalidad de vez en "
    "cuando (no en cada frase ni en todos los mensajes, para no sonar repetitivo ni robótico). "
    "Aprovecha también la disciplina, el turno y el día de interés que ya conozcas para personalizar "
    "tanto la respuesta como el CTA. Por ejemplo: 'Perfecto, Juan 🙌 Para *BJJ* en el turno noche "
    "te esperamos el lunes a las 19:30. ¿Te coordino tu clase de prueba GRATIS?'. Nunca vuelvas a "
    "pedir un dato que ya figura en el perfil; en su lugar, confírmalo o construye sobre él.\n"
    "\n"
    "🎯 *EMBUDO DE CALIFICACIÓN (recolección de datos del prospecto):*\n"
    "Además de responder lo que el usuario pregunte, tu segundo objetivo es ir recolectando, de "
    "forma natural y conversacional, estos 4 datos del prospecto, en este orden ideal:\n"
    "  1. *Nombre* (al usuario nuevo ya se le pidió el nombre en el mensaje de bienvenida; si en "
    "el historial el usuario acaba de responder con su nombre, salúdalo por su nombre y continúa).\n"
    "  2. *Disciplina* de interés (Kudo, BJJ, Kick Boxing o Defensa Personal).\n"
    "  3. *Turno* preferido (mañana, tarde o noche).\n"
    "  4. *Día* en que podría asistir a su clase de prueba gratuita.\n"
    "Haz UNA pregunta a la vez para no abrumar. NO interrogues de golpe ni repitas datos que el "
    "usuario ya te dio (revísalos en PERFIL_DEL_PROSPECTO y en el historial).\n"
    "MUY IMPORTANTE – flexibilidad: si en cualquier momento el usuario hace una pregunta o un "
    "comentario fuera de este guion (precio, ubicación, dudas, etc.), PRIMERO respóndele esa "
    "consulta con normalidad y LUEGO retoma con naturalidad la siguiente pregunta del embudo que "
    "falte. Nunca ignores lo que el usuario dice con tal de seguir el guion.\n"
    "Cada vez que el usuario te entregue uno de estos datos (nombre, disciplina, turno o día), "
    "DEBES llamar a la herramienta `guardar_datos_prospecto` con los datos que tengas hasta el "
    "momento, para registrarlos. Puedes llamarla varias veces a medida que obtienes más datos. "
    "Cuando ya tengas el día de la visita, confirma el horario que corresponde a su disciplina y "
    "ese día (respetando la REGLA ESTRICTA de horarios) e impulsa el cierre de la clase de prueba.\n"
    "\n"
    "⚠️ *REGLA ESTRICTA – Horarios:*\n"
    "NUNCA inventes, supongas ni modifiques horarios que no estén exactamente escritos en este "
    "prompt. Los únicos horarios válidos son los que aparecen en la sección 'Horarios generales "
    "de referencia' de este mismo prompt. Si alguien pregunta por un día, hora o modalidad que "
    "no figura aquí, responde honestamente: 'No tengo ese dato exacto, te recomiendo consultar "
    "directamente en el dojo o escribirnos para confirmarlo.' Está prohibido completar, extrapolar "
    "o inventar cualquier horario.\n"
    "Cada horario pertenece SOLO a la disciplina y al día bajo los que aparece escrito. JAMÁS "
    "apliques el horario de una disciplina a otra, ni el de un día a otro día. Por ejemplo, si "
    "BJJ solo figura en lunes, miércoles y viernes, entonces BJJ NO tiene clases los sábados, "
    "aunque otras disciplinas sí las tengan ese día. Si una disciplina no aparece listada para "
    "un día concreto, debes decir explícitamente que esa disciplina no tiene clases ese día. "
    "Antes de mencionar cualquier horario de sábado (u otro día), verifica que esa disciplina "
    "EXACTA aparezca listada para ese día exacto en la sección de horarios; si no aparece, NO "
    "la incluyas.\n"
    "\n"
    "📅 *Coordinación de visita:*\n"
    "Cuando el usuario indique un día o momento para venir al dojo (ej: 'puedo el martes', "
    "'voy el sábado'), responde confirmando el horario de clase que corresponde a ese día y "
    "disciplina de interés, y cierra con: '¡Te esperamos! ¿Quieres que avisemos al instructor?' "
    "Si el usuario confirma, usa la herramienta solicitar_asistencia_humana para notificar al equipo.\n"
    "\n"
    "🚫 *REGLA ESTRICTA – Feriados / días sin clases:*\n"
    "Al inicio de cada mensaje recibirás la fecha de hoy (FECHA_HOY) y, si corresponde, una lista "
    "de FERIADOS próximos en los que el dojo NO dicta clases. NUNCA coordines, confirmes ni "
    "agendes una clase de prueba para un día que figure como feriado. Si el usuario propone venir "
    "en una de esas fechas (o se refiere a ella, ej: 'este jueves', 'el viernes'), discúlpate "
    "amablemente, explícale que ese día es feriado y no hay clases, y ofrécele coordinar otro día "
    "disponible. No uses solicitar_asistencia_humana para agendar visitas en días feriados."
)


# ---------------------------------------------
# Funciones auxiliares
# ---------------------------------------------

def send_message(text, phone):
    """Envía un mensaje de texto por la API de WhatsApp"""
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}",
               "Content-Type": "application/json"
               }
    payload = {"messaging_product": "whatsapp",
               "to": phone,
               "type": "text",
               "text": {"body": text}
               }
    print(f"[INFO] Respuesta del bot a {phone}: {text}")
    response = requests.post(url, headers=headers, json=payload)
    print("[INFO] WhatsApp API response:", response.status_code, response.text)


def send_typing_indicator(message_id):
    """Marca el mensaje como leído y muestra el indicador de 'escribiendo…' en WhatsApp.

    El indicador se muestra hasta ~25 s o hasta que enviamos una respuesta. Mejora la
    sensación de conversación humana, sobre todo cuando el agente tarda unos segundos.
    Requiere el `id` (wamid) del mensaje entrante. Cualquier fallo aquí se ignora para
    no bloquear nunca la respuesta real al usuario.
    """
    if not message_id:
        return
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}",
               "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "status": "read",
        "message_id": message_id,
        "typing_indicator": {"type": "text"},
    }
    try:
        requests.post(url, headers=headers, json=payload)
    except Exception as e:
        print("[WARN] No se pudo enviar el indicador de escritura:", e)


def send_list_menu(phone, body_text=MENU_BODY):
    """Envía el menú principal como lista interactiva (opciones que el usuario toca).

    Reemplaza al antiguo menú de texto ('escribe 1-7'): WhatsApp muestra un botón
    'Ver opciones' que despliega las 7 opciones; al tocar una, Meta nos reenvía el
    `id` de la fila, que el webhook trata igual que si el usuario hubiera escrito el número.
    """
    url = f"https://graph.facebook.com/v18.0/{PHONE_NUMBER_ID}/messages"
    headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}",
               "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "header": {"type": "text", "text": "KUDO Bolivia 🥋"},
            "body": {"text": body_text},
            "footer": {"text": "Tu primera clase es GRATIS 🎁"},
            "action": {
                "button": "Ver opciones",
                "sections": [{"title": "Información", "rows": MENU_ROWS}],
            },
        },
    }
    print(f"[INFO] Menú interactivo enviado a {phone}")
    response = requests.post(url, headers=headers, json=payload)
    print("[INFO] WhatsApp API response:", response.status_code, response.text)


def registrar_interesado(phone, message, nombre="", disciplina="", turno="", dia=""):
    fecha = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    interesados_sheet.append_row([phone, message, fecha, nombre, disciplina, turno, dia])


def registrar_solicitud_humana(phone, message):
    fecha = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    solicitudes_sheet.append_row([phone, message, fecha])


def agregar_saludo(texto, phone):
    """Antepone el nombre del usuario si está disponible en el contexto."""
    nombre = (cargar_contexto(phone) or {}).get("nombre")
    return f"¡Hola, {nombre}! 😊\n\n{texto}" if nombre else texto


# ---------------------------------------------
# ✅ Tool (Agents SDK) para notificar a humanos
# ---------------------------------------------
@function_tool
def solicitar_asistencia_humana(user_phone: str, user_message: str) -> str:
    """
    Notifica al equipo humano por WhatsApp y registra la solicitud en Google Sheets.
    El agente debe llamar esta herramienta cuando el usuario pida 'hablar con alguien',
    'atención humana', 'hablar con una persona', etc.
    """
    registrar_solicitud_humana(user_phone, user_message)
    for admin_phone in notificar_humanos:
        send_message(
            f"📩 Solicitud de atención humana del número: {user_phone}\nMensaje: {user_message}",
            admin_phone
        )
    return "Notificación enviada al equipo humano y solicitud registrada."


# ---------------------------------------------
# ✅ Tool (Agents SDK) para guardar datos del prospecto (embudo de calificación)
# ---------------------------------------------
@function_tool
def guardar_datos_prospecto(user_phone: str, nombre: str = "", disciplina: str = "",
                            turno: str = "", dia: str = "") -> str:
    """
    Guarda en Google Sheets los datos del prospecto recolectados durante la conversación.
    Llama a esta herramienta CADA VEZ que el usuario te entregue uno de estos datos:
    su nombre, la disciplina de interés, el turno preferido o el día que podría asistir.
    Puedes llamarla varias veces a medida que obtienes más datos; envía siempre todos los
    que tengas hasta el momento (los que aún no conozcas déjalos vacíos).
    """
    ctx = cargar_contexto(user_phone) or {}
    if nombre:
        ctx["nombre"] = nombre
    if disciplina:
        ctx["disciplina_raw"] = disciplina
    if turno:
        ctx["turno_raw"] = turno
    if dia:
        ctx["dia_raw"] = dia
    ctx.setdefault("history", [])
    ctx["last_seen"] = time.time()
    guardar_contexto(user_phone, ctx)
    registrar_interesado(
        user_phone,
        "[DATOS PROSPECTO]",
        nombre=ctx.get("nombre", ""),
        disciplina=ctx.get("disciplina_raw", ""),
        turno=ctx.get("turno_raw", ""),
        dia=ctx.get("dia_raw", ""),
    )
    return "Datos del prospecto guardados."


# Agente instanciado una sola vez al arrancar (no en cada request)
kudo_agent = Agent(
    name="KUDO Bolivia Assistant",
    model="gpt-4.1",
    instructions=SYSTEM_PROMPT,
    tools=[solicitar_asistencia_humana, guardar_datos_prospecto],
)


# ---------------------------------------------
# ✅ Memoria de conversación (30 min) en Redis
# ---------------------------------------------
def get_or_init_user_context(user_phone: str, ahora: float):
    """Carga el contexto desde Redis (el TTL ya gestiona la expiración: None si caducó);
    si no existe, devuelve uno nuevo. NO persiste: el llamador guarda tras modificarlo."""
    ctx = cargar_contexto(user_phone)
    if not ctx:
        ctx = {"last_seen": ahora, "history": [], "etapa_calificacion": 99}
    # Contextos creados por los routers directos pueden no tener "history"
    ctx.setdefault("history", [])
    ctx["last_seen"] = ahora
    return ctx


def append_to_history(ctx: dict, role: str, content: str):
    ctx["history"].append({"role": role, "content": content})
    if len(ctx["history"]) > (MAX_TURNOS * 2):
        ctx["history"] = ctx["history"][-(MAX_TURNOS * 2):]


def construir_contexto_fechas():
    """Devuelve un bloque de texto con la fecha de hoy y los feriados futuros (o de hoy)."""
    hoy = time.strftime("%Y-%m-%d", time.localtime())
    dias_semana = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    dia_nombre = dias_semana[time.localtime().tm_wday]
    bloque = f"FECHA_HOY: {hoy} ({dia_nombre})\n"
    feriados_relevantes = {f: motivo for f, motivo in FERIADOS.items() if f >= hoy}
    if feriados_relevantes:
        lineas = [f"  • {f}: {motivo}" for f, motivo in sorted(feriados_relevantes.items())]
        bloque += "FERIADOS (NO hay clases, no coordines clases de prueba estos días):\n" + "\n".join(lineas) + "\n"
    return bloque + "\n"


def build_agent_input(user_phone: str, user_msg: str, history: list, perfil: dict = None):
    contexto_fechas = construir_contexto_fechas()
    transcript = []
    for item in history:
        if item["role"] == "user":
            transcript.append(f"Usuario: {item['content']}")
        else:
            transcript.append(f"Asistente: {item['content']}")
    historial_texto = "\n".join(transcript).strip()

    perfil_texto = ""
    if perfil:
        partes = []
        if perfil.get("nombre"):
            partes.append(f"Nombre: {perfil['nombre']}")
        if perfil.get("disciplina_raw"):
            partes.append(f"Disciplina de interés: {perfil['disciplina_raw']}")
        if perfil.get("turno_raw"):
            partes.append(f"Turno preferido: {perfil['turno_raw']}")
        if perfil.get("dia_raw"):
            partes.append(f"Día disponible: {perfil['dia_raw']}")
        if partes:
            perfil_texto = "PERFIL_DEL_PROSPECTO:\n" + "\n".join(partes) + "\n\n"

    if historial_texto:
        return (
            f"TELÉFONO_USUARIO: {user_phone}\n"
            f"{contexto_fechas}"
            f"{perfil_texto}"
            f"HISTORIAL_30_MIN:\n{historial_texto}\n\n"
            f"MENSAJE_ACTUAL_USUARIO: {user_msg}"
        )
    return (
        f"TELÉFONO_USUARIO: {user_phone}\n"
        f"{contexto_fechas}"
        f"{perfil_texto}"
        f"MENSAJE_ACTUAL_USUARIO: {user_msg}"
    )


# ---------------------------------------------
# Webhooks
# ---------------------------------------------
DEBUG_TOKEN = os.getenv("DEBUG_TOKEN", "")

@app.route("/debug/contexto", methods=["GET"])
def debug_contexto():
    token = request.args.get("token", "")
    if not DEBUG_TOKEN or token != DEBUG_TOKEN:
        return {"error": "unauthorized"}, 401
    data = {}
    for key in _backend.keys(CTX_PREFIX + "*"):
        phone = key[len(CTX_PREFIX):]
        ctx = cargar_contexto(phone)
        if ctx is not None:
            data[phone] = ctx
    return {"contexto_usuarios": data}, 200


@app.route("/webhook", methods=["GET"])
def verify():
    """Verificación inicial del webhook con Meta"""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == "mibotverificacion":
        return challenge, 200
    return "Error de verificación", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    """Manejo de mensajes entrantes de WhatsApp"""
    data = request.get_json()
    try:
        entry = data.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})

        if "messages" in value:
            # Ignorar mensajes provenientes de grupos
            if "-" in value["messages"][0].get("from", ""):
                print("[INFO] Mensaje ignorado: proviene de un grupo de WhatsApp.")
                return "ok", 200

            message = value["messages"][0]
            user_phone = message["from"]
            message_id = message.get("id")

            # Extraer el texto del usuario según el tipo de mensaje:
            #  - "text": mensaje escrito normal.
            #  - "interactive": el usuario tocó una opción del menú (lista o botón);
            #    usamos el `id` de la opción, que coincide con las claves 1-7.
            msg_type = message.get("type", "text")
            if msg_type == "text":
                user_msg = message["text"]["body"]
            elif msg_type == "interactive":
                interactive = message.get("interactive", {})
                if interactive.get("type") == "list_reply":
                    user_msg = interactive.get("list_reply", {}).get("id", "")
                elif interactive.get("type") == "button_reply":
                    user_msg = interactive.get("button_reply", {}).get("id", "")
                else:
                    user_msg = ""
            else:
                # Tipos aún no soportados (imagen, audio, etc.): se ignoran sin romper.
                print(f"[INFO] Tipo de mensaje no soportado: {msg_type}")
                return "ok", 200

            if not user_msg:
                return "ok", 200

            # Mostrar "escribiendo…" (y marcar como leído) antes de procesar la respuesta.
            send_typing_indicator(message_id)

            ahora = time.time()

            print(f"[INFO] Mensaje recibido: {user_msg} de {user_phone}")

            # --- BIENVENIDA PARA USUARIOS NUEVOS ---
            # El saludo inicial es determinístico (gratis e instantáneo). A partir de la
            # siguiente respuesta, el agente conduce el embudo de calificación. Sembramos la
            # bienvenida en el historial para que el agente sepa que ya saludó y pidió el nombre.
            es_nuevo = not ya_bienvenido(user_phone) and cargar_contexto(user_phone) is None
            if es_nuevo:
                marcar_bienvenido(user_phone)
                registrar_interesado(user_phone, f"[NUEVO USUARIO] {user_msg}")
                guardar_contexto(user_phone, {
                    "last_seen": ahora, "timestamp": ahora,
                    "history": [{"role": "assistant", "content": BIENVENIDA}], "tema": "nuevo",
                })
                send_message(BIENVENIDA, user_phone)
                return "ok", 200

            # --- MENSAJE CONTEXTUAL SI HUBO SILENCIO LARGO (>2h con perfil incompleto) ---
            ctx_existente = cargar_contexto(user_phone) or {}
            ultimo_contacto = ctx_existente.get("last_seen", ahora)
            perfil_completo = all(
                ctx_existente.get(k) for k in ("nombre", "disciplina_raw", "turno_raw", "dia_raw")
            )

            if (ahora - ultimo_contacto) > SILENCIO_RE_ENGANCHE and not perfil_completo:
                nombre = ctx_existente.get("nombre", "")
                saludo = f", {nombre}" if nombre else ""
                send_message(
                    f"¡Hola de nuevo{saludo}! 👋 Me alegra que hayas vuelto.\n"
                    f"¿Te ayudo a coordinar tu clase de prueba gratuita? 🥋",
                    user_phone
                )
                ctx_existente["last_seen"] = ahora
                guardar_contexto(user_phone, ctx_existente)

            # --- ROUTER DE OPCIONES DIRECTAS (número 1-7) ---
            if user_msg.strip() in respuestas_directas:
                key = user_msg.strip()
                ctx = cargar_contexto(user_phone) or {}
                ctx.setdefault("history", [])
                ctx.update({"tema": key, "timestamp": ahora, "last_seen": ahora})
                guardar_contexto(user_phone, ctx)
                # Respuestas partidas en mensajes cortos; el saludo va solo en el primero.
                for i, chunk in enumerate(respuestas_directas[key]):
                    texto = agregar_saludo(chunk, user_phone) if i == 0 else chunk
                    send_message(texto, user_phone)
                send_list_menu(user_phone)
                return "ok", 200

            # ---TODO LO DEMÁS VA AL AGENTE IA con historial y perfil del prospecto ---
            ctx = get_or_init_user_context(user_phone, ahora)
            append_to_history(ctx, "user", user_msg)
            # Persistir el mensaje del usuario ANTES de correr el agente: la tool
            # guardar_datos_prospecto lee y escribe este mismo contexto en Redis.
            guardar_contexto(user_phone, ctx)

            agent_input = build_agent_input(user_phone, user_msg, ctx["history"], perfil=ctx)
            result = Runner.run_sync(kudo_agent, agent_input)
            texto = getattr(result, "final_output", None) or getattr(result, "output", None) or str(result)

            # El agente puede pedir que mostremos el menú interactivo terminando con [[MENU]].
            mostrar_menu = "[[MENU]]" in texto
            texto = texto.replace("[[MENU]]", "").strip()

            # Recargar: durante su ejecución el agente pudo guardar datos del prospecto
            # (nombre/disciplina/turno/día) en el contexto; recargamos para no pisarlos.
            ctx = cargar_contexto(user_phone) or ctx
            append_to_history(ctx, "assistant", texto)
            ctx["tema"] = "libre"
            ctx["timestamp"] = ahora
            ctx["last_seen"] = ahora
            guardar_contexto(user_phone, ctx)

            registrar_interesado(
                user_phone,
                user_msg,
                nombre=ctx.get("nombre", ""),
                disciplina=ctx.get("disciplina_raw", ""),
                turno=ctx.get("turno_raw", ""),
            )
            send_message(texto, user_phone)
            if mostrar_menu:
                send_list_menu(user_phone)

    except Exception as e:
        print("Error:", e)

    return "ok", 200

@app.route("/testsheet")
def test_sheet():
    try:
        interesados_sheet.append_row(["TEST", "Prueba manual", time.strftime("%Y-%m-%d %H:%M:%S")])
        return "Escritura exitosa", 200
    except Exception as e:
        print("[ERROR]", e)
        return str(e), 500

# ---------------------------------------------
# Inicio del servidor Flask
# ---------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
