"""SIPAO-Naval · API del módulo de costeo de operación (COGUAR), v3.

GET  /api/costeo                  — matriz completa (precomputada)
GET  /api/costeo/catalogo         — TIPO → MODELO → UNIDAD
GET  /api/costeo/rubros/{modelo}  — desglose del día de mar por rubros
GET  /api/costeo/escalera         — escalera marginal unificada
GET  /api/costeo/ficha/{modelo}   — ficha logística digital del modelo

Puentes REALES con el módulo de abastecimiento (SARP):
1. El alistamiento del optimizador de repuestos entra como factor A_c y
   reduce los días de mar entregables. Precedente público: GAO-25-107222
   (FY2024, 594 días-cutter perdidos por demoras de repuestos, USCG).
2. El rubro «repuestos críticos» de la tarifa puede venir del PRONÓSTICO
   del propio motor (Holt/Croston × costo unitario ÷ días entregables)
   en vez de un valor referencial.
"""

import sqlite3

from fastapi import APIRouter, Depends, HTTPException

from backend.app.db import obtener_bd
from backend.app.rutas_alistamiento import _elegibles
from backend.motor.alistamiento import alistamiento_conjunto, optimizar
from backend.motor.costeo import (MODELOS, UNIDADES, catalogo_unidades,
                                  escalera_conjunta, ficha_modelo,
                                  matriz_costeo, presupuesto_para_plan,
                                  rubros_modelo)

router = APIRouter(prefix="/api", tags=["costeo"])

# El catálogo de repuestos del demostrador representa el material crítico
# de las unidades principales; el puente se declara sobre el tipo con más
# unidades en servicio.
TIPO_PUENTE = "PGM"


def _alistamiento(bd):
    """A_c del tipo puente = alistamiento de repuestos del catálogo.
    Sale del mismo motor que sirve /api/alistamiento."""
    items, _ = _elegibles(bd)
    if not items:
        return None
    niveles = [it["rop"] for it in items]
    return {TIPO_PUENTE: round(alistamiento_conjunto(items, niveles), 4)}


def _repuestos_dia(bd, a_c):
    """Rubro A4 pronosticado por SARP: demanda anual prevista valorizada
    ÷ días de mar entregables del tipo puente al alistamiento actual."""
    fila = bd.execute(
        """SELECT SUM(p.demanda_prevista * i.costo_unitario)
           FROM pronosticos p JOIN items i ON i.codigo = p.codigo_item"""
    ).fetchone()
    total_6m = fila[0] if fila and fila[0] else None
    if not total_6m:
        return None
    anual = total_6m * 2.0
    modelos = [c for c, m in MODELOS.items() if m["tipo"] == TIPO_PUENTE]
    dias = sum(MODELOS[c]["dias_operables"]
               * len([u for u in UNIDADES if u["modelo"] == c])
               for c in modelos) * max(0.05, a_c or 1.0)
    if dias <= 0:
        return None
    return {c: round(anual / dias, 2) for c in modelos}


@router.get("/costeo")
def costeo(bd: sqlite3.Connection = Depends(obtener_bd)):
    alist = _alistamiento(bd)
    a_c = (alist or {}).get(TIPO_PUENTE)
    reps = _repuestos_dia(bd, a_c)
    m = matriz_costeo(alistamiento=alist, repuestos_dia=reps)
    m["puente_alistamiento"] = {
        "tipo": TIPO_PUENTE,
        "a_c": a_c,
        "repuestos_dia_pronosticado": reps,
        "nota": ("El alistamiento del material crítico fija los días de mar "
                 "que el tipo puede entregar, y el rubro de repuestos de su "
                 "tarifa lo pronostica el propio motor de abastecimiento; los "
                 "demás tipos usan valores referenciales configurables."),
    }
    return m


@router.get("/costeo/catalogo")
def catalogo():
    return catalogo_unidades()


@router.get("/costeo/rubros/{modelo}")
def rubros(modelo: str, bd: sqlite3.Connection = Depends(obtener_bd)):
    modelo = modelo.upper()
    if modelo not in MODELOS:
        raise HTTPException(404, f"Modelo desconocido: {modelo}")
    alist = _alistamiento(bd)
    reps = _repuestos_dia(bd, (alist or {}).get(TIPO_PUENTE)) or {}
    return rubros_modelo(modelo, repuestos_dia=reps.get(modelo))


@router.get("/costeo/escalera")
def escalera(bd: sqlite3.Connection = Depends(obtener_bd)):
    """Escalera marginal unificada en un escenario de alistamiento
    degradado: los pasos de repuestos son REALES (frontera del optimizador
    sobre el catálogo); el estado degradado es un escenario configurable."""
    items, _ = _elegibles(bd)
    plan = presupuesto_para_plan()["operativo_minimo"]
    presupuesto = round(plan * 0.6, 2)
    base = {TIPO_PUENTE: 0.15}
    pasos = []
    if items:
        presupuesto_rbs = sum(it["rop"] * it["costo"] for it in items)
        _, _, vertices = optimizar(items, presupuesto_rbs)
        previos = [(g, a) for g, a in vertices if a > base[TIPO_PUENTE]]
        for (g0, a0), (g1, a1) in zip(previos, previos[1:]):
            if g1 > g0 and a1 > a0:
                pasos.append({"costo": round(g1 - g0, 2),
                              "delta_a": round(a1 - a0, 6)})
        pasos = pasos[:120]
    e = escalera_conjunta(presupuesto, pasos_repuestos=pasos,
                          alistamiento_base=base)
    return {"escenario": {"nombre": ("Recorte del 40 % con alistamiento "
                                     "degradado (escenario configurable)"),
                          "alistamiento_base": base},
            "pasos_disponibles": len(pasos), "escalera": e}


@router.get("/costeo/ficha/{modelo}")
def ficha(modelo: str, bd: sqlite3.Connection = Depends(obtener_bd)):
    modelo = modelo.upper()
    if modelo not in MODELOS:
        raise HTTPException(404, f"Modelo desconocido: {modelo}")
    alist = _alistamiento(bd)
    a_c = (alist or {}).get(MODELOS[modelo]["tipo"])
    reps = _repuestos_dia(bd, a_c) or {}
    return ficha_modelo(modelo, a_c=a_c, repuestos_dia=reps.get(modelo))
