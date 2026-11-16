"""Configuración del bot leída de variables de entorno (y de .env en local).

Las variables reales del entorno (Railway) tienen prioridad sobre el archivo .env.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
log = logging.getLogger("config")

# Valores que antes estaban fijos en app.py. Se mantienen como valor por defecto para no romper un
# despliegue que todavía no definió las variables nuevas; conviene definirlas en Railway.
VERIFY_TOKEN_POR_DEFECTO = "mibotverificacion"
NUMEROS_PERSONAL_POR_DEFECTO = "59179598641,59176785574"


def _bool(nombre: str, defecto: bool) -> bool:
    valor = os.environ.get(nombre)
    if valor is None or valor.strip() == "":
        return defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


def _float(nombre: str, defecto: float) -> float:
    try:
        return float(os.environ.get(nombre, "") or defecto)
    except ValueError:
        log.warning("%s no es un número; se usa %s", nombre, defecto)
        return defecto


def _lista(texto: str) -> list[str]:
    return [n for n in ("".join(c for c in parte if c.isdigit()) for parte in texto.split(",")) if n]


@dataclass
class Settings:
    data_dir: Path
    # WhatsApp (Meta Cloud API)
    whatsapp_token: str = ""
    phone_number_id: str = ""
    verify_token: str = VERIFY_TOKEN_POR_DEFECTO
    app_secret: str = ""
    graph_api_version: str = "v18.0"
    # OpenAI
    openai_api_key: str = ""
    modelo: str = "gpt-4.1"
    precio_entrada_usd_m: float = 2.0    # US$ por millón de tokens de entrada (gpt-4.1)
    precio_salida_usd_m: float = 8.0     # US$ por millón de tokens de salida (gpt-4.1)
    # Google Sheets (copia secundaria de los registros)
    google_sheet_key: str = ""
    google_credentials_json: str = ""
    # Equipo y negocio
    numeros_personal: list[str] = field(default_factory=list)
    zona_horaria: str = "America/La_Paz"
    pausa_derivacion_horas: float = 0.0  # 0 = solicitar_asistencia_humana NO pausa el bot
    pausa_respuesta_horas: float = 12.0  # pausa al responder desde el panel
    # Panel
    panel_activo: bool = True
    panel_usuario_inicial: str = ""
    panel_clave_inicial: str = ""
    panel_cookie_segura: bool = True
    panel_sesion_horas: float = 12.0
    panel_refrescar_seg: int = 60
    # Tareas únicas de arranque: migración desde el Redis anterior e importación del histórico de Sheets
    migrar_desde_redis_url: str = ""
    importar_historico_sheets: bool = False

    @property
    def ruta_db(self) -> Path:
        return self.data_dir / "kudo.db"


def _credenciales_google() -> str:
    """JSON de la cuenta de servicio: variable GOOGLE_CREDENTIALS_JSON o, en local, credentials.json."""
    texto = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if texto:
        return texto
    archivo = Path(os.environ.get("GOOGLE_CREDENTIALS_FILE", RAIZ / "credentials.json"))
    if archivo.is_file():
        return archivo.read_text(encoding="utf-8")
    return ""


def _url_migracion_redis() -> str:
    """MIGRAR_DESDE_REDIS_URL; en Railway, si no está definida, el REDIS_URL que ya usaba el bot anterior.
    Una MIGRAR_DESDE_REDIS_URL vacía desactiva la migración."""
    if "MIGRAR_DESDE_REDIS_URL" in os.environ:
        return os.environ["MIGRAR_DESDE_REDIS_URL"].strip()
    if os.environ.get("RAILWAY_ENVIRONMENT_NAME") or os.environ.get("RAILWAY_ENVIRONMENT"):
        return os.environ.get("REDIS_URL", "").strip()
    return ""


def cargar_settings(env_file: Path | str | None = None) -> Settings:
    load_dotenv(env_file or RAIZ / ".env", override=False)
    data_dir = Path(os.environ.get("DATA_DIR") or RAIZ / "data")
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        data_dir=data_dir,
        whatsapp_token=os.environ.get("WHATSAPP_TOKEN", ""),
        phone_number_id=os.environ.get("WHATSAPP_PHONE_NUMBER_ID") or os.environ.get("PHONE_NUMBER_ID", ""),
        verify_token=os.environ.get("WHATSAPP_VERIFY_TOKEN") or VERIFY_TOKEN_POR_DEFECTO,
        app_secret=os.environ.get("WHATSAPP_APP_SECRET", ""),
        graph_api_version=os.environ.get("GRAPH_API_VERSION") or "v18.0",
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        modelo=os.environ.get("OPENAI_MODELO") or "gpt-4.1",
        precio_entrada_usd_m=_float("PRECIO_ENTRADA_USD_M", 2.0),
        precio_salida_usd_m=_float("PRECIO_SALIDA_USD_M", 8.0),
        google_sheet_key=os.environ.get("GOOGLE_SHEET_KEY", ""),
        google_credentials_json=_credenciales_google(),
        numeros_personal=_lista(os.environ.get("NUMEROS_PERSONAL") or NUMEROS_PERSONAL_POR_DEFECTO),
        zona_horaria=os.environ.get("ZONA_HORARIA") or "America/La_Paz",
        pausa_derivacion_horas=_float("PAUSA_DERIVACION_HORAS", 0.0),
        pausa_respuesta_horas=_float("PAUSA_RESPUESTA_HORAS", 12.0),
        panel_activo=_bool("PANEL_ACTIVO", True),
        panel_usuario_inicial=(os.environ.get("PANEL_USUARIO_INICIAL") or "").strip().lower(),
        panel_clave_inicial=os.environ.get("PANEL_CLAVE_INICIAL") or "",
        panel_cookie_segura=_bool("PANEL_COOKIE_SEGURA", True),
        panel_sesion_horas=_float("PANEL_SESION_HORAS", 12.0),
        panel_refrescar_seg=int(_float("PANEL_REFRESCAR_SEG", 60)),
        migrar_desde_redis_url=_url_migracion_redis(),
        importar_historico_sheets=_bool("IMPORTAR_HISTORICO_SHEETS", False),
    )
