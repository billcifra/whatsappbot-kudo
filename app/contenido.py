"""Contenido fijo del bot: menú 1-7 (+8 del evento), bienvenida, feriados y evento temporal vigente.

Editar aquí los textos, horarios del menú, feriados o el evento del momento. Los horarios del
agente viven en prompts.py: si cambian, actualizar AMBOS archivos.
"""

# ---------------------------------------------
# 📅 Feriados / días SIN clases de prueba
# ---------------------------------------------
# Días en los que el dojo NO dicta clases (feriados, cierres, etc.).
# El agente NO debe coordinar ni confirmar clases de prueba en estas fechas.
# Formato: "YYYY-MM-DD": "motivo". Edita esta lista para agregar o quitar feriados.
FERIADOS = {
    "2026-12-25": "Receso de fin de año (Navidad) — dojo cerrado",
    "2026-12-26": "Receso de fin de año — dojo cerrado",
    "2026-12-27": "Receso de fin de año — dojo cerrado",
    "2026-12-28": "Receso de fin de año — dojo cerrado",
    "2026-12-29": "Receso de fin de año — dojo cerrado",
    "2026-12-30": "Receso de fin de año — dojo cerrado",
    "2026-12-31": "Receso de fin de año — dojo cerrado",
    "2027-01-01": "Receso de fin de año (Año Nuevo) — dojo cerrado",
}

# ---------------------------------------------
# Evento temporal vigente (camps de vacaciones, promociones, etc.).
# Se promociona automáticamente solo mientras hoy <= EVENTO_PROMO_HASTA;
# después desaparece de las respuestas del bot (bienvenida, agente y opción 8 del menú)
# sin tocar más código.
# Para anunciar un evento nuevo, llena estas constantes y RESPUESTA_EVENTO / FILA_MENU_EVENTO;
# sin evento, deja EVENTO_PROMO_HASTA en "".
# ---------------------------------------------
EVENTO_ID = "vacacional_2026_27"   # se guarda en contactos.evento; el panel filtra por él
EVENTO_NOMBRE = "Curso vacacional"  # nombre corto para el panel
EVENTO_DESDE = "2026-12-01"         # primer día del evento (para frasear "empieza"/"en curso")
EVENTO_PROMO_HASTA = "2027-01-29"   # último día de promoción (YYYY-MM-DD); "" = sin evento
EVENTO_TEASER = (                   # línea corta para el mensaje de bienvenida; terminar en "\n\n"
    "☀️ *¡Curso vacacional de Kudo para niños y jóvenes (7 a 17 años)!* "
    "Diciembre y enero, *Bs. 400 los dos meses*.\n\n"
)
EVENTO_INFO = (                     # descripción: nombre, fechas, horarios, precios
    "CURSO VACACIONAL DE KUDO (arte marcial mixto japonés) — diciembre 2026 / enero 2027:\n"
    "  • Fechas: martes 1 de diciembre de 2026 al viernes 29 de enero de 2027.\n"
    "  • Días: lunes, miércoles y viernes.\n"
    "  • Grupo INFANTIL (7 a 12 años): 9:30–10:30 (mañana) ó 15:30–16:30 (tarde).\n"
    "  • Grupo JUVENIL (13 a 17 años): 8:30–9:30 (mañana) ó 14:30–15:30 (tarde).\n"
    "  • Receso vacacional: del 25 de diciembre al 1 de enero (el dojo está cerrado esos días).\n"
    "  • Promoción por vacaciones: Bs. 400 por los DOS meses (diciembre y enero).\n"
    "  • Primera clase de prueba GRATIS, sin compromiso.\n"
    "  • Lugar: Cañada Strongest N.º 1847, Edificio 'Sarawi' — Dojo 'KUDO' "
    "(a media cuadra de la plaza del Estudiante).\n"
    "  • Las clases regulares (Kudo niños, jóvenes y adultos, y BJJ) siguen con su horario normal.\n"
)
EVENTO_INSTRUCCIONES = (            # instrucciones al agente sobre cómo responder/promocionarlo
    "INSTRUCCIONES sobre el curso vacacional:\n"
    "  • Usa estos datos para responder cualquier pregunta sobre el curso vacacional / vacaciones / "
    "curso de verano / clases para niños en diciembre o enero.\n"
    "  • Antes de dar el horario, pregunta la EDAD del niño o joven para ubicarlo en el grupo "
    "Infantil (7–12) o Juvenil (13–17), y da solo el horario de su grupo.\n"
    "  • Cuando te den la edad o muestren interés en el curso, llama a `guardar_datos_prospecto` "
    "con `edad` (tal como la dijeron) e `interes_evento=true`, junto con los demás datos que tengas.\n"
    "  • Si la edad está fuera de 7 a 17 años, explica con amabilidad que el curso vacacional es "
    "para 7 a 17 años y ofrécele las clases regulares (que siguen en diciembre y enero).\n"
    "  • Menciónalo de forma proactiva (sin ser insistente) cuando hablen de niños o jóvenes, o "
    "cuando ofrezcas el menú. Compara FECHA_HOY con el inicio (2026-12-01) para frasear: si aún no "
    "empieza di que 'empieza el martes 1 de diciembre'; si ya está dentro de las fechas, di que "
    "'está en curso'.\n"
    "  • El curso vacacional TAMBIÉN tiene clase de prueba GRATIS, sin compromiso: invítalos a "
    "venir a una clase del horario de su grupo (lunes, miércoles o viernes) y coordina el día como "
    "cualquier clase de prueba (respetando el receso y los FERIADOS). Después de la prueba, el curso "
    "cuesta Bs. 400 por diciembre y enero. Si preguntan por un precio que no figura aquí (por "
    "ejemplo, entrar a mitad del curso o un solo mes), NO lo inventes: indica que lo consulten en "
    "el dojo.\n"
    "  • Para inscribirse: en el dojo, o usa `solicitar_asistencia_humana` si quieren que el "
    "equipo los contacte para la inscripción.\n"
    "  • En el menú interactivo, la opción 'Curso vacacional' muestra este curso.\n"
)
# Opción 8 del menú: solo aparece mientras el evento está vigente.
FILA_MENU_EVENTO = {"id": "8", "title": "Curso vacacional", "description": "Kudo 7 a 17 años · dic–ene · Bs. 400"}
RESPUESTA_EVENTO = [
    "☀️ *Curso vacacional de Kudo* 🥋\n"
    "📅 1 de diciembre al 29 de enero · Lun, Mié y Vie\n\n"
    "📍 *Infantil (7 a 12 años)*\n"
    "• 9:30–10:30 ó 15:30–16:30\n\n"
    "📍 *Juvenil (13 a 17 años)*\n"
    "• 8:30–9:30 ó 14:30–15:30\n\n"
    "⛔ Receso: 25 de diciembre al 1 de enero.",

    "💰 *Promoción por vacaciones:* Bs. *400* por diciembre y enero.\n"
    "🎁 La *primera clase es GRATIS*, sin compromiso.\n"
    "📍 Cañada Strongest N.º 1847, Ed. Sarawi — a media cuadra de la plaza del Estudiante.\n\n"
    "👉 ¿Qué edad tiene tu hijo/a? Te digo su grupo y coordinamos su clase de prueba. 😊",
]
# --- Ejemplo (Winter Camp jul-2026), dejar comentado como plantilla: ---
# EVENTO_PROMO_HASTA = "2026-07-17"
# EVENTO_TEASER = (
#     "❄️ *¡Nuevo! Winter Camp de Kudo, del 6 al 17 de julio* "
#     "(Full Bs. 250 / Half Bs. 150) — cupos limitados.\n\n"
# )
# EVENTO_INFO = (
#     "WINTER CAMP (vacaciones de invierno) — disciplina *Kudo*:\n"
#     "  • Fechas: lunes 6 al viernes 17 de julio (lunes a viernes)\n"
#     "  • Horarios: 10:00–11:00 ó 15:00–16:00 (se elige uno)\n"
#     "  • Full Camp (Lunes a Viernes): Bs. 250\n"
#     "  • Half Camp (Lunes, Miércoles y Viernes): Bs. 150\n"
#     "  • Cupos limitados.\n"
# )
# EVENTO_INSTRUCCIONES = (
#     "INSTRUCCIONES sobre el Winter Camp:\n"
#     "  • Usa estos datos para responder cualquier pregunta sobre el winter camp / "
#     "campamento de invierno / vacaciones.\n"
#     "  • Menciónalo de forma proactiva (sin ser insistente) cuando saludes o cuando "
#     "ofrezcas el menú de opciones. Compara FECHA_HOY con el inicio (2026-07-06) "
#     "para frasear correctamente: si aún no empieza di que 'empieza el lunes 6 de julio'; "
#     "si ya está dentro de las fechas, di que 'está en curso'.\n"
#     "  • El Winter Camp es un programa PAGADO (Full Bs. 250 / Half Bs. 150); NO es la clase "
#     "de prueba gratuita. Para reservar un cupo (son limitados), pide el nombre y usa "
#     "`guardar_datos_prospecto` y/o `solicitar_asistencia_humana` para coordinar la inscripción.\n"
# )

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
        "🔄 *Kick Boxing — en reapertura*\n"
        "Estamos formando el nuevo grupo y abriremos horario en cuanto tengamos cupo suficiente. "
        "¿Te anoto para avisarte apenas se habilite? 📲\n"
        "Mientras tanto, ¡te invitamos a una *clase de prueba GRATIS* de Kudo o BJJ para que conozcas el dojo! 🥋\n\n"
        "⛔ BJJ no abre sábados ni domingos.",

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
        "🥋 *Kick Boxing* *(en reapertura)* — qué es: https://www.youtube.com/watch?v=Sh9cVUidnr0",
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
    {"id": "3", "title": "Disciplinas", "description": "Kudo, BJJ y Kick Boxing (próx.)"},
    {"id": "4", "title": "Inscripción", "description": "Cómo empezar + clase gratis"},
    {"id": "5", "title": "Ubicación", "description": "Dónde estamos"},
    {"id": "6", "title": "¿Qué es Kudo?", "description": "Conoce el arte marcial"},
    {"id": "7", "title": "Venta de Guantes", "description": "Guantillas de MMA en venta"},
]
MENU_BODY = "📋 ¿Sobre qué te gustaría saber? Toca una opción 👇"

# Respuestas fijas para mensajes que no son texto.
AUDIO_NO_ENTENDIDO = ("🎙️ Recibí tu audio pero no logré entenderlo bien. "
                      "¿Me lo puedes escribir en un mensajito? 😊")
TIPO_NO_SOPORTADO = ("Por ahora puedo leer *texto* y escuchar *notas de voz* 🎙️. "
                     "Cuéntame por aquí en qué te puedo ayudar 😊")

# Si el agente de IA falla (OpenAI caído, error inesperado): el menú sigue funcionando sin IA.
FALLA_AGENTE = ("Disculpa, tuve un problema técnico 🙏 "
                "Mientras lo resolvemos, toca una opción del menú 👇")

# Nombre corto de cada opción del menú (para el historial y el panel).
TITULO_OPCION = {fila["id"]: fila["title"] for fila in [*MENU_ROWS, FILA_MENU_EVENTO]}


def evento_vigente(hoy: str) -> bool:
    """True mientras se promociona el evento temporal (`hoy` es 'YYYY-MM-DD' local)."""
    return bool(EVENTO_PROMO_HASTA) and hoy <= EVENTO_PROMO_HASTA


def menu_rows(hoy: str) -> list[dict[str, str]]:
    """Filas del menú interactivo: las fijas y, si hay evento vigente, la opción 8."""
    return [*MENU_ROWS, FILA_MENU_EVENTO] if evento_vigente(hoy) else list(MENU_ROWS)


def respuesta_directa(clave: str, hoy: str) -> list[str] | None:
    """Mensajes fijos de una opción del menú, o None si no es una opción disponible hoy."""
    if clave in respuestas_directas:
        return respuestas_directas[clave]
    if clave == FILA_MENU_EVENTO["id"] and evento_vigente(hoy):
        return RESPUESTA_EVENTO
    return None


# Mensajes de conversión para leads de publicidad
def construir_bienvenida(hoy: str) -> str:
    """Mensaje de bienvenida para usuarios nuevos. `hoy` es la fecha local 'YYYY-MM-DD'.

    Si hay un evento temporal vigente (hoy <= EVENTO_PROMO_HASTA) añade su teaser
    corto; pasada la fecha (o sin evento configurado), el teaser desaparece solo.
    """
    teaser = EVENTO_TEASER if evento_vigente(hoy) else ""
    return (
        "¡Hola! 👋 Bienvenido/a a *KUDO Bolivia*, tu centro de artes marciales en La Paz.\n\n"
        f"{teaser}"
        "🥋 Entrenamos *Kudo*, *Brazilian Jiu-Jitsu* y *Defensa Personal* (Kick Boxing próximamente).\n"
        "🎁 *¡Tu primera clase es completamente GRATIS!* Sin compromiso.\n\n"
        "Para ayudarte mejor, ¿cómo te llamas? 😊"
    )
