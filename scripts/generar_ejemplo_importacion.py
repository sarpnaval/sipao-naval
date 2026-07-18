# -*- coding: utf-8 -*-
"""SARP-Naval — Generador de plantillas y ejemplo sintético de importación (tarea 2.3).

Crea en 03-datos/plantillas/:
  - plantilla_maestro_items.csv / plantilla_movimientos.csv /
    plantilla_stock_actual.csv: encabezados + filas de ejemplo comentadas
    (las filas '#...' las ignora el importador) para que un reparto sepa qué
    formato entregar.
  - ejemplo_sintetico/: un dataset COMPLETO y válido (10 ítems, 30 meses)
    que sirve de demostración del importador y de fixture para las pruebas.

Los datos son 100% FICTICIOS y deterministas (random.Random(20260711)):
no provienen de SISLOG ni de ningún dato real. Cubren a propósito los
casos que el importador debe manejar: demanda regular, demanda
intermitente, un ítem con historia corta (política de mínimos, dossier
§5.5) y un ítem sin fila de stock (existencia 0 → QUIEBRE).

Uso (desde 01-app/v1/scripts/):
    %USERPROFILE%\\.venvs\\sarp-naval\\Scripts\\python.exe generar_ejemplo_importacion.py
"""
import csv
import random
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[3]
DIR_PLANTILLAS = RAIZ / "03-datos" / "plantillas"
DIR_EJEMPLO = DIR_PLANTILLAS / "ejemplo_sintetico"

REPARTO = "Reparto guardacostas SUBNOR (referencial)"
FECHA_CORTE = "30/06/2026"  # dd/mm/aaaa (ejercita ese parser)

# 30 meses: ene-2024 .. jun-2026 (año, mes) del día 01 de cada mes
def _meses(desde=(2024, 1), n=30):
    y, m = desde
    salida = []
    for _ in range(n):
        salida.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return salida


MESES = _meses()

# (codigo, nombre, categoria, unidad, costo, crit, lt_dias, importado,
#  proveedor, base_mensual, patron, meses_historia)
# patron: "regular" | "intermitente" | "estacional"
CATALOGO = [
    ("REP-0001", "Filtro de combustible motor F/B 200HP", "Motor F/B", "u",
     38.5, "V", 45, "S", "Marine Parts Intl.", 8, "regular", 30),
    ("REP-0002", "Impulsor bomba de agua 200-250HP", "Motor F/B", "u",
     48.0, "V", 45, "S", "Marine Parts Intl.", 5, "regular", 30),
    ("REP-0003", "Aceite 2T TC-W3 (galón)", "Lubricantes", "gal",
     28.0, "V", 10, "N", "Lubricantes del Pacífico", 40, "estacional", 30),
    ("REP-0004", "Ánodo de sacrificio motor F/B", "Motor F/B", "u",
     14.0, "E", 30, "N", "Lubricantes del Pacífico", 12, "regular", 30),
    ("REP-0005", "Hélice acero inox 3 palas 15.5x17", "Motor F/B", "u",
     620.0, "E", 75, "S", "Marine Parts Intl.", 1, "intermitente", 30),
    ("REP-0006", "GPS/plotter 9\" (unidad reemplazo)", "Electrónica", "u",
     1150.0, "V", 90, "S", "NavElectronics Co.", 1, "intermitente", 30),
    ("REP-0007", "Chaleco salvavidas SOLAS adulto", "Seguridad", "u",
     65.0, "V", 30, "N", "Seguridad Marina EC", 6, "regular", 30),
    ("REP-0008", "Batería marina AGM 12V 100Ah", "Electrónica", "u",
     265.0, "V", 30, "N", "NavElectronics Co.", 3, "regular", 30),
    # Historia corta (6 meses) → política de mínimos
    ("REP-0009", "Kit empaques power head 250HP (nuevo)", "Motor F/B", "kit",
     210.0, "V", 60, "S", "Marine Parts Intl.", 4, "regular", 6),
    # Deseable de bajo costo, se dejará SIN fila de stock → QUIEBRE
    ("REP-0010", "Lija de agua #400 (pliego)", "Consumibles", "u",
     0.9, "D", 7, "N", "Ferretería Naval", 30, "regular", 30),
]

# Existencia actual por ítem (elegida para producir estados variados).
# REP-0010 se OMITE a propósito (sin fila de stock → existencia 0).
STOCK = {
    "REP-0001": (95, "Bodega A · Estante 3"),
    "REP-0002": (4, "Bodega A · Estante 3"),      # bajo ROP → REPONER
    "REP-0003": (520, "Bodega B · Tanque 1"),      # alto → posible EXCESO
    "REP-0004": (60, "Bodega A · Estante 5"),
    "REP-0005": (3, "Bodega C · Jaula 2"),
    "REP-0006": (0, "Bodega C · Jaula 2"),         # existencia 0 → QUIEBRE
    "REP-0007": (48, "Pañol de seguridad"),
    "REP-0008": (10, "Bodega D · Baterías"),
    "REP-0009": (5, "Bodega A · Estante 3"),
}


def _demanda(rng, base, patron, indice, total):
    """Demanda mensual ficticia según el patrón del ítem."""
    if patron == "intermitente":
        # muchos ceros; cuando hay demanda, un lote
        if rng.random() < 0.30:
            return max(1, int(round(base * rng.uniform(1, 4))))
        return 0
    factor = 1.0
    if patron == "estacional":
        # pico may-sep (meses 5-9)
        import math
        mes = MESES[indice][1]
        factor = 1 + 0.35 * math.sin(2 * math.pi * (mes - 4) / 12)
    # ligera tendencia de crecimiento (llegada de interceptoras)
    tendencia = 1 + 0.4 * (indice / total)
    valor = base * factor * tendencia * rng.uniform(0.8, 1.2)
    return max(0, int(round(valor)))


def generar_movimientos(rng):
    """Lista de filas de movimientos (dicts) para el ejemplo sintético."""
    filas = []
    for (codigo, *_resto) in CATALOGO:
        datos = next(c for c in CATALOGO if c[0] == codigo)
        base, patron, meses_hist = datos[9], datos[10], datos[11]
        meses_item = MESES[-meses_hist:]  # los últimos N meses
        for i, (y, m) in enumerate(meses_item):
            cantidad = _demanda(rng, base, patron, i, len(meses_item))
            if cantidad > 0:
                filas.append({
                    "codigo": codigo,
                    "fecha": f"{15:02d}/{m:02d}/{y}",
                    "tipo": "CONSUMO",
                    "cantidad": cantidad,
                    "reparto": REPARTO,
                    "referencia": f"OT-{y}-{rng.randint(1, 999):03d}",
                })
        # un par de INGRESOS (el análisis los ignora, pero deben aceptarse)
        for (y, m) in (meses_item[0], meses_item[len(meses_item) // 2]):
            filas.append({
                "codigo": codigo,
                "fecha": f"{5:02d}/{m:02d}/{y}",
                "tipo": "INGRESO",
                "cantidad": base * 6,
                "reparto": REPARTO,
                "referencia": "",
            })
    return filas


def _escribir_csv(ruta, columnas, filas, comentarios=None):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with ruta.open("w", encoding="utf-8", newline="") as fh:
        escritor = csv.writer(fh)
        escritor.writerow(columnas)
        for linea in comentarios or []:
            escritor.writerow([linea] + [""] * (len(columnas) - 1))
        for fila in filas:
            escritor.writerow([fila[c] for c in columnas])


def generar_plantillas_vacias():
    """Plantillas con encabezados y filas de ejemplo comentadas."""
    _escribir_csv(
        DIR_PLANTILLAS / "plantilla_maestro_items.csv",
        ["codigo", "nombre", "categoria", "unidad", "costo_unitario_usd",
         "criticidad", "lead_time_dias", "importado", "proveedor"],
        [],
        comentarios=[
            "# EJEMPLO (borre las filas '#'): REP-0001, Filtro combustible, "
            "Motor F/B, u, 38.50, V, 45, S, Proveedor S.A.",
            "# criticidad: V/E/D · importado: S/N · costo>0 · "
            "lead_time_dias entero>0",
        ])
    _escribir_csv(
        DIR_PLANTILLAS / "plantilla_movimientos.csv",
        ["codigo", "fecha", "tipo", "cantidad", "reparto", "referencia"],
        [],
        comentarios=[
            "# EJEMPLO: REP-0001, 15/01/2025, CONSUMO, 6, Reparto SUBNOR, "
            "OT-2025-014",
            "# fecha: dd/mm/aaaa o aaaa-mm-dd · tipo: CONSUMO/INGRESO/AJUSTE "
            "· 24-36 meses recomendados",
        ])
    _escribir_csv(
        DIR_PLANTILLAS / "plantilla_stock_actual.csv",
        ["codigo", "existencia", "fecha_corte", "ubicacion"],
        [],
        comentarios=[
            "# EJEMPLO: REP-0001, 12, 30/06/2026, Bodega A Estante 3",
            "# una fila por ítem · existencia>=0",
        ])


def generar_ejemplo(rng):
    """Dataset sintético completo (importable sin errores)."""
    maestro = [{
        "codigo": c[0], "nombre": c[1], "categoria": c[2], "unidad": c[3],
        "costo_unitario_usd": f"{c[4]:g}", "criticidad": c[5],
        "lead_time_dias": c[6], "importado": c[7], "proveedor": c[8],
    } for c in CATALOGO]
    _escribir_csv(
        DIR_EJEMPLO / "maestro_items.csv",
        ["codigo", "nombre", "categoria", "unidad", "costo_unitario_usd",
         "criticidad", "lead_time_dias", "importado", "proveedor"],
        maestro)

    movimientos = generar_movimientos(rng)
    _escribir_csv(
        DIR_EJEMPLO / "movimientos.csv",
        ["codigo", "fecha", "tipo", "cantidad", "reparto", "referencia"],
        movimientos)

    stock = [{
        "codigo": codigo, "existencia": existencia,
        "fecha_corte": FECHA_CORTE, "ubicacion": ubic,
    } for codigo, (existencia, ubic) in STOCK.items()]
    _escribir_csv(
        DIR_EJEMPLO / "stock_actual.csv",
        ["codigo", "existencia", "fecha_corte", "ubicacion"],
        stock)

    return len(maestro), len(movimientos), len(stock)


def main():
    rng = random.Random(20260711)
    generar_plantillas_vacias()
    n_items, n_mov, n_stock = generar_ejemplo(rng)
    print(f"Plantillas vacías: {DIR_PLANTILLAS}")
    print(f"Ejemplo sintético: {DIR_EJEMPLO}")
    print(f"  maestro_items.csv : {n_items} ítems")
    print(f"  movimientos.csv   : {n_mov} movimientos")
    print(f"  stock_actual.csv  : {n_stock} filas de stock "
          f"(REP-0010 omitido a proposito -> QUIEBRE)")


if __name__ == "__main__":
    main()
