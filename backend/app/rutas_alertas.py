"""Rutas de la cola de alertas priorizadas de SARP-Naval.

La prioridad (1..N) la calcula el sembrado según el dossier §5.4:
QUIEBRE > REPONER > EXCESO, luego criticidad V > E > D, luego menor
margen (dias_a_quiebre - lead_time_dias). Aquí solo se consulta ordenado.
"""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.db import obtener_bd
from backend.app.fechas import fecha_larga

router = APIRouter(prefix="/api", tags=["Alertas"])

_ESTADOS_ALERTA = {"QUIEBRE", "REPONER", "EXCESO"}


@router.get("/alertas")
def listar_alertas(
    estado: Optional[str] = Query(None, description="QUIEBRE, REPONER o EXCESO"),
    atendida: Optional[int] = Query(None, ge=0, le=1, description="0 pendiente, 1 atendida"),
    bd: sqlite3.Connection = Depends(obtener_bd),
):
    """Cola de alertas ya priorizada, con costo estimado por fila y el
    total del pedido borrador (suma de cantidades sugeridas valorizadas).
    """
    if estado is not None and estado.upper() not in _ESTADOS_ALERTA:
        raise HTTPException(
            status_code=422,
            detail=f"Estado de alerta inválido: '{estado}'. Valores "
                   "permitidos: QUIEBRE, REPONER, EXCESO.")

    sql = """
        SELECT a.id, a.codigo_item, i.nombre,
               i.criticidad_ved   AS criticidad,
               a.estado, a.dias_a_quiebre,
               i.lead_time_dias,
               a.cantidad_sugerida, a.prioridad, a.fecha, a.atendida,
               i.costo_unitario
        FROM alertas a
        JOIN items i ON i.codigo = a.codigo_item
        WHERE 1 = 1
    """
    parametros = []
    if estado is not None:
        sql += " AND a.estado = ?"
        parametros.append(estado.upper())
    if atendida is not None:
        sql += " AND a.atendida = ?"
        parametros.append(atendida)
    sql += " ORDER BY a.prioridad"

    alertas = []
    total_pedido = 0.0
    for fila in bd.execute(sql, parametros):
        registro = dict(fila)
        # regla del proyecto: fechas dd-mmm-aaaa hacia el usuario
        registro["fecha"] = fecha_larga(registro["fecha"])
        registro["costo_estimado"] = round(
            fila["cantidad_sugerida"] * fila["costo_unitario"], 2)
        total_pedido += registro["costo_estimado"]
        alertas.append(registro)

    return {
        "total_alertas": len(alertas),
        "total_pedido_borrador": round(total_pedido, 2),
        "alertas": alertas,
    }
