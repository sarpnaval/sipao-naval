# SIPAO-Naval — imagen del aplicativo (FastAPI + Uvicorn + SQLite).
# La MISMA aplicación que corre en local: no hay build especial ni variante
# "de nube". Lo que se prueba con pytest es lo que se publica.
FROM python:3.11-slim

# Zona horaria de Ecuador, para que las marcas de la bitácora de auditoría
# coincidan con la hora del reparto.
ENV TZ=America/Guayaquil \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias primero: aprovecha la caché de capas en cada redespliegue.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
# `scripts/` NO es accesorio: la siembra del catálogo referencial pasa por
# scripts/generar_dataset_realista.py, igual que en local. Sin él, el
# arranque falla con ModuleNotFoundError (ocurrió el 18-jul-2026).
COPY scripts/ ./scripts/

# La base vive en un directorio propio para poder respaldarla y restaurarla
# como una sola pieza (el archivo .db pesa menos de 1 MB).
ENV SARP_BD=/app/datos/sipao.db
RUN mkdir -p /app/datos

# Hugging Face Spaces expone el 7860; Render y Cloud Run inyectan $PORT.
ENV PORT=7860
EXPOSE 7860

# Siembra la base solo si está vacía, y arranca. Así el primer despliegue
# queda utilizable de inmediato y los siguientes conservan lo cargado.
CMD ["sh", "-c", "python -m backend.app.arranque && exec uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-7860}"]
