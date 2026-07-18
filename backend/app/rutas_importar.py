"""Ruta de importación de datos SISLOG (tarea 2.3).

Recibe la plantilla de importación (un .xlsx de tres hojas o tres .csv,
formato de README_DATOS.md) y delega en backend.app.importador:

- POST /api/importar?aplicar=false (por defecto): DRY-RUN. Valida y
  analiza sin tocar NUNCA la base; devuelve el reporte de errores,
  advertencias, resumen y calidad de datos para mostrarlo en pantalla.
- POST /api/importar?aplicar=true: si el reporte es válido (cero
  errores), reemplaza los datos y recalcula parámetros, pronósticos,
  alertas y clasificación en una transacción atómica. Si hay errores,
  NO se aplica nada.
- GET /api/importar/plantilla: describe el formato esperado.

Principio CLAUDE.md: la app solo LEE los archivos que el usuario sube;
NUNCA escribe en SISLOG. Las órdenes de reposición salen por el canal
formal (CSV/PDF), no por este endpoint.
"""

import sqlite3
from typing import List, Optional

from fastapi import APIRouter, Header, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse

from backend.app.db import obtener_conexion
from backend.app.importador import descripcion_plantilla, importar
from backend.app.rutas_registro import _anotar_bitacora, resolver_rol

router = APIRouter(prefix="/api", tags=["Importación"])

# Límite de tamaño total de la subida (suma de todos los archivos).
LIMITE_SUBIDA_BYTES = 10 * 1024 * 1024  # 10 MB


@router.get("/importar/plantilla")
def plantilla_importacion():
    """Describe el formato de la plantilla de importación (para la UI)."""
    return descripcion_plantilla()


@router.post("/importar")
async def importar_datos(
    archivos: List[UploadFile],
    aplicar: bool = Query(
        False,
        description="false = solo validar (dry-run, no toca la base); "
                    "true = aplicar si no hay errores."),
    x_rol_demo: Optional[str] = Header(None, alias="X-Rol-Demo"),
):
    """Valida (y opcionalmente aplica) una importación de datos.

    Devuelve 200 con el reporte {valido, errores, advertencias, resumen,
    aplicado, kpi, calidad_datos}. Un reporte con errores de validación
    NO es un error HTTP: es 200 con valido=false y la lista completa de
    errores, para que el frontend los muestre todos de una vez.
    """
    if not archivos:
        raise HTTPException(
            status_code=422,
            detail="No se recibió ningún archivo. Suba un .xlsx de tres "
                   "hojas o los tres .csv (maestro_items, movimientos, "
                   "stock_actual).")

    subida = []
    total = 0
    for archivo in archivos:
        contenido = await archivo.read()
        total += len(contenido)
        if total > LIMITE_SUBIDA_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"La subida supera el límite de "
                       f"{LIMITE_SUBIDA_BYTES // (1024 * 1024)} MB.")
        subida.append((archivo.filename, contenido))

    conexion = None
    try:
        if aplicar:
            conexion = obtener_conexion()
        reporte = importar(subida, conexion=conexion, aplicar=aplicar)
        if reporte["aplicado"]:
            # Pista de auditoría (tarea C1.2): la importación aplicada
            # queda en la bitácora, que NO se borra al reemplazar datos.
            res = reporte["resumen"]
            _anotar_bitacora(
                conexion, resolver_rol(x_rol_demo), "importacion", None,
                f"Importación aplicada: {res['items']} ítems, "
                f"{res['movimientos']} movimientos, "
                f"{res['meses_historia']} meses de historia "
                f"(reparto {res['reparto']}).")
            conexion.commit()
    except sqlite3.Error as exc:
        # Fallo al aplicar: la transacción hizo rollback; la base previa
        # queda intacta. Se informa en español sin filtrar internos.
        raise HTTPException(
            status_code=500,
            detail="No se pudo aplicar la importación; la base de datos "
                   "anterior quedó intacta. Detalle técnico: "
                   f"{exc}") from exc
    finally:
        if conexion is not None:
            conexion.close()

    return JSONResponse(status_code=200, content=reporte)
