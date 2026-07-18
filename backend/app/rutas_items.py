"""Rutas del catálogo de ítems de SARP-Naval.

El estado de cada ítem se deriva de la cola de alertas: los ítems sin
alerta están en estado OK. Los campos calculados por el motor (abc, xyz,
cv, valor de stock, días a quiebre) viven en la tabla auxiliar
`clasificacion` (ver esquema.sql).
"""

import sqlite3
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from backend.app.db import obtener_bd
from backend.app.fechas import etiqueta_mes, fecha_larga
from backend.motor import esencialidad as esn
from backend.motor.regimen import clasificar_regimen, resumen_regimen


def _serie_mensual(bd, codigo):
    """Serie mensual de consumo del ítem (huecos en 0), como analisis_real:
    del primer mes con consumo al último mes con movimiento registrado."""
    filas = bd.execute(
        """SELECT substr(fecha, 1, 7) AS mes, SUM(cantidad) AS total
           FROM movimientos WHERE codigo_item = ? AND tipo = 'consumo'
           GROUP BY mes ORDER BY mes""", (codigo,)).fetchall()
    if not filas:
        return []
    por_mes = {f["mes"]: f["total"] for f in filas}
    ini, fin = filas[0]["mes"], filas[-1]["mes"]
    a, m = int(ini[:4]), int(ini[5:7])
    fa, fm = int(fin[:4]), int(fin[5:7])
    serie = []
    while (a, m) <= (fa, fm):
        serie.append(float(por_mes.get(f"{a:04d}-{m:02d}", 0.0)))
        m += 1
        if m > 12:
            m = 1
            a += 1
    return serie


def _bloque_regimen(bd, codigo, criticidad):
    """Régimen de política + esencialidad de un ítem, para la ficha."""
    serie = _serie_mensual(bd, codigo)
    reg = clasificar_regimen(
        {"id": codigo, "hist": serie, "crit": criticidad,
         "mesesHistoria": len(serie)})
    # se reemplaza el código escueto por el bloque completo para la ficha
    reg["esencialidad"] = {
        "codigo": esn.codigo_de(codigo),
        "impide_operar": esn.impide_operar(codigo),
        "explicacion": esn.explicar(codigo),
    }
    return reg

router = APIRouter(prefix="/api", tags=["Ítems"])

_ESTADOS_VALIDOS = {"OK", "QUIEBRE", "REPONER", "EXCESO"}


@router.get("/items")
def listar_items(
    estado: Optional[str] = Query(None, description="OK, QUIEBRE, REPONER o EXCESO"),
    categoria: Optional[str] = Query(None, description="Categoría exacta del ítem"),
    abc: Optional[str] = Query(None, description="Clase ABC: A, B o C"),
    buscar: Optional[str] = Query(None, description="Subcadena en código o nombre"),
    bd: sqlite3.Connection = Depends(obtener_bd),
):
    """Lista resumida del catálogo, con filtros combinables."""
    if estado is not None and estado.upper() not in _ESTADOS_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail=f"Estado inválido: '{estado}'. Valores permitidos: "
                   "OK, QUIEBRE, REPONER, EXCESO.")

    sql = """
        SELECT i.codigo, i.nombre, i.categoria,
               i.criticidad_ved            AS criticidad,
               COALESCE(a.estado, 'OK')    AS estado,
               s.existencia,
               p.rop,
               c.dias_quiebre              AS dias_a_quiebre,
               c.valor_stock,
               c.abc
        FROM items i
        LEFT JOIN alertas a       ON a.codigo_item = i.codigo
        LEFT JOIN stock s         ON s.codigo_item = i.codigo
        LEFT JOIN parametros p    ON p.codigo_item = i.codigo
        LEFT JOIN clasificacion c ON c.codigo_item = i.codigo
        WHERE 1 = 1
    """
    parametros = []
    if estado is not None:
        sql += " AND COALESCE(a.estado, 'OK') = ?"
        parametros.append(estado.upper())
    if categoria is not None:
        sql += " AND i.categoria = ?"
        parametros.append(categoria)
    if abc is not None:
        sql += " AND c.abc = ?"
        parametros.append(abc.upper())
    if buscar is not None:
        # Se neutralizan los comodines LIKE (% y _) y la barra de escape
        # para que la búsqueda sea por subcadena LITERAL (sigue siendo
        # parametrizada: sin riesgo de inyección en ningún caso).
        literal = (buscar.replace("\\", "\\\\")
                         .replace("%", "\\%")
                         .replace("_", "\\_"))
        sql += (" AND (i.nombre LIKE ? ESCAPE '\\'"
                " OR i.codigo LIKE ? ESCAPE '\\')")
        patron = f"%{literal}%"
        parametros.extend([patron, patron])
    sql += " ORDER BY i.rowid"

    items = [dict(fila) for fila in bd.execute(sql, parametros)]
    return {"total": len(items), "items": items}


@router.get("/items/{codigo}")
def detalle_item(codigo: str, bd: sqlite3.Connection = Depends(obtener_bd)):
    """Detalle completo de un ítem: ficha, stock, parámetros, clasificación,
    pronóstico a 6 meses y serie histórica de 36 meses (desde movimientos).
    """
    ficha = bd.execute(
        "SELECT * FROM items WHERE codigo = ?", (codigo,)).fetchone()
    if ficha is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ítem '{codigo}' no encontrado en el catálogo SARP-Naval.")

    stock = bd.execute(
        """SELECT reparto, existencia, fecha_corte, ubicacion
           FROM stock WHERE codigo_item = ?""", (codigo,)).fetchone()

    parametros = bd.execute(
        """SELECT z_servicio, ss, rop, eoq, nivel_max, fecha_calculo,
                  version_modelo
           FROM parametros WHERE codigo_item = ?""", (codigo,)).fetchone()

    clasificacion = bd.execute(
        """SELECT abc, xyz, cv, valor_anual, valor_stock, dias_quiebre,
                  demanda_mensual
           FROM clasificacion WHERE codigo_item = ?""", (codigo,)).fetchone()

    # Estado derivado: sin alerta = OK
    alerta = bd.execute(
        """SELECT estado, dias_a_quiebre, cantidad_sugerida, prioridad
           FROM alertas WHERE codigo_item = ?""", (codigo,)).fetchone()

    pronostico = [dict(fila) for fila in bd.execute(
        """SELECT mes, demanda_prevista, sigma, mape, modelo
           FROM pronosticos WHERE codigo_item = ? ORDER BY rowid""",
        (codigo,))]

    historico = [
        {"mes": etiqueta_mes(fila["fecha"]),
         "fecha": fecha_larga(fila["fecha"]),
         "cantidad": fila["cantidad"]}
        for fila in bd.execute(
            """SELECT fecha, cantidad FROM movimientos
               WHERE codigo_item = ? AND tipo = 'consumo'
               ORDER BY fecha""", (codigo,))
    ]

    # regla del proyecto: fechas dd-mmm-aaaa hacia el usuario
    # (en la base se almacenan ISO yyyy-mm-dd)
    stock_salida = dict(stock) if stock else None
    if stock_salida:
        stock_salida["fecha_corte"] = fecha_larga(stock_salida["fecha_corte"])
    parametros_salida = dict(parametros) if parametros else None
    if parametros_salida:
        parametros_salida["fecha_calculo"] = fecha_larga(
            parametros_salida["fecha_calculo"])

    return {
        "item": dict(ficha),
        "estado": alerta["estado"] if alerta else "OK",
        "alerta": dict(alerta) if alerta else None,
        "stock": stock_salida,
        "parametros": parametros_salida,
        "clasificacion": dict(clasificacion) if clasificacion else None,
        "pronostico": pronostico,
        "historico": historico,
        "regimen": _bloque_regimen(bd, codigo, ficha["criticidad_ved"]),
    }


@router.get("/regimen")
def resumen_regimen_catalogo(bd: sqlite3.Connection = Depends(obtener_bd)):
    """Resumen del selector de régimen sobre el catálogo completo:
    cuántos ítems entran al modelo de alistamiento, qué porcentaje del
    gasto anual cubren y la distribución de patrones de demanda (SBC),
    más la calibración de esencialidad contra la banda publicada.
    """
    fichas = bd.execute(
        """SELECT i.codigo, i.criticidad_ved, c.valor_anual
           FROM items i LEFT JOIN clasificacion c
             ON c.codigo_item = i.codigo""").fetchall()
    clasificados = []
    for f in fichas:
        reg = _bloque_regimen(bd, f["codigo"], f["criticidad_ved"])
        reg["codigo_item"] = f["codigo"]
        reg["valorAnual"] = f["valor_anual"] or 0.0
        clasificados.append(reg)
    resumen = resumen_regimen(clasificados)
    resumen["calibracion_esencialidad"] = esn.verificar_calibracion(
        [f["codigo"] for f in fichas])
    resumen["items"] = [
        {"codigo": r["codigo_item"], "regimen": r["regimen"],
         "patron": r["patron"], "adi": r["adi"], "cv2": r["cv2"],
         "elegible_rbs": r["elegible_rbs"],
         "impide_operar": r["esencialidad"]["impide_operar"]}
        for r in clasificados
    ]
    return resumen
