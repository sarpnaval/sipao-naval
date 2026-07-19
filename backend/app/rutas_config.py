"""SIPAO-Naval · API del panel de configuración.

Convierte la plataforma de demostrador en sistema institucional: todo
parámetro que hoy trae un VALOR REFERENCIAL puede ser reemplazado por el
reparto sin tocar código.

GET  /api/config                — configuración completa con su procedencia
GET  /api/config/impacto        — vista previa del efecto de un cambio
POST /api/config                — guarda cambios (con motivo y bitácora)
POST /api/config/restaurar      — vuelve a los valores referenciales

PROCEDENCIA DE CADA PARÁMETRO (`origen`), inspirada en la exigencia de
trazabilidad de costos de la GAO (GAO-20-195G):
    referencial   — valor de arranque provisto por el sistema
    literatura    — respaldo bibliográfico (su valor correcto ES este)
    institucional — cargado de un documento de la institución
    medido        — tomado de bitácoras/horómetros propios
    estimado      — juicio del configurador

El índice de madurez se publica como VECTOR (no un escalar): distingue
lo cargado institucionalmente de lo que sigue siendo valor de fábrica.
Los parámetros de tipo `literatura` no cuentan como pendientes: su valor
correcto es el referencial y exigir su reemplazo crearía un incentivo a
etiquetarlos falsamente, corrompiendo el propio campo de procedencia.
"""

import copy
import json
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.app import config_persistente, respaldo, seguridad
from backend.app.db import obtener_bd
from backend.motor import costeo

router = APIRouter(prefix="/api/config", tags=["configuracion"])

ORIGENES = ("referencial", "literatura", "institucional", "medido", "estimado")

# Instantánea de los valores de fábrica, para poder restaurar.
_FABRICA = {
    "parametros": copy.deepcopy(costeo.PARAMETROS),
    "modelos": copy.deepcopy(costeo.MODELOS),
    "operaciones": copy.deepcopy(costeo.OPERACIONES),
    "tipos": copy.deepcopy(costeo.TIPOS),
}


class CambioConfig(BaseModel):
    seccion: str = Field(..., description="parametros | modelos | operaciones | tipos")
    clave: str = Field(..., description="parámetro, modelo, operación o tipo")
    campo: str = Field(..., description="campo a modificar")
    valor: float | str | None = None
    origen: str | None = None
    fuente: str | None = None


class GuardarConfig(BaseModel):
    cambios: list[CambioConfig]
    motivo: str = Field(..., min_length=3,
                        description="por qué se cambia (queda en bitácora)")
    responsable: str = Field("", description="grado y nombre de quien firma")


# ---------------------------------------------------------------- lectura
def _indicadores():
    """Los seis indicadores de mando que se muestran antes/después."""
    inv = costeo.presupuesto_para_plan()
    pleno = costeo.simular_cobertura(inv["operativo_minimo"], priorizado=True)
    insignia = max(costeo.OPERACIONES,
                   key=lambda o: costeo.OPERACIONES[o]["peso"])
    return {
        "presupuesto_operativo_plan": inv["operativo_minimo"],
        "costo_fijo_anual": inv["costo_fijo_contexto"],
        "dias_de_mar_del_plan": sum(pleno["dias_por_clase"].values()),
        "cobertura_ponderada": pleno["cobertura_ponderada"],
        "cobertura_vida_humana": pleno["operaciones"][insignia]["cobertura"],
        "tipos_bajo_presencia_minima": len(pleno["unidades_bajo_minimo"]),
    }


def _madurez():
    """Vector de procedencia sobre los parámetros de contexto local."""
    conteo = {o: 0 for o in ORIGENES}
    total = 0
    for p in costeo.PARAMETROS.values():
        conteo[p.get("origen", "referencial")] += 1
        total += 1
    for m in costeo.MODELOS.values():
        conteo[m.get("origen", "referencial")] += 1
        total += 1
    local = total - conteo["literatura"]          # la literatura no es pendiente
    cargados = conteo["institucional"] + conteo["medido"]
    return {
        "vector": conteo, "total": total,
        "pct_institucional_o_medido": round(100 * cargados / max(1, local), 1),
        "pendientes": [
            *[f"parámetro: {p['etiqueta']}" for k, p in costeo.PARAMETROS.items()
              if p.get("origen") in ("referencial", "estimado")],
            *[f"modelo: {m['nombre']}" for m in costeo.MODELOS.values()
              if m.get("origen") in ("referencial", "estimado")],
        ],
        "nota": ("Los parámetros con respaldo bibliográfico no cuentan como "
                 "pendientes: su valor correcto es el que trae el sistema."),
    }


@router.get("")
def leer_configuracion():
    return {
        "parametros": costeo.PARAMETROS,
        "modelos": {c: {
            "nombre": m["nombre"], "tipo": m["tipo"],
            "constructor": m["constructor"], "origen": m["origen"],
            "eslora_m": m["eslora_m"], "tripulacion": m["tripulacion"],
            "dias_operables": m["dias_operables"],
            "mantto_prev_usd_h": m["mantto_prev_usd_h"],
            "repuestos_usd_dia": m["repuestos_usd_dia"],
            "perfil_dia": m["perfil_dia"], "consumo_gal_h": m["consumo_gal_h"],
            "fijos": m["fijos"], "nota": m["nota"],
            "unidades": [u for u in costeo.UNIDADES if u["modelo"] == c],
        } for c, m in costeo.MODELOS.items()},
        "operaciones": {o: {
            "nombre": od["nombre"], "peso": od["peso"],
            "min_dias": od["min_dias"], "req_dias": od["req_dias"],
            "clases": od["clases"], "responde_a": od["responde_a"],
        } for o, od in costeo.OPERACIONES.items()},
        "tipos": {t: {
            "denominacion": d["denominacion"], "es_principal": d["es_principal"],
            "base_costeo": d["base_costeo"], "presencia_min": d["presencia_min"],
            "op_presencia": d["op_presencia"], "ambito": d["ambito"],
        } for t, d in costeo.TIPOS.items()},
        "origenes": list(ORIGENES),
        "indicadores": _indicadores(),
        "madurez": _madurez(),
        # Estado del respaldo automático. Antes solo se veía DESPUÉS de
        # guardar, que es tarde: quien va a cargar datos necesita saber
        # ANTES si lo que escriba sobrevivirá al reinicio de la instancia.
        "respaldo": respaldo.estado(),
        # Si la instancia exige clave para escribir (publicada) o no (local).
        "escritura_protegida": seguridad.escritura_protegida(),
    }


# --------------------------------------------------------------- escritura
def _aplicar(cambio: CambioConfig):
    """Aplica un cambio al motor. Devuelve (anterior, nuevo) o lanza 400."""
    s, k, campo = cambio.seccion, cambio.clave, cambio.campo
    if cambio.origen and cambio.origen not in ORIGENES:
        raise HTTPException(400, f"Origen inválido: {cambio.origen}")

    if s == "parametros":
        if k not in costeo.PARAMETROS:
            raise HTTPException(404, f"Parámetro desconocido: {k}")
        p = costeo.PARAMETROS[k]
        antes = p["valor"]
        if cambio.valor is not None:
            v = float(cambio.valor)
            if v < 0:
                raise HTTPException(400, f"{k}: no admite valores negativos")
            p["valor"] = v
        if cambio.origen:
            p["origen"] = cambio.origen
        if cambio.fuente is not None:
            p["fuente"] = cambio.fuente
        return antes, p["valor"]

    if s == "modelos":
        if k not in costeo.MODELOS:
            raise HTTPException(404, f"Modelo desconocido: {k}")
        m = costeo.MODELOS[k]
        if campo in ("dias_operables", "tripulacion", "mantto_prev_usd_h",
                     "repuestos_usd_dia", "eslora_m", "potencia_hp"):
            antes = m[campo]
            v = float(cambio.valor)
            if campo == "dias_operables" and not (0 < v <= 365):
                raise HTTPException(400, "Días operables debe estar entre 1 y 365")
            m[campo] = v
        elif campo.startswith("consumo_gal_h."):
            reg = campo.split(".", 1)[1]
            antes = m["consumo_gal_h"].get(reg)
            m["consumo_gal_h"][reg] = float(cambio.valor)
        elif campo.startswith("perfil_dia."):
            reg = campo.split(".", 1)[1]
            antes = m["perfil_dia"].get(reg)
            v = float(cambio.valor)
            otras = sum(h for r, h in m["perfil_dia"].items() if r != reg)
            if otras + v > 24:
                raise HTTPException(400, "El perfil del día no puede pasar de 24 h")
            m["perfil_dia"][reg] = v
        elif campo.startswith("fijos."):
            rubro = campo.split(".", 1)[1]
            antes = m["fijos"].get(rubro)
            m["fijos"][rubro] = float(cambio.valor)
        else:
            raise HTTPException(400, f"Campo no configurable: {campo}")
        if cambio.origen:
            m["origen"] = cambio.origen
        return antes, cambio.valor

    if s == "operaciones":
        if k not in costeo.OPERACIONES:
            raise HTTPException(404, f"Operación desconocida: {k}")
        od = costeo.OPERACIONES[k]
        if campo not in ("peso", "min_dias", "req_dias"):
            raise HTTPException(400, f"Campo no configurable: {campo}")
        antes = od[campo]
        v = float(cambio.valor)
        if v < 0:
            raise HTTPException(400, f"{campo}: no admite valores negativos")
        od[campo] = v if campo == "peso" else int(v)
        if od["min_dias"] > od["req_dias"]:
            od[campo] = antes
            raise HTTPException(
                400, "Los días mínimos no pueden superar los del plan")
        return antes, od[campo]

    if s == "tipos":
        if k not in costeo.TIPOS:
            raise HTTPException(404, f"Tipo desconocido: {k}")
        t = costeo.TIPOS[k]
        if campo != "presencia_min":
            raise HTTPException(400, f"Campo no configurable: {campo}")
        antes = t["presencia_min"]
        v = int(float(cambio.valor))
        # V4 por clase: la presencia no puede exceder la capacidad del tipo
        clases = costeo._clases_operativas()
        if k in clases and v > clases[k]["dias_entregables"]:
            raise HTTPException(
                400, f"{k}: la presencia mínima ({v} días) supera la capacidad "
                     f"de la clase ({clases[k]['dias_entregables']:.0f} días)")
        t["presencia_min"] = v
        return antes, v

    raise HTTPException(400, f"Sección desconocida: {s}")


@router.post("/impacto")
def previsualizar(cambios: list[CambioConfig]):
    """Vista previa: aplica los cambios, mide los indicadores y REVIERTE.
    El oficial ve el efecto antes de confirmar (patrón «revisar antes de
    guardar»: reduce errores al dar una segunda oportunidad de notarlos)."""
    antes = _indicadores()
    # NOTA: no llamar a esta variable "respaldo": taparia al modulo del
    # mismo nombre importado arriba (colision detectada el 18-jul-2026).
    instantanea = {s: copy.deepcopy(getattr(costeo, s.upper()))
                   for s in ("parametros", "modelos", "operaciones", "tipos")}
    try:
        detalle = []
        for c in cambios:
            a, n = _aplicar(c)
            detalle.append({"seccion": c.seccion, "clave": c.clave,
                            "campo": c.campo, "antes": a, "despues": n})
        costeo._refrescar_clases()
        despues = _indicadores()
    finally:
        for s, valor in instantanea.items():
            getattr(costeo, s.upper()).clear()
            getattr(costeo, s.upper()).update(valor)
        costeo._refrescar_clases()
    return {"cambios": detalle, "antes": antes, "despues": despues,
            "delta": {k: round(despues[k] - antes[k], 4)
                      for k in antes if isinstance(antes[k], (int, float))}}


@router.post("")
def guardar(cuerpo: GuardarConfig, bd: sqlite3.Connection = Depends(obtener_bd)):
    """Guarda los cambios y deja una fila de bitácora por parámetro
    tocado (valor previo, valor nuevo, responsable y motivo)."""
    if not cuerpo.cambios:
        raise HTTPException(400, "No hay cambios que guardar")
    antes = _indicadores()

    # TODO O NADA (corregido el 18-jul-2026)
    # ---------------------------------------
    # Antes se aplicaban los cambios uno por uno sin red: si el tercero de
    # cinco violaba una validación, la API respondía 400 y la pantalla decía
    # «no se guardó» — pero los dos primeros YA estaban aplicados en el
    # estado global del proceso. Desde ese instante el tablero de mando
    # servía cifras que nadie autorizó, a todos los usuarios a la vez, sin
    # una sola fila de bitácora y sin nada persistido: al reiniciar
    # desaparecía el rastro. Se midió un caso con el presupuesto del plan
    # inflado un 34 % tras un guardado RECHAZADO.
    #
    # El endpoint hermano /impacto ya usaba este patrón; el que escribe de
    # verdad, que es el que importa, no lo tenía.
    instantanea = {s: copy.deepcopy(getattr(costeo, s.upper()))
                   for s in ("parametros", "modelos", "operaciones", "tipos")}
    try:
        aplicados = []
        for c in cuerpo.cambios:
            a, n = _aplicar(c)
            aplicados.append({"seccion": c.seccion, "clave": c.clave,
                              "campo": c.campo, "antes": a, "despues": n,
                              "origen": c.origen, "fuente": c.fuente})
        costeo._refrescar_clases()
        despues = _indicadores()

        ahora = datetime.now().isoformat(timespec="seconds")
        # PERSISTIR el valor efectivo: sin esto, al reiniciar el sistema los
        # parámetros volverían a fábrica y la bitácora quedaría mintiendo.
        for x in aplicados:
            config_persistente.guardar_valor(
                bd, x["seccion"], x["clave"], x["campo"], x["despues"],
                origen=x.get("origen"), fuente=x.get("fuente"))
        for x in aplicados:
            bd.execute(
                """INSERT INTO configuracion_bitacora
                   (fecha_hora, seccion, clave, campo, valor_previo, valor_nuevo,
                    origen, fuente, motivo, responsable)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (ahora, x["seccion"], x["clave"], x["campo"],
                 str(x["antes"]), str(x["despues"]), x["origen"], x["fuente"],
                 cuerpo.motivo, cuerpo.responsable or "configurador"))
        bd.commit()
    except Exception:
        # Cualquier fallo —validación, base de datos, lo que sea— deja el
        # sistema exactamente como estaba. Si la pantalla dice «no se
        # guardó», que sea verdad.
        bd.rollback()
        for seccion, valor in instantanea.items():
            getattr(costeo, seccion.upper()).clear()
            getattr(costeo, seccion.upper()).update(valor)
        costeo._refrescar_clases()
        raise
    # El respaldo lo dispara el middleware de main.py para TODA escritura que
    # sale bien. No se llama aquí a mano: tener dos mecanismos fue justo lo
    # que dejó sin respaldo a la importación y al registro directo, porque
    # solo esta ruta se acordaba de hacerlo.
    return {"guardados": len(aplicados), "cambios": aplicados,
            "antes": antes, "despues": despues, "madurez": _madurez(),
            "respaldo": respaldo.estado()}


@router.post("/restaurar")
def restaurar(bd: sqlite3.Connection = Depends(obtener_bd)):
    """Vuelve a los valores referenciales. No borra la bitácora: registra
    la restauración como un evento más."""
    for seccion, valor in _FABRICA.items():
        destino = getattr(costeo, seccion.upper())
        destino.clear()
        destino.update(copy.deepcopy(valor))
    costeo._refrescar_clases()
    config_persistente.olvidar_todo(bd)   # que no se reapliquen al arrancar
    bd.execute(
        """INSERT INTO configuracion_bitacora
           (fecha_hora, seccion, clave, campo, valor_previo, valor_nuevo,
            origen, fuente, motivo, responsable)
           VALUES (?, 'todas', 'todas', 'todas', NULL, 'valores referenciales',
                   'referencial', '', ?, 'configurador')""",
        (datetime.now().isoformat(timespec="seconds"),
         "Restauración de los valores referenciales de fábrica"))
    bd.commit()
    # El respaldo lo dispara el middleware (ver main.py).
    return {"restaurado": True, "indicadores": _indicadores(),
            "madurez": _madurez()}


@router.get("/bitacora")
def bitacora(limite: int = 50, bd: sqlite3.Connection = Depends(obtener_bd)):
    """Historial de cambios de configuración: quién cambió qué, cuándo,
    con qué respaldo y por qué. Restaurar no borra: queda como evento."""
    filas = bd.execute(
        """SELECT fecha_hora, seccion, clave, campo, valor_previo,
                  valor_nuevo, origen, fuente, motivo, responsable
           FROM configuracion_bitacora
           ORDER BY id DESC LIMIT ?""", (max(1, min(500, limite)),)).fetchall()
    return {"eventos": [dict(f) for f in filas]}
