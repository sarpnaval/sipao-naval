"""Ruta de validación estadística del pronóstico (tarea 2.2c).

GET /api/validacion?t0=&horizonte= corre un backtesting de origen móvil
(backend.motor.backtesting) sobre el dataset ACTUAL de la base local y
devuelve, en español, el MAPE de la clase A regular y el porcentaje de
ítems intermitentes con MASE < 1: las dos cifras que hacen medible el
KPI de exactitud comprometido.

La ruta SOLO evalúa el pronóstico: reconstruye las series mensuales por
ítem a partir de los movimientos de consumo (igual que el análisis real)
y NO recalcula parámetros de inventario ni escribe en la base. Como todo
el aplicativo, es de solo lectura respecto a SISLOG.
"""

import sqlite3
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.db import obtener_bd
from backend.motor.backtesting import (
    HORIZONTE_POR_DEFECTO,
    T0_POR_DEFECTO,
    UMBRAL_INTERMITENCIA,
    backtest_dataset,
)

router = APIRouter(prefix="/api", tags=["Validación"])

# Límites de los parámetros del backtest (documentados en los mensajes
# de error). t0 >= 12: al menos un año de entrenamiento antes del primer
# pronóstico. horizonte 1..6: hasta el horizonte de pronóstico de la app.
T0_MINIMO = 12
HORIZONTE_MINIMO = 1
HORIZONTE_MAXIMO = 6

_NOTA_METODOLOGICA = (
    "Backtesting de origen móvil (rolling-origin): para cada ítem se "
    "entrena el modelo con los primeros t meses y se pronostica el "
    "horizonte h=1..H, avanzando el origen t desde t0 hasta el final de "
    "la serie, sin usar datos posteriores al origen (sin fuga temporal). "
    "La demanda intermitente (>= "
    f"{int(UMBRAL_INTERMITENCIA * 100)}% de meses en cero) se pronostica "
    "con Croston y su exactitud se mide con MASE (error escalado por el "
    "pronóstico ingenuo naïve-1; MASE<1 = mejor que ingenuo), válido con "
    "ceros. La demanda regular se pronostica con Holt y se mide con MAPE "
    "(%); el MAPE no aplica a series con meses en cero porque dividiría "
    "por cero (Hyndman & Koehler, 2006). El MAPE de clase A regular se "
    "pondera por el número de evaluaciones (equivale al MAPE agrupado). "
    "Nota: el modelo por ítem se deriva de la SERIE observada (igual que "
    "en datos reales); en el demo simulado algunos ítems de frontera se "
    "muestran con Croston por el flag del catálogo aunque aquí, por tener "
    "menos del 40% de meses en cero, se validen como regulares con Holt."
)


def _indice_mes(fecha_iso):
    """Índice absoluto del mes de una fecha ISO yyyy-mm-dd (año*12+mes-1)."""
    return int(fecha_iso[0:4]) * 12 + int(fecha_iso[5:7]) - 1


def _reconstruir_series(bd):
    """Reconstruye la serie mensual de consumo por ítem desde la base.

    Igual criterio que backend.motor.analisis_real: se agregan por mes
    calendario los movimientos de tipo 'consumo'; la serie de cada ítem
    va de su PRIMER mes con consumo al ÚLTIMO mes del rango global de
    movimientos, con los meses intermedios sin consumo contados como 0.
    Devuelve una lista de dicts {codigo, crit, abc, serie} en orden de
    catálogo (i.rowid).
    """
    # Rango global: último mes con cualquier movimiento registrado.
    fila = bd.execute("SELECT MAX(fecha) AS f FROM movimientos").fetchone()
    if fila is None or fila["f"] is None:
        return []
    idx_fin_global = _indice_mes(fila["f"])

    # Consumo mensual por ítem (solo tipo 'consumo'; SQL parametrizado).
    consumo = defaultdict(lambda: defaultdict(float))
    for mov in bd.execute(
            "SELECT codigo_item, fecha, cantidad FROM movimientos "
            "WHERE tipo = ?", ("consumo",)):
        consumo[mov["codigo_item"]][_indice_mes(mov["fecha"])] += \
            mov["cantidad"]

    items = []
    for ficha in bd.execute(
            "SELECT i.codigo, i.criticidad_ved AS crit, c.abc AS abc "
            "FROM items i "
            "LEFT JOIN clasificacion c ON c.codigo_item = i.codigo "
            "ORDER BY i.rowid"):
        cons = consumo.get(ficha["codigo"], {})
        if cons:
            idx_ini = min(cons)
            serie = [cons.get(i, 0.0)
                     for i in range(idx_ini, idx_fin_global + 1)]
        else:
            serie = []
        items.append({
            "codigo": ficha["codigo"],
            "crit": ficha["crit"],
            "abc": ficha["abc"],
            "serie": serie,
        })
    return items


@router.get("/validacion")
def validar_pronostico(
    t0: int = Query(
        T0_POR_DEFECTO,
        description="Origen inicial: meses de entrenamiento antes del "
                    f"primer pronóstico (>= {T0_MINIMO})."),
    horizonte: int = Query(
        HORIZONTE_POR_DEFECTO,
        description="Pasos a evaluar en cada origen "
                    f"({HORIZONTE_MINIMO}..{HORIZONTE_MAXIMO})."),
    bd: sqlite3.Connection = Depends(obtener_bd),
):
    """Backtesting de origen móvil sobre el dataset cargado.

    Devuelve {resumen, por_clase, por_item, parametros, nota_metodologica}
    con el MAPE de clase A regular y el % de intermitentes con MASE<1.
    """
    if t0 < T0_MINIMO:
        raise HTTPException(
            status_code=422,
            detail=f"Parámetro 't0' inválido: {t0}. Debe ser >= "
                   f"{T0_MINIMO} (al menos un año de entrenamiento antes "
                   "del primer pronóstico).")
    if not (HORIZONTE_MINIMO <= horizonte <= HORIZONTE_MAXIMO):
        raise HTTPException(
            status_code=422,
            detail=f"Parámetro 'horizonte' inválido: {horizonte}. Debe "
                   f"estar entre {HORIZONTE_MINIMO} y {HORIZONTE_MAXIMO}.")

    items = _reconstruir_series(bd)
    if not items:
        raise HTTPException(
            status_code=409,
            detail="No hay datos cargados para validar: la base no tiene "
                   "movimientos de consumo. Siembre o importe un dataset "
                   "antes de correr la validación.")

    resultado = backtest_dataset(items, t0=t0, horizonte=horizonte)
    resultado["parametros"] = {"t0": t0, "horizonte": horizonte}
    resultado["nota_metodologica"] = _NOTA_METODOLOGICA
    return resultado
