"""SARP-Naval · Motor de análisis para datos IMPORTADOS (tarea 2.3).

A diferencia de motor.py (demo con datos simulados y PRNG), este módulo
NO usa ningún generador aleatorio: es determinista por construcción, la
salida depende únicamente de los datos importados (maestro, movimientos
y stock). Reutiliza las fórmulas canónicas de motor.py (holt,
croston_lite, redondeo_js, clasificar_abc, z por criticidad, EOQ) para
que los cálculos sean EXACTAMENTE los mismos que valida el jurado en la
demo — sin duplicar fórmulas.

Reglas del análisis (documentadas para sustentación técnica):

1. SERIE MENSUAL POR ÍTEM: se agrega la cantidad de los movimientos
   tipo CONSUMO por mes calendario. La serie de cada ítem empieza en su
   PRIMER mes con consumo y termina en el ÚLTIMO mes del rango global
   del dataset importado; los meses intermedios sin consumo cuentan
   como 0 (cero demanda observada, no dato faltante).

2. DEMANDA INTERMITENTE: si la proporción de meses en cero de la serie
   es >= UMBRAL_INTERMITENCIA (0.40) se pronostica con croston_lite;
   si no, con holt. El umbral equivale a un intervalo medio entre
   demandas (ADI) >= 1/0.6 ≈ 1.67 meses, criterio conservador frente
   al ADI > 1.32 clásico de Syntetos-Boylan: preferimos clasificar como
   intermitente antes que aplicar Holt a una serie llena de ceros.

3. POLÍTICA DE MÍNIMOS (dossier §5.5): un ítem con historia menor a
   MESES_POLITICA_MINIMOS (18) no recibe pronóstico estadístico (con
   tan pocas observaciones sigma no es confiable y z·sigma·raiz(LT)
   pierde sentido). En su lugar se aplica una regla simple y
   conservadora, auditable por un jurado técnico:

       SS  = ceil(d_media_mensual × factor_criticidad)
       ROP = ceil(d_media_mensual × LT_meses + SS)

   con factor_criticidad V=1.0, E=0.75, D=0.5: el colchón de seguridad
   es una fracción fija de UN MES de demanda media según la criticidad
   del ítem (un ítem vital cubre un mes entero adicional de demanda;
   uno deseable, medio mes). Es el equivalente discreto de asumir el
   peor CV razonable cuando no se puede estimar: protege el servicio
   sin inflar el capital. El EOQ sí se calcula (no es estadístico) y el
   "pronóstico" mostrado es la media simple de la historia disponible,
   marcado con politica_minimos=True y SIN registrarse como modelo
   estadístico en la tabla de pronósticos.

4. MISMOS CÁLCULOS Y REDONDEOS que el motor simulado: dAvg sobre los
   últimos 12 meses (o los que haya), SS = ceil(z·sigma·raiz(max(LT_m,
   0.25))), ROP = ceil(d̄·LT_m + SS), EOQ = raiz(2DS/H) con S=120
   importado / 45 nacional y H=18%, nivel máximo = ROP + EOQ, estados
   QUIEBRE/REPONER/OK/EXCESO, ABC por Pareto 80/95 sobre el conjunto
   importado y XYZ por CV. Única adaptación: como la existencia
   importada puede ser fraccionaria, la cantidad sugerida usa
   ceil(ROP + EOQ - stock) (con stock entero coincide con el motor).

5. INFORME DE CALIDAD DE DATOS (README_DATOS regla 4): ítems sin
   movimientos de consumo, sin fila de stock, con historia corta
   (política de mínimos), con historia bajo el mínimo útil de 24 meses
   y movimientos con fecha posterior a la fecha de corte del stock.
"""

import math
from collections import Counter, defaultdict

from .motor import (
    MESES,
    TASA_POSESION,
    Z,
    clasificar_abc,
    costo_orden,
    croston_lite,
    holt,
    redondeo_js,
)

__all__ = [
    "analizar_importacion",
    "UMBRAL_INTERMITENCIA",
    "MESES_POLITICA_MINIMOS",
    "MESES_MINIMO_UTIL",
    "FACTOR_MINIMOS",
    "HORIZONTE_PRONOSTICO",
]

# Proporción de meses en cero a partir de la cual la demanda se trata
# como intermitente (ver regla 2 del docstring del módulo).
UMBRAL_INTERMITENCIA = 0.40

# Historia mínima (meses) para pronóstico estadístico (dossier §5.5).
MESES_POLITICA_MINIMOS = 18

# Mínimo útil recomendado por README_DATOS (regla 2): 24 meses.
MESES_MINIMO_UTIL = 24

# Factor de la política de mínimos: fracción de un mes de demanda media
# que se mantiene como colchón, según criticidad V/E/D (regla 3).
FACTOR_MINIMOS = {"V": 1.0, "E": 0.75, "D": 0.5}

# Horizonte de pronóstico en meses (igual que la demo).
HORIZONTE_PRONOSTICO = 6


# ---------------------------------------------------------------------
# Utilidades de calendario (índice absoluto de mes = año*12 + mes-1)
# ---------------------------------------------------------------------
def _indice_mes(fecha_iso):
    """Índice absoluto del mes de una fecha ISO yyyy-mm-dd."""
    return int(fecha_iso[0:4]) * 12 + int(fecha_iso[5:7]) - 1


def _etiqueta_mes(indice):
    """Etiqueta corta 'mmm-aa' de un índice absoluto de mes."""
    anio = indice // 12
    return f"{MESES[indice % 12]}-{str(anio)[2:]}"


def _iso_mes(indice):
    """Fecha ISO del día 01 de un índice absoluto de mes."""
    return f"{indice // 12:04d}-{indice % 12 + 1:02d}-01"


def _desviacion_muestral(serie, media):
    """Desviación estándar muestral (n-1); 0.0 con menos de 2 datos."""
    if len(serie) < 2:
        return 0.0
    suma = 0.0
    for v in serie:
        suma += (v - media) ** 2
    return math.sqrt(suma / (len(serie) - 1))


# ---------------------------------------------------------------------
# Análisis principal
# ---------------------------------------------------------------------
def analizar_importacion(maestro, movimientos, stock, reparto=None,
                         fecha_corte=None):
    """Analiza un dataset importado y devuelve la misma estructura que
    motor.construir_dataset() más el informe de calidad de datos.

    Parámetros (ya validados por backend.app.importador):
    - maestro: lista de dicts con codigo, nombre, categoria, unidad,
      costo (float > 0), crit ('V'/'E'/'D'), lt (días, int > 0),
      imp (bool) y proveedor (str o None), en el orden del archivo.
    - movimientos: lista de dicts con codigo, fecha (ISO yyyy-mm-dd),
      tipo ('CONSUMO'/'INGRESO'/'AJUSTE'), cantidad (float), reparto y
      referencia.
    - stock: dict codigo -> {"existencia": float, "fecha_corte": ISO,
      "ubicacion": str o None}. Ítems ausentes se asumen con 0.
    - reparto: nombre del reparto (si None se detecta por mayoría).
    - fecha_corte: ISO; si None se toma la mayor fecha_corte del stock
      o, en su defecto, la mayor fecha de movimiento.

    Devuelve dict con claves: items, kpi, labels, fcLabels,
    meses_historia, rango_fechas, fecha_corte, reparto, calidad_datos.
    """
    if not maestro:
        raise ValueError("El maestro de ítems está vacío: nada que analizar.")
    if not movimientos:
        raise ValueError("No hay movimientos: no se puede construir historia.")

    # ---- Rango global del dataset (todos los movimientos) ----
    fechas = [m["fecha"] for m in movimientos]
    fecha_min, fecha_max = min(fechas), max(fechas)
    idx_ini_global = _indice_mes(fecha_min)
    idx_fin_global = _indice_mes(fecha_max)
    meses_globales = idx_fin_global - idx_ini_global + 1

    if reparto is None:
        reparto = Counter(m["reparto"] for m in movimientos).most_common(1)[0][0]
    if fecha_corte is None:
        cortes = [s["fecha_corte"] for s in stock.values()
                  if s.get("fecha_corte")]
        fecha_corte = max(cortes) if cortes else fecha_max

    # ---- Consumos mensuales por ítem (solo tipo CONSUMO) ----
    consumo_mensual = defaultdict(lambda: defaultdict(float))
    for mov in movimientos:
        if mov["tipo"] == "CONSUMO":
            consumo_mensual[mov["codigo"]][_indice_mes(mov["fecha"])] += \
                mov["cantidad"]

    items = []
    for ficha in maestro:
        items.append(_analizar_item(
            ficha, consumo_mensual.get(ficha["codigo"], {}),
            stock.get(ficha["codigo"]), idx_fin_global))
    clasificar_abc(items)  # asigna 'abc' sobre los mismos dicts

    # ---- KPIs (misma estructura y fórmulas que construir_dataset) ----
    capital_stock = 0
    valor_anual_demanda = 0
    for it in items:
        capital_stock += it["valorStock"]
    for it in items:
        valor_anual_demanda += it["valorAnual"]
    capital_exceso = 0.0
    for it in items:
        if it["estado"] == "EXCESO":
            capital_exceso += max(0, it["stock"] - it["maxLevel"]) * it["costo"]

    kpi = {
        "nItems": len(items),
        "quiebres": sum(1 for i in items if i["estado"] == "QUIEBRE"),
        "reponer": sum(1 for i in items if i["estado"] == "REPONER"),
        "excesos": sum(1 for i in items if i["estado"] == "EXCESO"),
        "capitalStock": capital_stock,
        "capitalExceso": capital_exceso,
        "valorAnualDemanda": valor_anual_demanda,
        "criticosRiesgo": sum(1 for i in items
                              if i["crit"] == "V"
                              and i["estado"] in ("QUIEBRE", "REPONER")),
    }
    vitales_quiebre = sum(1 for i in items
                          if i["crit"] == "V" and i["estado"] == "QUIEBRE")
    kpi["disponibilidad"] = max(60, redondeo_js(94 - vitales_quiebre * 4.5))
    kpi["ahorroPotencial"] = redondeo_js(kpi["capitalExceso"] * 0.5
                                         + kpi["valorAnualDemanda"] * 0.03)

    # ---- Informe de calidad de datos (README_DATOS regla 4) ----
    calidad = {
        "sin_movimientos": [it["id"] for it in items
                            if it["mesesHistoria"] == 0],
        "sin_stock": [it["id"] for it in items
                      if it["id"] not in stock],
        "historia_corta": [
            {"codigo": it["id"], "meses": it["mesesHistoria"]}
            for it in items
            if 0 < it["mesesHistoria"] < MESES_POLITICA_MINIMOS],
        "historia_bajo_minimo": [
            {"codigo": it["id"], "meses": it["mesesHistoria"]}
            for it in items
            if MESES_POLITICA_MINIMOS <= it["mesesHistoria"] < MESES_MINIMO_UTIL],
        "fechas_fuera_de_rango": [
            {"codigo": m["codigo"], "fecha": m["fecha"], "tipo": m["tipo"]}
            for m in movimientos if m["fecha"] > fecha_corte],
    }

    labels = [_etiqueta_mes(i)
              for i in range(idx_ini_global, idx_fin_global + 1)]
    fc_labels = [_etiqueta_mes(idx_fin_global + 1 + k)
                 for k in range(HORIZONTE_PRONOSTICO)]

    return {
        "items": items,
        "kpi": kpi,
        "labels": labels,
        "fcLabels": fc_labels,
        "meses_historia": meses_globales,
        "rango_fechas": {"desde": fecha_min, "hasta": fecha_max},
        "fecha_corte": fecha_corte,
        "reparto": reparto,
        "calidad_datos": calidad,
    }


def _analizar_item(ficha, consumos_por_mes, fila_stock, idx_fin_global):
    """Analiza un ítem importado con las reglas del docstring del módulo."""
    crit = ficha["crit"]
    lt_m = ficha["lt"] / 30  # lead time en meses, igual que el motor

    # Serie: del primer mes con consumo del ítem al fin del rango global
    if consumos_por_mes:
        idx_ini = min(consumos_por_mes)
        serie = [consumos_por_mes.get(i, 0.0)
                 for i in range(idx_ini, idx_fin_global + 1)]
    else:
        serie = []
    meses_historia = len(serie)

    ceros = sum(1 for v in serie if v == 0)
    intermitente = bool(serie) and (ceros / len(serie)) >= UMBRAL_INTERMITENCIA
    politica_minimos = meses_historia < MESES_POLITICA_MINIMOS

    # Demanda media: últimos 12 meses o los que haya (0 sin historia)
    if serie:
        cola = serie[-12:]
        d_prom = sum(cola) / len(cola)
    else:
        d_prom = 0.0

    if politica_minimos:
        # Regla conservadora sin estadística (ver docstring, regla 3)
        modelo_nombre = "minimos"
        media_total = (sum(serie) / len(serie)) if serie else 0.0
        sigma = _desviacion_muestral(serie, media_total)
        mape = None
        pronostico = [d_prom] * HORIZONTE_PRONOSTICO
        ss = math.ceil(d_prom * FACTOR_MINIMOS[crit])
    else:
        modelo = croston_lite(serie) if intermitente else holt(serie)
        modelo_nombre = "croston" if intermitente else "holt"
        sigma = modelo["sigma"]
        mape = modelo["mape"]
        pronostico = modelo["forecast"]
        ss = math.ceil(Z[crit] * sigma * math.sqrt(max(lt_m, 0.25)))

    rop = math.ceil(d_prom * lt_m + ss)
    d_anual = d_prom * 12
    eoq = max(1, redondeo_js(math.sqrt(
        (2 * d_anual * costo_orden(ficha)) / (TASA_POSESION * ficha["costo"]))))
    nivel_max = rop + eoq

    existencia = fila_stock["existencia"] if fila_stock else 0.0

    diario = d_prom / 30
    dias_quiebre = math.floor(existencia / diario) if diario > 0 else 999
    if existencia == 0:
        estado = "QUIEBRE"
    elif existencia <= rop:
        estado = "REPONER"
    elif existencia > nivel_max * 1.1:
        estado = "EXCESO"
    else:
        estado = "OK"
    if estado in ("QUIEBRE", "REPONER"):
        # ceil por si la existencia importada es fraccionaria (regla 4)
        sugerido = max(eoq, math.ceil(rop + eoq - existencia))
    else:
        sugerido = 0

    if serie:
        media = sum(serie) / len(serie)
        cv = (_desviacion_muestral(serie, media) / media) if media > 0 else 0.0
    else:
        cv = 0.0

    return {
        # ficha maestro (mismas claves que el motor simulado)
        "id": ficha["codigo"],
        "nombre": ficha["nombre"],
        "cat": ficha["categoria"],
        "um": ficha["unidad"],
        "costo": ficha["costo"],
        "crit": crit,
        "lt": ficha["lt"],
        "imp": ficha["imp"],
        "proveedor": ficha.get("proveedor"),
        # resultados del análisis (mismos redondeos que el motor)
        "hist": serie,
        "forecast": [redondeo_js(max(0.0, v) * 10) / 10 for v in pronostico],
        "sigma": redondeo_js(sigma * 10) / 10,
        "mape": redondeo_js(mape) if mape else None,
        "dAvg": redondeo_js(d_prom * 10) / 10,
        "ss": ss, "rop": rop, "eoq": eoq, "maxLevel": nivel_max,
        "stock": existencia,
        "diasQuiebre": dias_quiebre, "estado": estado, "sugerido": sugerido,
        "cv": redondeo_js(cv * 100) / 100,
        "valorStock": redondeo_js(existencia * ficha["costo"]),
        "valorAnual": redondeo_js(d_anual * ficha["costo"]),
        "xyz": "X" if cv < 0.5 else ("Y" if cv < 1 else "Z"),
        # metadatos propios de la importación
        "intermitente": intermitente,
        "politica_minimos": politica_minimos,
        "mesesHistoria": meses_historia,
        "modelo": modelo_nombre,
    }
