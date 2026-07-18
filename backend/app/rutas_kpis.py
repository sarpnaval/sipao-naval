"""Rutas de indicadores (KPIs) de SARP-Naval.

Los KPIs se calculan con SQL sobre las tablas locales (stock, parametros,
alertas, clasificacion), sin volver a invocar el motor: los números deben
cuadrar exactamente con lo sembrado por backend.app.seed.
"""

import math
import sqlite3

from fastapi import APIRouter, Depends

from backend.app.db import obtener_bd

router = APIRouter(prefix="/api", tags=["KPIs"])


def _redondear_js(valor):
    """Redondeo a entero equivalente a Math.round de JavaScript (0.5 sube).

    No usa floor(valor + 0.5): esa suma redondea mal cuando valor + 0.5
    no es representable en IEEE-754 (mismo criterio que motor.redondeo_js).
    """
    piso = math.floor(valor)
    return piso + 1 if valor - piso >= 0.5 else piso


def _entero_si_exacto(valor):
    """Devuelve int si el flotante es (casi) entero; el flotante si no."""
    if abs(valor - round(valor)) < 1e-9:
        return int(round(valor))
    return valor


@router.get("/kpis")
def leer_kpis(bd: sqlite3.Connection = Depends(obtener_bd)):
    """Bloque completo de KPIs del tablero, calculado desde la base local."""
    n_items = bd.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]

    # Conteos por estado desde la cola de alertas (los OK no tienen alerta)
    conteos = {"QUIEBRE": 0, "REPONER": 0, "EXCESO": 0}
    for fila in bd.execute(
            "SELECT estado, COUNT(*) AS n FROM alertas GROUP BY estado"):
        conteos[fila["estado"]] = fila["n"]

    # Capital valorizado (sumas de valores por ítem ya redondeados)
    fila = bd.execute(
        """SELECT COALESCE(SUM(valor_stock), 0) AS capital,
                  COALESCE(SUM(valor_anual), 0) AS anual
           FROM clasificacion""").fetchone()
    capital_stock = fila["capital"]
    valor_anual_demanda = fila["anual"]

    # Capital en exceso: sobre-stock por encima del nivel máximo, valorizado.
    # Se suma en orden de catálogo para replicar el cálculo del motor.
    capital_exceso = 0.0
    for f in bd.execute(
            """SELECT s.existencia, p.nivel_max, i.costo_unitario
               FROM alertas a
               JOIN items i      ON i.codigo = a.codigo_item
               JOIN stock s      ON s.codigo_item = a.codigo_item
               JOIN parametros p ON p.codigo_item = a.codigo_item
               WHERE a.estado = 'EXCESO'
               ORDER BY i.rowid"""):
        capital_exceso += max(0.0, f["existencia"] - f["nivel_max"]) * f["costo_unitario"]

    # Ítems vitales en riesgo (quiebre o bajo punto de reorden)
    criticos_riesgo = bd.execute(
        """SELECT COUNT(*) AS n
           FROM alertas a JOIN items i ON i.codigo = a.codigo_item
           WHERE i.criticidad_ved = 'V'
             AND a.estado IN ('QUIEBRE', 'REPONER')""").fetchone()["n"]

    # Alistamiento estimado de las unidades de la familia ancla: proxy según vitales en quiebre
    vitales_quiebre = bd.execute(
        """SELECT COUNT(*) AS n
           FROM alertas a JOIN items i ON i.codigo = a.codigo_item
           WHERE i.criticidad_ved = 'V' AND a.estado = 'QUIEBRE'""").fetchone()["n"]
    disponibilidad = max(60, _redondear_js(94 - vitales_quiebre * 4.5))

    # Ahorro potencial: 50% del capital en exceso + 3% de la demanda anual
    ahorro_potencial = _redondear_js(
        capital_exceso * 0.5 + valor_anual_demanda * 0.03)

    metadatos = {f["clave"]: f["valor"]
                 for f in bd.execute("SELECT clave, valor FROM metadatos")}

    return {
        "nItems": n_items,
        "quiebres": conteos["QUIEBRE"],
        "reponer": conteos["REPONER"],
        "excesos": conteos["EXCESO"],
        "capitalStock": capital_stock,
        "capitalExceso": _entero_si_exacto(capital_exceso),
        "valorAnualDemanda": valor_anual_demanda,
        "criticosRiesgo": criticos_riesgo,
        "disponibilidad": disponibilidad,
        "ahorroPotencial": ahorro_potencial,
        "generado": metadatos.get("generado"),
        "reparto": metadatos.get("reparto"),
    }
