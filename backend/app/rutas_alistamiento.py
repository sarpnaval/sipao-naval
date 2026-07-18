"""SARP-Naval · API del optimizador de alistamiento operativo.

GET /api/alistamiento — todo precomputado y sin parámetros, para que la
misma respuesta sirva en vivo y en la demo estática (site-fase2):

- la frontera declarada (cuántos ítems entran al modelo y por qué),
- el presupuesto base (los ROP vigentes del motor clásico valorizados),
- la curva presupuesto→alistamiento (envolvente eficiente completa),
- la tabla de recortes: reparto lineal vs optimizado al mismo dinero,
- el plan por ítem con el nivel de servicio RESULTANTE (el output que
  antes era un input decretado por z-según-VED).
"""

import sqlite3

from fastapi import APIRouter, Depends

from backend.app.db import obtener_bd
from backend.app.rutas_items import _bloque_regimen
from backend.motor.alistamiento import (
    alistamiento_conjunto,
    comparar_recortes,
    curva_presupuesto,
    optimizar,
    ready_rate_qr,
)

router = APIRouter(prefix="/api", tags=["alistamiento"])


def _elegibles(bd):
    """Ítems que entran al modelo (frontera del selector de régimen)."""
    filas = bd.execute(
        """SELECT i.codigo, i.nombre, i.criticidad_ved, i.costo_unitario,
                  i.lead_time_dias, c.demanda_mensual, p.eoq, p.rop
           FROM items i
           JOIN clasificacion c ON c.codigo_item = i.codigo
           JOIN parametros p ON p.codigo_item = i.codigo
           ORDER BY i.codigo""").fetchall()
    elegibles, total = [], 0
    for f in filas:
        total += 1
        reg = _bloque_regimen(bd, f["codigo"], f["criticidad_ved"])
        if not reg["elegible_rbs"]:
            continue
        elegibles.append({
            "codigo": f["codigo"],
            "nombre": f["nombre"],
            "lam": float(f["demanda_mensual"] or 0.0),
            "lt_meses": max(0.25, f["lead_time_dias"] / 30.0),
            "costo": float(f["costo_unitario"]),
            "eoq": int(f["eoq"] or 1),
            "rop": int(f["rop"] or 0),
        })
    return elegibles, total


@router.get("/alistamiento")
def alistamiento(bd: sqlite3.Connection = Depends(obtener_bd)):
    items, total = _elegibles(bd)
    if not items:
        return {"elegibles": 0, "total_items": total, "curva": [],
                "recortes": None, "plan": [],
                "frontera": ("Ningún ítem del catálogo entra al modelo de "
                             "alistamiento (esencialidad 1 + historia "
                             "suficiente).")}

    niveles_actuales = [it["rop"] for it in items]
    a_actual = alistamiento_conjunto(items, niveles_actuales)
    base = sum(it["costo"] * r
               for it, r in zip(items, niveles_actuales))

    recortes = comparar_recortes(items, niveles_actuales)
    curva = curva_presupuesto(items, base * 1.2)
    niveles_opt, gasto_opt, _ = optimizar(items, base)
    # el plan que DIFERENCIA: la asignación optimizada bajo recorte del
    # 20 % — ahí se ve que el nivel de servicio es un output distinto
    # por ítem, no el 95 % decretado igual para todos
    niveles_r20, _, _ = optimizar(items, base * 0.8)

    plan = []
    for it, r_act, r_opt, r_20 in zip(items, niveles_actuales,
                                      niveles_opt, niveles_r20):
        m = it["lam"] * it["lt_meses"]
        plan.append({
            "codigo": it["codigo"],
            "nombre": it["nombre"],
            "costo": it["costo"],
            "rop_actual": r_act,
            "r_optimo": r_opt,
            "r_recorte20": r_20,
            "servicio_actual": round(
                100 * ready_rate_qr(r_act, it["eoq"], m), 1),
            "servicio_optimo": round(
                100 * ready_rate_qr(r_opt, it["eoq"], m), 1),
            "servicio_recorte20": round(
                100 * ready_rate_qr(r_20, it["eoq"], m), 1),
        })
    plan.sort(key=lambda x: -x["costo"])

    return {
        "elegibles": len(items),
        "total_items": total,
        "frontera": (f"{len(items)} de {total} ítems entran al modelo "
                     "(su falta impide operar y su demanda es estimable); "
                     "el resto se gestiona por EOQ/ROP clásico."),
        "presupuesto_base": round(base, 2),
        "alistamiento_actual": round(a_actual, 4),
        "gasto_optimizado": round(gasto_opt, 2),
        "curva": [[round(g, 2), round(a, 4)] for g, a in curva],
        "recortes": recortes,
        "plan": plan,
    }
