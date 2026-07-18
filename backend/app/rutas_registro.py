"""SARP-Naval · Registro directo de inventario (tarea C1.2).

La pieza que independiza a SARP de SISLOG: con este módulo el bodeguero
registra consumos/ingresos/ajustes y da de alta ítems DIRECTAMENTE en la
base PROPIA de SARP (esa es justamente la independencia — SARP jamás
escribe en SISLOG). Toda acción queda en la tabla `bitacora` como pista
de auditoría; en producción se enlaza a la autenticación institucional,
aquí registra el rol de demostración activo (cabecera X-Rol-Demo).

Endpoints:
- POST /api/registro/item        — alta de ítem nuevo en el maestro.
- POST /api/registro/movimiento  — consumo / ingreso / ajuste de stock.
- GET  /api/bitacora             — últimas acciones, más reciente primero.

Tras cada escritura exitosa se RECALCULA TODO el dataset (parámetros,
pronósticos, alertas y clasificación) reutilizando exactamente la misma
tubería del importador: se leen maestro/movimientos/stock de la base, se
analiza con backend.motor.analisis_real.analizar_importacion y se aplica
con backend.app.importador.aplicar_importacion en UNA transacción SQLite
(el movimiento nuevo, el stock actualizado, la fila de bitácora y todos
los resultados recalculados se confirman con un único COMMIT; si algo
falla, rollback total y la base anterior queda intacta). Con ~125 ítems
el recálculo completo tarda muy por debajo de 2 s: simple y correcto.

Decisiones documentadas:
- Un ítem recién dado de alta nace SIN historia y SIN existencia (0):
  opera en política de mínimos (dossier §5.5) hasta acumular datos; si
  hoy no hay stock físico, aparece honestamente como QUIEBRE hasta que
  se registre su primer INGRESO.
- El AJUSTE fija la existencia ABSOLUTA (conteo físico) con motivo
  obligatorio; se permite ajustar a 0 (merma total constatada) y la
  bitácora guarda `datos_previos` con la existencia anterior.
- El movimiento avanza la fecha de corte del stock del ítem si su fecha
  es posterior (la "foto al corte" se mantiene coherente).
- SQL siempre parametrizado; validación campo a campo en español (422).
"""

import datetime
import json
import math
import sqlite3
from typing import Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.app.db import obtener_bd
from backend.app.fechas import fecha_larga
from backend.app.importador import _fecha_iso, aplicar_importacion
from backend.motor.analisis_real import (
    MESES_POLITICA_MINIMOS,
    analizar_importacion,
)

router = APIRouter(prefix="/api", tags=["Registro directo"])

ROLES_DEMO = {"operador", "jefe", "gestion", "ejecutivo"}
TIPOS_REGISTRO = {"consumo", "ingreso", "ajuste"}
ACCIONES_BITACORA = {"alta_item", "registro_movimiento", "ajuste_stock",
                     "importacion", "recalculo"}

NOTA_MINIMOS = (
    "El ítem nace sin historia de consumo: opera en POLÍTICA DE MÍNIMOS "
    f"(dossier §5.5) hasta acumular {MESES_POLITICA_MINIMOS} meses de "
    "datos; los parámetros se recalcularán automáticamente con cada "
    "movimiento registrado.")


# ---------------------------------------------------------------------
# Utilidades comunes
# ---------------------------------------------------------------------
def resolver_rol(x_rol_demo=None, rol=None):
    """Rol de demostración que firma la acción (X-Rol-Demo o ?rol=).

    En producción esto se reemplaza por el usuario autenticado. Un valor
    desconocido cae al rol por defecto 'operador' (no es un error: la
    bitácora de demostración solo distingue los cuatro roles de la UI).
    """
    candidato = (x_rol_demo or rol or "").strip().lower()
    return candidato if candidato in ROLES_DEMO else "operador"


def _ahora_iso():
    """Fecha-hora local ISO con segundos (para la bitácora)."""
    return datetime.datetime.now().isoformat(timespec="seconds")


def _anotar_bitacora(conexion, rol, accion, codigo_item, detalle,
                     datos_previos=None):
    """Inserta una fila de bitácora SIN commit (se une a la transacción
    abierta: la confirma el COMMIT único del recálculo)."""
    conexion.execute(
        """INSERT INTO bitacora (fecha_hora, rol, accion, codigo_item,
               detalle, datos_previos)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (_ahora_iso(), rol, accion, codigo_item, detalle,
         json.dumps(datos_previos, ensure_ascii=False)
         if datos_previos is not None else None))


def _error_campo(campo, mensaje):
    return {"campo": campo, "mensaje": mensaje}


def _respuesta_422(errores):
    """422 con TODOS los errores campo a campo, en español."""
    return JSONResponse(
        status_code=422,
        content={
            "error": ("Datos inválidos: corrija los campos señalados. " +
                      " · ".join(f"[{e['campo']}] {e['mensaje']}"
                                 for e in errores)),
            "errores": errores,
        })


def _texto(valor):
    """Valor del cuerpo como texto limpio ('' si viene vacío o None)."""
    if valor is None:
        return ""
    return str(valor).strip()


def _numero(valor):
    """Valor del cuerpo como float FINITO; None si no es numérico.

    NaN e infinito ('nan', 'inf', '1e999'…) se rechazan aquí: pasan
    float() y engañan a las comparaciones (nan <= 0 es False), pero
    reventarían después dentro del recálculo con un 500 genérico en
    lugar del 422 campo a campo prometido.
    """
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        resultado = float(valor)
        return resultado if math.isfinite(resultado) else None
    texto = _texto(valor)
    if not texto:
        return None
    try:
        resultado = float(texto.replace(",", ".", 1)
                          if texto.count(",") == 1 and "." not in texto
                          else texto)
    except ValueError:
        return None
    return resultado if math.isfinite(resultado) else None


def _abrir_transaccion_escritura(conexion):
    """Toma el candado de escritura de SQLite ANTES de leer el estado.

    Los endpoints de escritura leen TODO el estado, lo recalculan y lo
    reemplazan: sin este candado, dos peticiones concurrentes leerían el
    mismo estado y la segunda borraría silenciosamente lo que la primera
    acababa de confirmar (lost update). BEGIN IMMEDIATE serializa
    lectores-escritores: la segunda petición espera el COMMIT de la
    primera y recién entonces lee el estado ya actualizado.
    """
    # Espera hasta 30 s el candado (el recálculo tarda < 2 s por escritura)
    conexion.execute("PRAGMA busy_timeout = 30000")
    try:
        conexion.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as exc:
        raise HTTPException(
            status_code=503,
            detail="La base de datos está ocupada procesando otra "
                   "escritura: reintente en unos segundos.") from exc


# ---------------------------------------------------------------------
# Lectura del estado actual de la base → estructuras del importador
# ---------------------------------------------------------------------
def _leer_datos_bd(conexion):
    """Lee maestro/movimientos/stock de la base en las MISMAS estructuras
    que produce importador.validar(): así el recálculo reutiliza la
    tubería analizar_importacion + aplicar_importacion sin duplicar nada.
    """
    maestro = [{
        "codigo": f["codigo"], "nombre": f["nombre"],
        "categoria": f["categoria"], "unidad": f["unidad"],
        "costo": f["costo_unitario"], "crit": f["criticidad_ved"],
        "lt": f["lead_time_dias"], "imp": bool(f["importado"]),
        "proveedor": f["proveedor"],
    } for f in conexion.execute("SELECT * FROM items ORDER BY rowid")]

    movimientos = [{
        "codigo": f["codigo_item"], "fecha": f["fecha"],
        "tipo": f["tipo"].upper(), "cantidad": f["cantidad"],
        "reparto": f["reparto"], "referencia": f["orden_ref"],
    } for f in conexion.execute(
        "SELECT * FROM movimientos ORDER BY id")]

    stock = {f["codigo_item"]: {
        "existencia": f["existencia"], "fecha_corte": f["fecha_corte"],
        "ubicacion": f["ubicacion"],
    } for f in conexion.execute("SELECT * FROM stock")}

    fila = conexion.execute(
        "SELECT valor FROM metadatos WHERE clave = 'reparto'").fetchone()
    reparto = fila["valor"] if fila else None

    return {"maestro": maestro, "movimientos": movimientos, "stock": stock,
            "reparto": reparto}


def _recalcular_y_aplicar(conexion, datos, rol, resumen_accion):
    """Analiza el dataset completo y lo aplica en la MISMA transacción.

    aplicar_importacion borra y reinserta datos + resultados y hace el
    ÚNICO COMMIT: como esta conexión ya tiene filas sin confirmar (la
    bitácora de la acción), todo se confirma junto; si falla, rollback
    total. El metadato `origen` previo se pasa a aplicar_importacion
    para que viaje en esa misma transacción (el registro directo no
    convierte el dataset en 'importado' y no hay ninguna ventana en la
    que quede confirmado un origen incorrecto).
    Devuelve el análisis (para responder KPIs y estado del ítem).
    """
    origen_previo = conexion.execute(
        "SELECT valor FROM metadatos WHERE clave = 'origen'").fetchone()
    analisis = analizar_importacion(
        datos["maestro"], datos["movimientos"], datos["stock"],
        reparto=datos["reparto"])

    _anotar_bitacora(
        conexion, rol, "recalculo", None,
        f"Recálculo automático tras {resumen_accion}: "
        f"{analisis['kpi']['quiebres']} quiebres, "
        f"{analisis['kpi']['reponer']} bajo ROP, "
        f"{analisis['kpi']['excesos']} excesos.")

    aplicar_importacion(
        conexion, datos, analisis,
        fecha_importacion=datetime.date.today().isoformat(),
        origen=origen_previo["valor"] if origen_previo else "importado")
    return analisis


def _estado_item(analisis, codigo):
    """Estado y parámetros del ítem según el análisis recién aplicado."""
    for it in analisis["items"]:
        if it["id"] == codigo:
            return {
                "estado": it["estado"],
                "existencia": it["stock"],
                "ss": it["ss"], "rop": it["rop"], "eoq": it["eoq"],
                "dias_a_quiebre": it["diasQuiebre"],
                "cantidad_sugerida": it["sugerido"],
                "politica_minimos": it["politica_minimos"],
            }
    return None


def _kpi_resumen(analisis):
    k = analisis["kpi"]
    return {"quiebres": k["quiebres"], "reponer": k["reponer"],
            "excesos": k["excesos"], "capitalStock": k["capitalStock"]}


# ---------------------------------------------------------------------
# POST /api/registro/item — alta de ítem nuevo en el maestro propio
# ---------------------------------------------------------------------
@router.post("/registro/item")
def alta_item(
    datos: dict = Body(...),
    rol: Optional[str] = Query(None, description="Rol de demostración"),
    x_rol_demo: Optional[str] = Header(None, alias="X-Rol-Demo"),
    bd: sqlite3.Connection = Depends(obtener_bd),
):
    """Da de alta un ítem nuevo en el maestro PROPIO de SARP.

    Valida todos los campos a la vez (422 con errores campo a campo en
    español). El ítem nace sin historia y sin existencia: opera en
    política de mínimos hasta acumular datos (se documenta en la
    respuesta). Registra la acción en la bitácora y recalcula todo.
    """
    rol_activo = resolver_rol(x_rol_demo, rol)
    # Candado de escritura ANTES de leer nada (incluida la verificación
    # de código duplicado): serializa altas concurrentes (lost update).
    _abrir_transaccion_escritura(bd)
    errores = []

    codigo = _texto(datos.get("codigo"))
    if not codigo:
        errores.append(_error_campo("codigo", "El código del ítem es obligatorio."))
    elif len(codigo) > 40:
        errores.append(_error_campo("codigo", "El código no puede superar 40 caracteres."))
    elif bd.execute("SELECT 1 FROM items WHERE codigo = ?",
                    (codigo,)).fetchone():
        errores.append(_error_campo(
            "codigo", f"Ya existe un ítem con el código '{codigo}' en el "
                      "maestro: el código debe ser único."))

    for campo, etiqueta in (("nombre", "nombre"), ("categoria", "categoría"),
                            ("unidad", "unidad de medida")):
        if not _texto(datos.get(campo)):
            errores.append(_error_campo(
                campo, f"La {etiqueta} del ítem es obligatoria."))

    costo = _numero(datos.get("costo_unitario"))
    if costo is None or costo <= 0:
        errores.append(_error_campo(
            "costo_unitario",
            "El costo unitario debe ser un número mayor que 0 "
            f"(valor recibido: '{_texto(datos.get('costo_unitario'))}')."))

    criticidad = _texto(datos.get("criticidad")).upper()
    if criticidad not in ("V", "E", "D"):
        errores.append(_error_campo(
            "criticidad",
            "Criticidad inválida: debe ser V (vital), E (esencial) o "
            f"D (deseable); se recibió '{_texto(datos.get('criticidad'))}'."))

    lead_time = _numero(datos.get("lead_time_dias"))
    if (lead_time is None or lead_time <= 0
            or not float(lead_time).is_integer()):
        errores.append(_error_campo(
            "lead_time_dias",
            "El lead time debe ser un entero de días mayor que 0 "
            f"(valor recibido: '{_texto(datos.get('lead_time_dias'))}')."))

    importado = _texto(datos.get("importado")).upper()
    if importado not in ("S", "N"):
        errores.append(_error_campo(
            "importado",
            "La columna importado debe ser S o N; se recibió "
            f"'{_texto(datos.get('importado'))}'."))

    if errores:
        return _respuesta_422(errores)

    ficha = {
        "codigo": codigo,
        "nombre": _texto(datos.get("nombre")),
        "categoria": _texto(datos.get("categoria")),
        "unidad": _texto(datos.get("unidad")),
        "costo": costo,
        "crit": criticidad,
        "lt": int(lead_time),
        "imp": importado == "S",
        "proveedor": _texto(datos.get("proveedor")) or None,
    }

    conjunto = _leer_datos_bd(bd)
    conjunto["maestro"].append(ficha)
    # Nace sin existencia (0) a la fecha de corte vigente del dataset
    cortes = [s["fecha_corte"] for s in conjunto["stock"].values()
              if s["fecha_corte"]]
    corte_vigente = max(cortes) if cortes else datetime.date.today().isoformat()
    conjunto["stock"][codigo] = {"existencia": 0.0,
                                 "fecha_corte": corte_vigente,
                                 "ubicacion": None}

    _anotar_bitacora(
        bd, rol_activo, "alta_item", codigo,
        f"Alta de ítem '{ficha['nombre']}' ({ficha['categoria']}, "
        f"criticidad {criticidad}, costo ${costo:g}, LT {int(lead_time)} d, "
        f"{'importado' if ficha['imp'] else 'nacional'}). {NOTA_MINIMOS}")

    try:
        analisis = _recalcular_y_aplicar(
            bd, conjunto, rol_activo, f"alta del ítem {codigo}")
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo aplicar el alta; la base de datos anterior "
                   f"quedó intacta. Detalle técnico: {exc}") from exc

    return {
        "creado": True,
        "item": {**ficha, "importado": importado},
        "politica_minimos": True,
        "nota": NOTA_MINIMOS,
        "estado": _estado_item(analisis, codigo),
        "kpi": _kpi_resumen(analisis),
        "mensaje": f"Ítem '{codigo}' dado de alta en el maestro de SARP y "
                   "dataset recalculado.",
    }


# ---------------------------------------------------------------------
# POST /api/registro/movimiento — consumo / ingreso / ajuste
# ---------------------------------------------------------------------
@router.post("/registro/movimiento")
def registrar_movimiento(
    datos: dict = Body(...),
    rol: Optional[str] = Query(None, description="Rol de demostración"),
    x_rol_demo: Optional[str] = Header(None, alias="X-Rol-Demo"),
    bd: sqlite3.Connection = Depends(obtener_bd),
):
    """Registra un movimiento de inventario en la base PROPIA de SARP.

    - consumo: descuenta del stock; no puede dejar existencia < 0 (409).
    - ingreso: suma al stock.
    - ajuste: fija la existencia ABSOLUTA (conteo físico), con motivo
      obligatorio; se permite ajustar a 0. La bitácora guarda
      `datos_previos` con el estado anterior del stock.

    El movimiento, la actualización del stock, la bitácora y el recálculo
    completo se confirman en UNA transacción (COMMIT único).
    """
    rol_activo = resolver_rol(x_rol_demo, rol)
    # Candado de escritura ANTES de leer la existencia: dos movimientos
    # concurrentes ya no pueden partir del mismo stock previo ni
    # reemplazarse mutuamente el estado recalculado (lost update).
    _abrir_transaccion_escritura(bd)
    errores = []

    codigo = _texto(datos.get("codigo"))
    if not codigo:
        errores.append(_error_campo("codigo", "El código del ítem es obligatorio."))

    tipo = _texto(datos.get("tipo")).lower()
    if tipo not in TIPOS_REGISTRO:
        errores.append(_error_campo(
            "tipo", "Tipo de movimiento inválido: debe ser consumo, ingreso "
                    f"o ajuste; se recibió '{_texto(datos.get('tipo'))}'."))

    cantidad = _numero(datos.get("cantidad"))
    if cantidad is None:
        errores.append(_error_campo(
            "cantidad", "La cantidad debe ser numérica (valor recibido: "
                        f"'{_texto(datos.get('cantidad'))}')."))
    elif tipo == "ajuste":
        if cantidad < 0:
            errores.append(_error_campo(
                "cantidad", "El ajuste fija la existencia absoluta contada: "
                            "debe ser mayor o igual a 0 (0 = merma total)."))
    elif cantidad <= 0:
        errores.append(_error_campo(
            "cantidad", "La cantidad debe ser mayor que 0."))

    hoy = datetime.date.today().isoformat()
    fecha_cruda = _texto(datos.get("fecha"))
    if fecha_cruda:
        fecha = _fecha_iso(fecha_cruda)
        if fecha is None:
            errores.append(_error_campo(
                "fecha", "Fecha inválida: use dd/mm/aaaa o yyyy-mm-dd "
                         f"(valor recibido: '{fecha_cruda}')."))
        elif fecha > hoy:
            errores.append(_error_campo(
                "fecha", f"La fecha del movimiento ({fecha_larga(fecha)}) no "
                         "puede ser futura: los movimientos registran hechos "
                         "ya ocurridos."))
    else:
        fecha = hoy  # por defecto: hoy

    motivo = _texto(datos.get("motivo"))
    if tipo == "ajuste" and not motivo:
        errores.append(_error_campo(
            "motivo", "El motivo del ajuste es obligatorio (p. ej. conteo "
                      "físico, merma, corrección de inventario)."))

    if errores:
        return _respuesta_422(errores)

    ficha = bd.execute("SELECT * FROM items WHERE codigo = ?",
                       (codigo,)).fetchone()
    if ficha is None:
        raise HTTPException(
            status_code=404,
            detail=f"Ítem '{codigo}' no encontrado en el maestro de SARP. "
                   "Dé de alta el ítem antes de registrar movimientos.")

    fila_stock = bd.execute(
        "SELECT * FROM stock WHERE codigo_item = ?", (codigo,)).fetchone()
    existencia_previa = fila_stock["existencia"] if fila_stock else 0.0

    # ---- Nueva existencia según el tipo ----
    if tipo == "consumo":
        if cantidad > existencia_previa:
            raise HTTPException(
                status_code=409,
                detail=f"El consumo de {cantidad:g} {ficha['unidad']} "
                       f"dejaría la existencia en negativo: el ítem "
                       f"'{codigo}' solo tiene {existencia_previa:g} "
                       f"{ficha['unidad']} en stock. Verifique la cantidad "
                       "o registre antes el ingreso faltante.")
        existencia_nueva = existencia_previa - cantidad
    elif tipo == "ingreso":
        existencia_nueva = existencia_previa + cantidad
    else:  # ajuste: fija la existencia absoluta contada
        existencia_nueva = cantidad

    conjunto = _leer_datos_bd(bd)
    referencia = motivo if tipo == "ajuste" else (
        _texto(datos.get("referencia")) or None)
    conjunto["movimientos"].append({
        "codigo": codigo, "fecha": fecha, "tipo": tipo.upper(),
        "cantidad": cantidad, "reparto": conjunto["reparto"] or
        (fila_stock["reparto"] if fila_stock else "SARP"),
        "referencia": referencia,
    })
    corte_previo = (fila_stock["fecha_corte"] if fila_stock else fecha)
    conjunto["stock"][codigo] = {
        "existencia": existencia_nueva,
        # la foto al corte avanza si el movimiento es posterior
        "fecha_corte": max(corte_previo, fecha),
        "ubicacion": fila_stock["ubicacion"] if fila_stock else None,
    }

    accion = "ajuste_stock" if tipo == "ajuste" else "registro_movimiento"
    if tipo == "ajuste":
        detalle = (f"Ajuste de existencia de '{codigo}' a {cantidad:g} "
                   f"{ficha['unidad']} (antes: {existencia_previa:g}). "
                   f"Motivo: {motivo}.")
        datos_previos = {"existencia": existencia_previa,
                         "fecha_corte": corte_previo}
    else:
        detalle = (f"{tipo.capitalize()} de {cantidad:g} {ficha['unidad']} "
                   f"de '{codigo}' con fecha {fecha_larga(fecha)}: "
                   f"existencia {existencia_previa:g} → {existencia_nueva:g}"
                   + (f" (ref. {referencia})" if referencia else "") + ".")
        datos_previos = None
    _anotar_bitacora(bd, rol_activo, accion, codigo, detalle, datos_previos)

    try:
        analisis = _recalcular_y_aplicar(
            bd, conjunto, rol_activo, f"{tipo} de {codigo}")
    except sqlite3.Error as exc:
        raise HTTPException(
            status_code=500,
            detail="No se pudo registrar el movimiento; la base de datos "
                   f"anterior quedó intacta. Detalle técnico: {exc}") from exc

    return {
        "registrado": True,
        "movimiento": {"codigo": codigo, "tipo": tipo, "cantidad": cantidad,
                       "fecha": fecha_larga(fecha),
                       "referencia": referencia},
        "existencia_anterior": existencia_previa,
        "existencia_nueva": existencia_nueva,
        "estado": _estado_item(analisis, codigo),
        "kpi": _kpi_resumen(analisis),
        "mensaje": f"{tipo.capitalize()} registrado: '{codigo}' pasa de "
                   f"{existencia_previa:g} a {existencia_nueva:g} "
                   f"{ficha['unidad']}. Dataset recalculado.",
    }


# ---------------------------------------------------------------------
# GET /api/bitacora — pista de auditoría (más reciente primero)
# ---------------------------------------------------------------------
@router.get("/bitacora")
def leer_bitacora(
    limite: int = Query(20, ge=1, le=500,
                        description="Máximo de registros a devolver"),
    accion: Optional[str] = Query(
        None, description="Filtrar por acción: alta_item, "
                          "registro_movimiento, ajuste_stock, importacion "
                          "o recalculo"),
    bd: sqlite3.Connection = Depends(obtener_bd),
):
    """Últimos N registros de la bitácora de auditoría, del más reciente
    al más antiguo, con filtro opcional por tipo de acción."""
    if accion is not None and accion not in ACCIONES_BITACORA:
        raise HTTPException(
            status_code=422,
            detail=f"Acción inválida: '{accion}'. Valores permitidos: "
                   + ", ".join(sorted(ACCIONES_BITACORA)) + ".")

    sql = """SELECT id, fecha_hora, rol, accion, codigo_item, detalle,
                    datos_previos
             FROM bitacora WHERE 1 = 1"""
    parametros = []
    if accion is not None:
        sql += " AND accion = ?"
        parametros.append(accion)
    sql += " ORDER BY id DESC LIMIT ?"
    parametros.append(limite)

    registros = []
    for fila in bd.execute(sql, parametros):
        registro = dict(fila)
        # regla del proyecto: dd-mmm-aaaa hh:mm hacia el usuario
        fh = registro["fecha_hora"]
        registro["fecha_formato"] = (
            f"{fecha_larga(fh[:10])} {fh[11:16]}" if len(fh) >= 16
            else fecha_larga(fh[:10]))
        registros.append(registro)

    total = bd.execute("SELECT COUNT(*) AS n FROM bitacora").fetchone()["n"]
    return {"total_bitacora": total, "mostrados": len(registros),
            "registros": registros}
