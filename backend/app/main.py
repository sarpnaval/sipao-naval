"""Aplicación FastAPI de SARP-Naval (API v0.1.0).

Capa de analítica predictiva sobre los datos logísticos que ya registra
SISLOG. Solo lee/importa datos: NUNCA escribe en SISLOG. Base SQLite
local propia (ver backend.app.db). El sembrado de datos simulados es
explícito: `python -m backend.app.seed` desde la raíz v1.
"""

import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.app import db
from backend.app.db import obtener_bd
from backend.app.rutas_alertas import router as router_alertas
from backend.app.rutas_importar import router as router_importar
from backend.app.rutas_items import router as router_items
from backend.app.rutas_kpis import router as router_kpis
from backend.app.rutas_registro import router as router_registro
from backend.app.rutas_validacion import router as router_validacion
from backend.app.rutas_alistamiento import router as router_alistamiento
from backend.app import config_persistente
from backend.app.rutas_config import router as router_config
from backend.app.rutas_costeo import router as router_costeo
from backend.app.seguridad import escritura_protegida, exigir_token

VERSION = "0.1.0"


@asynccontextmanager
async def ciclo_vida(app: FastAPI):
    """Al arrancar: crea la base si no existe y aplica el esquema.

    El DDL usa CREATE TABLE IF NOT EXISTS, así que ejecutarlo SIEMPRE es
    seguro y además incorpora tablas nuevas (p. ej. `bitacora`, tarea
    C1.2) a bases creadas por versiones anteriores. No siembra datos:
    el sembrado es una acción explícita (python -m backend.app.seed).
    """
    db.inicializar_bd(db.ruta_bd_activa())
    # Reaplica la configuración guardada: sin esto, al reiniciar los
    # parámetros volverían a fábrica mientras la bitácora seguiría
    # afirmando que se cambiaron (defecto corregido el 18-jul-2026).
    conexion = db.obtener_conexion()
    try:
        aplicados, ignorados = config_persistente.cargar_configuracion(conexion)
        if aplicados or ignorados:
            print(f"  Configuración reaplicada: {aplicados} valor(es)"
                  + (f", {ignorados} ignorado(s) por clave inexistente" if ignorados else ""))
    finally:
        conexion.close()
    yield


app = FastAPI(
    title="SARP-Naval API",
    version=VERSION,
    description=(
        "Sistema de Abastecimiento y Reposición Predictiva — Armada del "
        "Ecuador. API local de analítica de inventarios: clasificación "
        "ABC/XYZ/VED, pronóstico de demanda (Holt/Croston), parámetros de "
        "inventario (SS, ROP, EOQ) y alertas priorizadas de reposición. "
        "Solo lectura respecto a SISLOG."),
    lifespan=ciclo_vida,
)

# CORS abierto únicamente a orígenes locales (la app se sirve en localhost)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost", "http://127.0.0.1",
        "http://localhost:8000", "http://127.0.0.1:8000",
        "http://localhost:5500", "http://127.0.0.1:5500",
        "http://localhost:8080", "http://127.0.0.1:8080",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router_kpis)
app.include_router(router_items)
app.include_router(router_alertas)
# Routers de ESCRITURA: si SIPAO_TOKEN_ESCRITURA está definida (instancia
# publicada), exigen la clave de operación. En local no está definida y
# el comportamiento es el de siempre.
_guardia = [Depends(exigir_token)]
app.include_router(router_importar, dependencies=_guardia)
app.include_router(router_registro, dependencies=_guardia)  # registro directo (C1.2)
app.include_router(router_validacion)
app.include_router(router_alistamiento)  # optimizador RBS (17-jul)
app.include_router(router_costeo)  # matriz de costeo (17-jul)
app.include_router(router_config, dependencies=_guardia)  # panel de configuracion


@app.get("/api/salud", tags=["Salud"])
def salud(bd: sqlite3.Connection = Depends(obtener_bd)):
    """Estado operativo de la API y resumen de los datos cargados."""
    items_cargados = bd.execute(
        "SELECT COUNT(*) AS n FROM items").fetchone()["n"]
    fila = bd.execute(
        "SELECT valor FROM metadatos WHERE clave = 'generado'").fetchone()
    return {
        "estado": "operativo",
        "version": VERSION,
        "fecha_datos": fila["valor"] if fila else None,
        "items_cargados": items_cargados,
    }


@app.exception_handler(StarletteHTTPException)
async def manejar_error_http(request: Request, exc: StarletteHTTPException):
    """Errores HTTP con mensajes en español (404 genérico traducido)."""
    detalle = exc.detail
    if exc.status_code == 404 and detalle == "Not Found":
        detalle = ("Recurso no encontrado: la ruta solicitada no existe "
                   "en la API SARP-Naval.")
    if exc.status_code == 405 and detalle == "Method Not Allowed":
        detalle = "Método HTTP no permitido para esta ruta."
    return JSONResponse(status_code=exc.status_code,
                        content={"error": detalle})


@app.exception_handler(RequestValidationError)
async def manejar_error_validacion(request: Request,
                                   exc: RequestValidationError):
    """Errores 422 de validación automática con el mismo contrato
    {'error': ...} en español que usa el resto de la API."""
    campos = sorted({
        " → ".join(str(parte) for parte in error.get("loc", ()))
        for error in exc.errors()
    })
    return JSONResponse(
        status_code=422,
        content={"error": ("Parámetros inválidos en la petición: "
                           + "; ".join(campos)
                           + ". Revise tipos y rangos permitidos.")},
    )


@app.exception_handler(Exception)
async def manejar_error_interno(request: Request, exc: Exception):
    """Error 500 genérico en español (sin filtrar detalles internos)."""
    return JSONResponse(
        status_code=500,
        content={"error": ("Error interno del servidor SARP-Naval. "
                           "Revise el registro de la aplicación.")},
    )


# ---------------------------------------------------------------------
# Archivos estáticos de la app conectada (tarea 2.4-2.7).
#
# Se monta la carpeta frontend/ en la raíz "/" DESPUÉS de registrar todos
# los routers y endpoints de la API: en Starlette las rutas se resuelven
# por orden de registro, así que "/api/*" sigue atendido por los routers
# y solo lo que NO empieza por una ruta de la API cae en StaticFiles.
# html=True hace que "/" sirva index.html. Si la carpeta no existe (p. ej.
# entornos de solo-API), simplemente no se monta y la API funciona igual.
# ---------------------------------------------------------------------
DIR_FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
if DIR_FRONTEND.is_dir():
    app.mount(
        "/",
        StaticFiles(directory=str(DIR_FRONTEND), html=True),
        name="frontend",
    )
