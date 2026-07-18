"""SARP-Naval · Motor analítico — port Python bit-exacto de sarp_core.js.

Sistema de Abastecimiento y Reposición Predictiva — DEMO datos simulados.

Paridad garantizada con el motor JS canónico (01-app/sarp_core.js):
- Un solo PRNG mulberry32 (semilla 20260710) creado FRESCO en cada llamada
  a construir_dataset(); los ítems del catálogo se procesan en orden y el
  consumo de draws replica exactamente la secuencia del JS.
- Redondeo half-up hacia +infinito (Math.round de JS) vía redondeo_js();
  el round() de Python (banker's rounding) NO se usa.
- Mismo orden de operaciones flotantes (sumas secuenciales) para que los
  dobles IEEE-754 coincidan bit a bit.
"""

import math

from .catalogo import CATALOGO
from .prng import crear_gauss, mulberry32

__all__ = [
    "construir_dataset", "holt", "croston_lite", "label_for",
    "N_HIST", "CATALOGO", "SEMILLA",
]

# ---------- Constantes del modelo ----------
SEMILLA = 20260710
MESES = ["ene", "feb", "mar", "abr", "may", "jun",
         "jul", "ago", "sep", "oct", "nov", "dic"]
N_HIST = 36  # jul-2023 .. jun-2026
INICIO = {"y": 2023, "m": 6}  # índice 6 = julio

# Nivel de servicio 99/95/90% según criticidad V/E/D
Z = {"V": 2.326, "E": 1.645, "D": 1.282}
TASA_POSESION = 0.18  # costo anual de posesión (18%)


def costo_orden(item):
    """Costo de emisión de orden en USD: 120 importado, 45 nacional."""
    return 120 if item["imp"] else 45


def redondeo_js(x):
    """Math.round de JS: entero más cercano, empates hacia +infinito.

    NO equivale a floor(x + 0.5): cuando x + 0.5 no es representable en
    IEEE-754 la suma redondea mal (p. ej. x = 0.49999999999999994 da 1
    con floor(x+0.5) pero Math.round da 0). Tampoco equivale a round()
    de Python (banker's rounding). Se compara la parte fraccionaria
    exacta contra 0.5 (x - floor(x) es exacto en IEEE-754 para los
    rangos relevantes). NaN se propaga igual que Math.round(NaN).
    """
    if math.isnan(x):
        return x
    piso = math.floor(x)
    return piso + 1 if x - piso >= 0.5 else piso


def label_for(i):
    """Etiqueta de mes i contada desde jul-2023 (p. ej. 'jul-23')."""
    m = (INICIO["m"] + i) % 12
    y = INICIO["y"] + math.floor((INICIO["m"] + i) / 12)
    return MESES[m] + "-" + str(y)[2:]


# ---------- Generación de demanda histórica ----------
def generar_historial(item, rnd, gauss):
    """Genera 36 meses de demanda simulada consumiendo el PRNG compartido.

    Orden de consumo por mes (idéntico al JS):
    - no intermitente: gauss() = 2 draws;
    - intermitente: 1 draw (test de ocurrencia) + 2 draws de gauss SOLO
      si ocurre (cortocircuito del ternario en JS).
    """
    salida = []
    for i in range(N_HIST):
        m = (INICIO["m"] + i) % 12
        # estacionalidad: pico de operaciones may-sep (mayor actividad)
        estacional = 1 + item["saz"] * math.sin((2 * math.pi * (m - 4)) / 12)
        # crecimiento por llegada de interceptoras: rampa desde mes 22 hasta +55%
        rampa = (1 + 0.55 * max(0, min(1, (i - 22) / 12))) if item["growth"] else 1
        mu = item["base"] * estacional * rampa
        if item.get("intermitente"):
            # demanda intermitente: probabilidad de ocurrencia + tamaño
            p = min(0.85, mu / (mu + 2))
            if rnd() < p:
                d = max(1, redondeo_js(mu / p + gauss() * math.sqrt(mu)))
            else:
                d = 0
        else:
            d = max(0, redondeo_js(mu + gauss() * mu * 0.18))
        salida.append(d)
    return salida


# ---------- Pronóstico: Holt (suavizamiento exponencial doble) ----------
def holt(hist, alpha=0.35, beta=0.12, h=6):
    """Suavizamiento exponencial doble de Holt, calco del JS.

    Acepta None explícito en alpha/beta/h, igual que el operador ?? del
    JS (alpha = alpha ?? 0.35): un payload JSON con campos null recibe
    los mismos defaults que si se omitieran.
    """
    alpha = 0.35 if alpha is None else alpha
    beta = 0.12 if beta is None else beta
    h = 6 if h is None else h
    if not hist:
        # Calco del JS con hist=[]: hist[0] es undefined, la aritmética
        # produce NaN sin lanzar (sigma=0 porque no hay residuales y
        # mape=null). Se replica con NaN explícito en vez de excepción.
        nan = float("nan")
        return {"forecast": [nan] * h, "sigma": 0.0, "mape": None,
                "level": nan, "trend": nan}
    nivel = hist[0]
    tendencia = (hist[min(3, len(hist) - 1)] - hist[0]) / min(3, (len(hist) - 1) or 1)
    ajustados = [nivel]
    for t in range(1, len(hist)):
        nivel_prev = nivel
        ajustados.append(nivel + tendencia)
        nivel = alpha * hist[t] + (1 - alpha) * (nivel + tendencia)
        tendencia = beta * (nivel - nivel_prev) + (1 - beta) * tendencia
    resid = [v - ajustados[t] for t, v in enumerate(hist)]
    n = len(resid)
    suma_cuad = 0
    for r in resid:
        suma_cuad = suma_cuad + r * r
    sigma = math.sqrt(suma_cuad / max(1, n - 2))
    base_mape = [abs(resid[t]) / v for t, v in enumerate(hist) if v > 0]
    if base_mape:
        suma_mape = 0
        for b in base_mape:
            suma_mape = suma_mape + b
        mape = (suma_mape / len(base_mape)) * 100
    else:
        mape = None
    fc = [max(0, nivel + k * tendencia) for k in range(1, h + 1)]
    return {"forecast": fc, "sigma": sigma, "mape": mape,
            "level": nivel, "trend": tendencia}


def croston_lite(hist, h=6):
    """Media simple para intermitentes (Croston simplificado), calco del JS.

    Acepta None explícito en h (equivalente al ?? de JS). Con hist=[]
    replica al JS: p = 0/0 = NaN se propaga sin lanzar (sigma=0).
    """
    h = 6 if h is None else h
    if not hist:
        nan = float("nan")
        return {"forecast": [nan] * h, "sigma": 0.0, "mape": None,
                "level": nan, "trend": 0}
    nz = [v for v in hist if v > 0]
    p = len(nz) / len(hist)  # frecuencia de ocurrencia
    if nz:
        suma_nz = 0
        for v in nz:
            suma_nz = suma_nz + v
        tamano = suma_nz / len(nz)
    else:
        tamano = 0
    media = p * tamano
    suma_var = 0
    for v in hist:
        suma_var = suma_var + (v - media) ** 2
    varianza = suma_var / max(1, len(hist) - 1)
    return {"forecast": [media] * h, "sigma": math.sqrt(varianza),
            "mape": None, "level": media, "trend": 0}


# ---------- Análisis por ítem ----------
def analizar_item(item, rnd, gauss):
    """Analiza un ítem del catálogo: pronóstico, SS, ROP, EOQ, estado."""
    hist = generar_historial(item, rnd, gauss)
    modelo = croston_lite(hist) if item.get("intermitente") else holt(hist)
    d_prom = sum(hist[-12:]) / 12          # demanda media últimos 12 meses
    lt_m = item["lt"] / 30                 # lead time en meses
    ss = math.ceil(Z[item["crit"]] * modelo["sigma"] * math.sqrt(max(lt_m, 0.25)))
    rop = math.ceil(d_prom * lt_m + ss)
    d_anual = d_prom * 12
    eoq = max(1, redondeo_js(math.sqrt(
        (2 * d_anual * costo_orden(item)) / (TASA_POSESION * item["costo"]))))
    nivel_max = rop + eoq

    # stock actual simulado: mezcla de situaciones (quiebre / bajo ROP / normal / exceso)
    # La rama de quiebre (r < 0.10) NO consume draw adicional; las otras sí.
    r = rnd()
    if r < 0.10:
        stock = 0                                              # quiebre
    elif r < 0.30:
        stock = redondeo_js(rop * (0.25 + 0.6 * rnd()))        # bajo ROP
    elif r < 0.85:
        stock = redondeo_js(rop + eoq * rnd())                 # normal
    else:
        stock = redondeo_js(nivel_max * (1.15 + 0.7 * rnd()))  # exceso

    diario = d_prom / 30
    dias_quiebre = math.floor(stock / diario) if diario > 0 else 999
    if stock == 0:
        estado = "QUIEBRE"
    elif stock <= rop:
        estado = "REPONER"
    elif stock > nivel_max * 1.1:
        estado = "EXCESO"
    else:
        estado = "OK"
    sugerido = max(eoq, rop + eoq - stock) if estado in ("QUIEBRE", "REPONER") else 0

    media = sum(hist) / len(hist)
    suma_var = 0
    for x in hist:
        suma_var = suma_var + (x - media) ** 2
    varianza = suma_var / max(1, len(hist) - 1)
    cv = math.sqrt(varianza) / media if media > 0 else 0

    resultado = dict(item)
    # OJO truthiness JS: mape 0 o None se reporta como None (null)
    resultado.update({
        "hist": hist,
        "forecast": [redondeo_js(v * 10) / 10 for v in modelo["forecast"]],
        "sigma": redondeo_js(modelo["sigma"] * 10) / 10,
        "mape": redondeo_js(modelo["mape"]) if modelo["mape"] else None,
        "dAvg": redondeo_js(d_prom * 10) / 10,
        "ss": ss, "rop": rop, "eoq": eoq, "maxLevel": nivel_max, "stock": stock,
        "diasQuiebre": dias_quiebre, "estado": estado, "sugerido": sugerido,
        "cv": redondeo_js(cv * 100) / 100,
        "valorStock": redondeo_js(stock * item["costo"]),
        "valorAnual": redondeo_js(d_anual * item["costo"]),
        # xyz se clasifica con el cv SIN redondear, igual que el JS
        "xyz": "X" if cv < 0.5 else ("Y" if cv < 1 else "Z"),
    })
    return resultado


def clasificar_abc(items):
    """Clasificación ABC por valor anual (Pareto 80/95), calco del JS.

    El orden de `items` en la salida es el del catálogo: la etiqueta se
    asigna al MISMO dict a través de la lista ordenada (sort estable).
    """
    ordenados = sorted(items, key=lambda it: it["valorAnual"], reverse=True)
    total = 0
    for it in ordenados:
        total = total + it["valorAnual"]
    if total == 0:
        # Calco del JS: con total=0, acc/total = NaN y las comparaciones
        # NaN <= 0.80 / NaN <= 0.95 son false, así que todos son 'C'.
        for it in ordenados:
            it["abc"] = "C"
        return items
    acumulado = 0
    for it in ordenados:
        acumulado += it["valorAnual"]
        if acumulado / total <= 0.80:
            it["abc"] = "A"
        elif acumulado / total <= 0.95:
            it["abc"] = "B"
        else:
            it["abc"] = "C"
    return items


def construir_dataset():
    """Equivalente exacto de buildDataset() de sarp_core.js.

    Crea un PRNG fresco con semilla 20260710 en CADA llamada, por lo que
    la salida es idéntica y determinista en cada invocación (equivale a
    la primera llamada tras cargar el módulo JS, que es lo que capturó
    el JSON de referencia).
    """
    rnd = mulberry32(SEMILLA)
    gauss = crear_gauss(rnd)
    items = clasificar_abc([analizar_item(it, rnd, gauss) for it in CATALOGO])

    capital_stock = 0
    valor_anual_demanda = 0
    for it in items:
        capital_stock = capital_stock + it["valorStock"]
    for it in items:
        valor_anual_demanda = valor_anual_demanda + it["valorAnual"]
    capital_exceso = 0
    for it in items:
        if it["estado"] == "EXCESO":
            capital_exceso = capital_exceso + max(0, it["stock"] - it["maxLevel"]) * it["costo"]

    kpi = {
        "nItems": len(items),
        "quiebres": sum(1 for i in items if i["estado"] == "QUIEBRE"),
        "reponer": sum(1 for i in items if i["estado"] == "REPONER"),
        "excesos": sum(1 for i in items if i["estado"] == "EXCESO"),
        "capitalStock": capital_stock,
        "capitalExceso": capital_exceso,
        "valorAnualDemanda": valor_anual_demanda,
        "criticosRiesgo": sum(1 for i in items
                              if i["crit"] == "V" and i["estado"] in ("QUIEBRE", "REPONER")),
    }
    # alistamiento estimado de las unidades de la familia ancla: proxy según vitales en quiebre
    vitales_quiebre = sum(1 for i in items
                          if i["crit"] == "V" and i["estado"] == "QUIEBRE")
    kpi["disponibilidad"] = max(60, redondeo_js(94 - vitales_quiebre * 4.5))
    # ahorro potencial: 50% del capital en exceso + 3% del valor anual de demanda
    kpi["ahorroPotencial"] = redondeo_js(kpi["capitalExceso"] * 0.5
                                         + kpi["valorAnualDemanda"] * 0.03)

    labels = [label_for(i) for i in range(N_HIST)]
    fc_labels = [label_for(N_HIST + i) for i in range(6)]
    return {
        "items": items, "kpi": kpi, "labels": labels, "fcLabels": fc_labels,
        "generado": "10-jul-2026",
        "reparto": "Reparto guardacostas SUBNOR (referencial)",
    }
