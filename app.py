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

# Diccionario para almacenar contexto por usuario (tema y tiempo)
contexto_usuarios = {}
usuarios_bienvenidos = set()  # phones que ya recibieron el mensaje de bienvenida

# ✅ Config memoria (30 minutos)
TTL_SEGUNDOS = 1800
MAX_TURNOS = 20  # 20 turnos (user+assistant). Ajusta si quieres.
SILENCIO_RE_ENGANCHE = 7200  # 2 horas — umbral para mensaje contextual de retorno

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

respuestas_directas = {
    "1": "👉 *Horarios de clases en KUDO Bolivia:*\n• "
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
         "\n"
         "📍 *Brazilian Jiu-Jitsu Kids*\n"
         "     • Lunes, Miércoles y Viernes: 18:30–19:30\n"
         "\n"
         "📍 *Kick Boxing*\n"
         "   🕗 *Turno mañana:*\n"
         "     • Martes y Jueves: 7:00–8:30\n"
         "   🌙 *Turno noche:*\n"
         "     • Martes y Jueves: 18:00–19:30\n",
    "2": "👉 *Precios:*\n"
         "Bs. 250 la mensualidad por persona (3 clases por semana).\n\n"
         "Si preferís asistir solo un día, dos días o únicamente los sábados, "
         "es posible coordinar una configuración diferente. "
         "Acercate al dojo para consultar el precio según tu disponibilidad. 😊",
    "3": "👉 *Disciplinas que ofrecemos:"
         "*\n🥋 Kudo\n\t"
         "Que es KUDO: https://www.youtube.com/watch?v=NqcE1J7z2eE\n\n"
         "*\n🥋 Brazilian Jiu-Jitsu\n\t"
         "Que es BJJ: https://www.youtube.com/watch?v=tztK3dJksk0\n\n"
         "*\n🥋 Kick Boxing\n\t"
         "Que es Kick Boxing: https://www.youtube.com/watch?v=Sh9cVUidnr0&pp=ygULa2ljayBib3hpbmc%3D",
    "4": (
        "👉 *¿Cómo inscribirte en KUDO Bolivia?*\n\n"
        "¡Es muy sencillo! Solo ven al dojo y te inscribimos en el momento.\n\n"
        "📍 Calle Cañada Strongest N.º 1847, a pasos de la plaza del estudiante, La Paz.\n\n"
        "🎁 *¿Sabías que puedes venir primero a una clase de prueba GRATIS?* "
        "Sin compromiso, sin costo. Es la mejor forma de conocernos.\n\n"
        "👉 *¿Cuándo podrías venir?* Dime el día (ej: 'este jueves', 'el sábado por la mañana') "
        "y te confirmo el horario exacto. 🗓️"
    ),
    "5": "📍 *Ubicación:* Calle Cañada Strongest N.º 1847 - a pasos de la plaza del estudiante, "
         "La Paz, Bolivia.\n\n"
         "📌Mapa: https://maps.app.goo.gl/CeW1sAW77AgTzriA6?g_st=ipc",
    "6": "¿Qué es Kudo?\n\n"
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
         "• *Mente abierta* (humildad, imparcialidad y aprendizaje continuo).\n\n"
         "\n"
         "📹 Videos recomendados:\n"
         "🎥 Mira este video: https://www.youtube.com/watch?v=NqcE1J7z2eE&\n\n"
         "🎥 Highlights: https://www.youtube.com/watch?v=JtTWeISoAFA&\n\n"
         "🎥 Mundial 2023: https://www.youtube.com/watch?v=jfcne0M5qEU",
    "7": "🥊 *Guantillas para MMA*\n\n"
         "¡GUANTILLAS PARA MMA, PARA DARLE CALIDAD A TUS ENTRENAMIENTOS!\n"
         "En venta guantillas para MMA, nuevas. También adecuados para tu práctica de cualquier Arte Marcial y entrenamiento en sacos, pads/manoplas, gobernadoras, wall pad (saco de pared). Perfectas para todas las edades por su diseño ergonómico.\n\n"
         "💰 *Precios:*\n"
         "- 1 par: Bs. 90\n"
         "- 2 pares o más: Bs. 80 cada par.\n\n"
         "⏰ *Horario de atención para ventas:* Lunes a viernes de 14:00 a 15:30.\n\n"
         "📍 *Lugar de entrega:* Calle Cañada Strongest 1847 (Ed. Sarawi) – Dojo \"KUDO BOLIVIA\", a media cuadra de la plaza del estudiante."
}

# Menú adicional que se agrega al final de cada mensaje
menu = ("\n\n📋 ¿Sobre qué más te gustaría saber?\n"
        "1️⃣ Horarios\n2️⃣ Precios\n3️⃣ Disciplinas\n4️⃣ Inscripción\n5️⃣ Ubicación\n6️⃣ ¿Qué es Kudo?\n7️⃣ Venta de Guantes")

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
    "respuesta seguida siempre de este menú de opciones:\n"
    "1️⃣ Horarios\n"
    "2️⃣ Precios\n"
    "3️⃣ Disciplinas\n"
    "4️⃣ Inscripción\n"
    "5️⃣ Ubicación\n"
    "6️⃣ ¿Qué es Kudo?\n"
    "7️⃣ Venta de Guantes\n"
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
    "información? Recuerda que tu primera clase es GRATIS. ' seguido del menú.\n"
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


def registrar_interesado(phone, message, nombre="", disciplina="", turno="", dia=""):
    fecha = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    interesados_sheet.append_row([phone, message, fecha, nombre, disciplina, turno, dia])


def registrar_solicitud_humana(phone, message):
    fecha = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    solicitudes_sheet.append_row([phone, message, fecha])


def agregar_saludo(texto, phone):
    """Antepone el nombre del usuario si está disponible en el contexto."""
    nombre = contexto_usuarios.get(phone, {}).get("nombre")
    return f"¡Hola, {nombre}! 😊\n\n{texto}" if nombre else texto


def limpiar_contextos_expirados(ahora):
    """Borra de contexto_usuarios todos los usuarios cuyo last_seen expiró (30 min)."""
    for phone, ctx in list(contexto_usuarios.items()):
        if ahora - ctx.get("last_seen", 0) > TTL_SEGUNDOS:
            del contexto_usuarios[phone]


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
    ctx = contexto_usuarios.setdefault(user_phone, {})
    if nombre:
        ctx["nombre"] = nombre
    if disciplina:
        ctx["disciplina_raw"] = disciplina
    if turno:
        ctx["turno_raw"] = turno
    if dia:
        ctx["dia_raw"] = dia
    ctx["last_seen"] = time.time()
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
# ✅ Memoria de conversación (30 min) en RAM
# ---------------------------------------------
def get_or_init_user_context(user_phone: str, ahora: float):
    ctx = contexto_usuarios.get(user_phone)
    if ctx and (ahora - ctx.get("last_seen", 0) > TTL_SEGUNDOS):
        ctx = None
    if not ctx:
        ctx = {"last_seen": ahora, "history": [], "etapa_calificacion": 99}
        contexto_usuarios[user_phone] = ctx
    # Contextos creados por los routers directos/keyword pueden no tener "history"
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
    return {"contexto_usuarios": contexto_usuarios}, 200


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
            user_msg = message["text"]["body"]
            user_phone = message["from"]
            ahora = time.time()
            limpiar_contextos_expirados(ahora)

            print(f"[INFO] Mensaje recibido: {user_msg} de {user_phone}")

            # --- BIENVENIDA PARA USUARIOS NUEVOS ---
            # El saludo inicial es determinístico (gratis e instantáneo). A partir de la
            # siguiente respuesta, el agente conduce el embudo de calificación. Sembramos la
            # bienvenida en el historial para que el agente sepa que ya saludó y pidió el nombre.
            es_nuevo = (user_phone not in usuarios_bienvenidos and
                        user_phone not in contexto_usuarios)
            if es_nuevo:
                usuarios_bienvenidos.add(user_phone)
                registrar_interesado(user_phone, f"[NUEVO USUARIO] {user_msg}")
                contexto_usuarios[user_phone] = {
                    "last_seen": ahora, "timestamp": ahora,
                    "history": [{"role": "assistant", "content": BIENVENIDA}], "tema": "nuevo",
                }
                send_message(BIENVENIDA, user_phone)
                return "ok", 200

            # --- MENSAJE CONTEXTUAL SI HUBO SILENCIO LARGO (>2h con perfil incompleto) ---
            ctx_existente = contexto_usuarios.get(user_phone, {})
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

            # --- ROUTER DE OPCIONES DIRECTAS (número 1-7) ---
            if user_msg.strip() in respuestas_directas:
                key = user_msg.strip()
                if user_phone not in contexto_usuarios:
                    contexto_usuarios[user_phone] = {}
                contexto_usuarios[user_phone].update({"tema": key, "timestamp": ahora, "last_seen": ahora})
                send_message(agregar_saludo(respuestas_directas[key], user_phone) + menu, user_phone)
                return "ok", 200

            # ---TODO LO DEMÁS VA AL AGENTE IA con historial y perfil del prospecto ---
            ctx = get_or_init_user_context(user_phone, ahora)
            append_to_history(ctx, "user", user_msg)

            agent_input = build_agent_input(user_phone, user_msg, ctx["history"], perfil=ctx)
            result = Runner.run_sync(kudo_agent, agent_input)
            texto = getattr(result, "final_output", None) or getattr(result, "output", None) or str(result)

            append_to_history(ctx, "assistant", texto)
            contexto_usuarios[user_phone]["tema"] = "libre"
            contexto_usuarios[user_phone]["timestamp"] = ahora

            registrar_interesado(
                user_phone,
                user_msg,
                nombre=ctx.get("nombre", ""),
                disciplina=ctx.get("disciplina_raw", ""),
                turno=ctx.get("turno_raw", ""),
            )
            send_message(texto, user_phone)

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
