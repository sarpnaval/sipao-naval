"""Siembra de la base SQLite de SARP-Naval.

Ejecutable como módulo desde la raíz v1:

    python -m backend.app.seed                 # dataset guardacostas realista (defecto)
    SARP_SEED=canonico python -m backend.app.seed   # dataset canónico 42 ítems

Es IDEMPOTENTE: borra la base existente y la recrea completa.

Por DEFECTO siembra el dataset guardacostas REALISTA
(scripts/generar_dataset_realista.py, ~125 ítems) pasándolo por la MISMA
tubería que usará el piloto real: el importador (backend.app.importador)
valida los CSV y backend.motor.analisis_real calcula parámetros,
pronósticos, alertas y clasificación. Así la demo ejercita el pipeline de
datos reales, sin usar motor.construir_dataset() (que sigue intacto como
ancla de paridad del motor).

Se conserva la siembra del dataset CANÓNICO de 42 ítems
(motor.construir_dataset(), semilla determinista 20260710) como opción
explícita —`sembrar(canonico=True)` o la variable de entorno
SARP_SEED=canonico—: es útil para pruebas y como referencia de paridad.

La app nunca escribe en SISLOG: esta base es local y propia.
"""

import os

from backend import motor
from backend.app import db

# Nivel de servicio z por criticidad VED (99% / 95% / 90%)
Z_SERVICIO = {"V": 2.326, "E": 1.645, "D": 1.282}

# Orden de prioridad de alertas (dossier §5.4)
_ORDEN_ESTADO = {"QUIEBRE": 0, "REPONER": 1, "EXCESO": 2}
_ORDEN_CRIT = {"V": 0, "E": 1, "D": 2}

FECHA_CORTE = "2026-07-10"
VERSION_MODELO = "v1.0-py"

# Primer mes del histórico: julio 2023 (36 meses hasta junio 2026)
_ANIO_INICIO = 2023
_MES_INICIO = 6  # índice 0-11 → 6 = julio


def _fecha_mes(indice):
    """Fecha ISO del día 01 del mes `indice` del histórico (0 = jul-2023)."""
    anio = _ANIO_INICIO + (_MES_INICIO + indice) // 12
    mes = (_MES_INICIO + indice) % 12 + 1
    return f"{anio:04d}-{mes:02d}-01"


def _priorizar_alertas(items):
    """Ordena los ítems con estado distinto de OK según el dossier §5.4.

    Criterios: (1) estado QUIEBRE > REPONER > EXCESO; (2) criticidad
    V > E > D; (3) margen = dias_a_quiebre - lead_time_dias ascendente
    (menor margen = más urgente). Devuelve la lista ya ordenada.
    """
    con_alerta = [it for it in items if it["estado"] != "OK"]
    con_alerta.sort(key=lambda it: (
        _ORDEN_ESTADO[it["estado"]],
        _ORDEN_CRIT[it["crit"]],
        it["diasQuiebre"] - it["lt"],
    ))
    return con_alerta


def sembrar(ruta=None, canonico=None, verboso=False):
    """Borra y recrea la base local. Devuelve la ruta usada.

    `ruta`: ruta explícita de la base (por defecto se resuelve con SARP_BD
    o la ruta estándar; ver backend.app.db).

    `canonico`: si es True siembra el dataset CANÓNICO de 42 ítems
    (motor.construir_dataset); si es False siembra el dataset guardacostas
    realista por la tubería del importador. Si es None (defecto) se decide
    por la variable de entorno SARP_SEED ('canonico' -> canónico; cualquier
    otro valor o ausencia -> realista).
    """
    if canonico is None:
        canonico = os.environ.get("SARP_SEED", "").strip().lower() == "canonico"
    if canonico:
        return _sembrar_canonico(ruta, verboso)
    return _sembrar_realista(ruta, verboso)


def _sembrar_realista(ruta=None, verboso=False):
    """Siembra el dataset guardacostas realista por la tubería del importador.

    Genera el dataset simulado (determinista) en memoria como los tres CSV
    de la plantilla, y los pasa por backend.app.importador exactamente
    igual que un extracto real de SISLOG: valida, analiza con
    analisis_real y puebla todas las tablas de forma atómica. Marca el
    origen como 'simulado-realista' en metadatos.
    """
    from backend.app import importador
    from scripts import generar_dataset_realista as generador

    ruta_final = db.ruta_bd_activa(ruta)
    if ruta_final.exists():
        ruta_final.unlink()
    db.inicializar_bd(ruta_final)

    archivos = generador.construir_archivos()
    conexion = db.obtener_conexion(ruta_final)
    try:
        reporte = importador.importar(
            archivos, conexion=conexion, aplicar=True,
            fecha_importacion=generador.FECHA_CORTE_ISO)
        if not reporte["valido"]:
            detalle = "; ".join(e["mensaje"] for e in reporte["errores"][:5])
            raise RuntimeError(
                "El dataset guardacostas realista no pasó la validación del "
                f"importador: {detalle}")
        # El importador marca origen='importado'; aquí es un simulado
        # realista sembrado, no un extracto real: lo dejamos explícito.
        conexion.execute(
            "UPDATE metadatos SET valor = ? WHERE clave = 'origen'",
            ("simulado-realista",))
        conexion.commit()
    finally:
        conexion.close()

    if verboso:
        cd = reporte["calidad_datos"] or {}
        kpi = reporte["kpi"] or {}
        print(f"Base sembrada (guardacostas realista) en: {ruta_final}")
        print(f"  Reparto: {generador.REPARTO}")
        print(f"  Ítems: {reporte['resumen']['items']} | "
              f"Movimientos: {reporte['resumen']['movimientos']} | "
              f"Meses: {reporte['resumen']['meses_historia']}")
        print(f"  KPIs -> quiebres: {kpi.get('quiebres')} | "
              f"reponer: {kpi.get('reponer')} | excesos: {kpi.get('excesos')} "
              f"| capitalStock: {kpi.get('capitalStock')} | "
              f"ahorroPotencial: {kpi.get('ahorroPotencial')}")
        print(f"  Calidad -> sin_movimientos: {cd.get('sin_movimientos')} | "
              f"sin_stock: {cd.get('sin_stock')} | "
              f"historia_corta: {cd.get('historia_corta')}")
    return ruta_final


def _sembrar_canonico(ruta=None, verboso=False):
    """Borra y recrea la base con el dataset canónico de 42 ítems.

    Poblada a partir de motor.construir_dataset() (semilla determinista
    20260710). Es la referencia de paridad del motor; se conserva como
    opción explícita (ver `sembrar`).
    """
    ruta_final = db.ruta_bd_activa(ruta)
    if ruta_final.exists():
        ruta_final.unlink()
    db.inicializar_bd(ruta_final)

    datos = motor.construir_dataset()
    items = datos["items"]
    reparto = datos["reparto"]

    conexion = db.obtener_conexion(ruta_final)
    try:
        cursor = conexion.cursor()

        # ---- items (catálogo maestro; proveedor desconocido en la demo) ----
        cursor.executemany(
            """INSERT INTO items (codigo, nombre, categoria, unidad,
                   costo_unitario, criticidad_ved, lead_time_dias,
                   importado, proveedor)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
            [(it["id"], it["nombre"], it["cat"], it["um"], it["costo"],
              it["crit"], it["lt"], 1 if it["imp"] else 0) for it in items],
        )

        # ---- movimientos: 36 consumos mensuales por ítem ----
        filas_mov = []
        for it in items:
            for i, cantidad in enumerate(it["hist"]):
                filas_mov.append(
                    (it["id"], _fecha_mes(i), "consumo", cantidad, reparto))
        cursor.executemany(
            """INSERT INTO movimientos (codigo_item, fecha, tipo, cantidad,
                   reparto, orden_ref)
               VALUES (?, ?, ?, ?, ?, NULL)""",
            filas_mov,
        )

        # ---- stock: existencia actual al corte ----
        cursor.executemany(
            """INSERT INTO stock (codigo_item, reparto, existencia,
                   fecha_corte, ubicacion)
               VALUES (?, ?, ?, ?, NULL)""",
            [(it["id"], reparto, it["stock"], FECHA_CORTE) for it in items],
        )

        # ---- parametros de inventario ----
        cursor.executemany(
            """INSERT INTO parametros (codigo_item, z_servicio, ss, rop, eoq,
                   nivel_max, fecha_calculo, version_modelo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(it["id"], Z_SERVICIO[it["crit"]], it["ss"], it["rop"],
              it["eoq"], it["maxLevel"], FECHA_CORTE, VERSION_MODELO)
             for it in items],
        )

        # ---- pronosticos: 6 meses por ítem ----
        filas_pron = []
        for it in items:
            modelo = "croston" if it.get("intermitente") else "holt"
            for k, prevision in enumerate(it["forecast"]):
                filas_pron.append(
                    (it["id"], datos["fcLabels"][k], prevision,
                     it["sigma"], it["mape"], modelo))
        cursor.executemany(
            """INSERT INTO pronosticos (codigo_item, mes, demanda_prevista,
                   sigma, mape, modelo)
               VALUES (?, ?, ?, ?, ?, ?)""",
            filas_pron,
        )

        # ---- alertas: una por ítem con estado != OK, ya priorizadas ----
        for prioridad, it in enumerate(_priorizar_alertas(items), start=1):
            cursor.execute(
                """INSERT INTO alertas (codigo_item, estado, dias_a_quiebre,
                       cantidad_sugerida, prioridad, fecha, atendida)
                   VALUES (?, ?, ?, ?, ?, ?, 0)""",
                (it["id"], it["estado"], it["diasQuiebre"], it["sugerido"],
                 prioridad, FECHA_CORTE),
            )

        # ---- clasificacion (tabla calculada del motor) ----
        cursor.executemany(
            """INSERT INTO clasificacion (codigo_item, abc, xyz, cv,
                   valor_anual, valor_stock, dias_quiebre, demanda_mensual)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [(it["id"], it["abc"], it["xyz"], it["cv"], it["valorAnual"],
              it["valorStock"], it["diasQuiebre"], it["dAvg"])
             for it in items],
        )

        # ---- metadatos del conjunto de datos ----
        cursor.executemany(
            "INSERT INTO metadatos (clave, valor) VALUES (?, ?)",
            [("generado", datos["generado"]),
             ("reparto", reparto),
             ("fecha_corte", FECHA_CORTE),
             ("version_modelo", VERSION_MODELO)],
        )

        conexion.commit()
    finally:
        conexion.close()

    if verboso:
        n_alertas = sum(1 for it in items if it["estado"] != "OK")
        print(f"Base sembrada (canónico 42 ítems) en: {ruta_final}")
        print(f"  Ítems: {len(items)} | Movimientos: {len(filas_mov)} | "
              f"Pronósticos: {len(filas_pron)} | Alertas: {n_alertas}")
    return ruta_final


if __name__ == "__main__":
    sembrar(verboso=True)
