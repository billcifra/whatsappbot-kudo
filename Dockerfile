FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Chequeo de compatibilidad openai / openai-agents: si no encajan, el build falla y Railway
# mantiene la versión anterior (antes, el bot desplegaba y fallaba en cada mensaje al agente).
RUN python -c "from agents import RunContextWrapper; from agents.usage import Usage; Usage(); RunContextWrapper(context=None)"
COPY app ./app
COPY scripts ./scripts
# La base SQLite vive en DATA_DIR=/data: en Railway hay que montar un Volume en /data.
# No se usa la instrucción VOLUME porque Railway no la acepta.
EXPOSE 8000
# Un solo proceso a propósito: SQLite y el orden por cliente (asyncio.Lock) viven en este proceso.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
