"""SARP-Naval · Backtesting de pronóstico con origen móvil (tarea 2.2c).

HACE MEDIBLE el KPI comprometido (corrección aprobada 11-jul-2026):
"MAPE <= 25% en clase A de demanda REGULAR · MASE < 1 en ítems
INTERMITENTES". El módulo valida los modelos de pronóstico del motor
(Holt y Croston) con una evaluación temporal HONESTA — origen móvil,
sin fuga de datos del futuro — y reporta el error escalado (MASE) en
demanda intermitente y el error porcentual (MAPE) en demanda regular.

Módulo PURO: no importa FastAPI ni toca SQL. Reutiliza las funciones de
pronóstico canónicas del paquete motor (holt, croston_lite) — NO
reimplementa ninguna fórmula de pronóstico — y el criterio de
intermitencia de analisis_real, para que el backtest evalúe EXACTAMENTE
los mismos modelos que produce la app en la demo y en los datos reales.

=====================================================================
DEFINICIONES Y FÓRMULAS (documentadas para sustentación técnica)
=====================================================================

1. ORIGEN MÓVIL (rolling-origin, validación temporal).
   Para una serie de longitud N se recorre un "origen" t desde t0 hasta
   N-1. En cada origen se ENTRENA el modelo únicamente con los primeros
   t meses (serie[0:t]) y se pronostica el horizonte h = 1..H; el
   pronóstico del paso h se compara contra el valor real serie[t+h-1]
   cuando esa posición existe. NUNCA se usan datos en posiciones >= t
   para entrenar: no hay fuga temporal (el pronóstico del origen t
   depende solo de serie[0:t] y se compara contra serie[t : t+H]).
   Al avanzar el origen hacia el final, los horizontes largos se quedan
   sin dato real y simplemente no se evalúan en ese origen.

2. MASE — Mean Absolute Scaled Error (Hyndman & Koehler, 2006).
       MASE = mean(|e_t|) / escala
   donde e_t = real_t - pronostico_t y la ESCALA es el MAE del
   pronóstico ingenuo naïve-1 IN-SAMPLE sobre el tramo de entrenamiento:
       escala = mean(|y_i - y_{i-1}|)  para i = 1..t0-1
   (se toma el tramo inicial serie[0:t0], estrictamente anterior a todo
   origen evaluado, de modo que la escala tampoco incorpora información
   del futuro). MASE < 1 significa "mejor que el pronóstico ingenuo".
   Es válido con ceros (no divide por el real). BORDE: si el tramo de
   escala es constante o tiene < 2 puntos, el denominador es 0; en ese
   caso MASE = None (documentado, sin excepción).

3. MAPE — Mean Absolute Percentage Error, SOLO demanda regular.
       MAPE = mean(|e_t / y_t|) * 100   sobre el tramo evaluado
   El MAPE es matemáticamente inválido con demanda intermitente porque
   divide por y_t = 0 (Hyndman, 2006). Por eso: si el tramo evaluado
   contiene algún real = 0, el MAPE se marca NO APLICABLE (None) y la
   exactitud se reporta con MASE. Se expresa en PORCENTAJE (igual que
   motor.holt), para comparar directo contra el umbral de 25%.

4. RMSE — raíz del error cuadrático medio: sqrt(mean(e_t^2)).

5. CLASIFICACIÓN regular vs intermitente: se reutiliza el criterio de
   analisis_real (proporción de meses en cero >= UMBRAL_INTERMITENCIA,
   por defecto 0.40). Los intermitentes se pronostican y evalúan con
   croston_lite; los regulares con holt.

   OJO — dos rutas eligen el modelo de forma distinta (por diseño):
   * La ruta de DATOS REALES (analisis_real) y este BACKTEST derivan el
     modelo de la SERIE observada (regla es_intermitente sobre la serie).
   * El DEMO simulado (motor.construir_dataset) fija el modelo por el
     FLAG 'intermitente' del catálogo (catalogo.py), no por la serie.
   Ambos criterios coinciden en casi todo el catálogo, pero para un
   puñado de ítems "de frontera" —marcados intermitentes en el catálogo
   pero con < 40% de meses en cero en la serie generada— divergen: el
   demo muestra un pronóstico Croston mientras el backtest los tabula
   como tipo='regular'/método='holt'. En el dataset simulado sembrado
   (semilla 20260710) son 5 ítems: 2815-EC-0105, 2815-EC-0109,
   2815-EC-0111, 5895-EC-0401 y 2815-EC-0603. La divergencia NO afecta
   los KPIs comprometidos: esos 5 tienen algún mes en cero en su tramo
   evaluado (MAPE no aplicable, mape=None), así que no entran al pool
   del "MAPE clase A regular"; y al tener < 40% de ceros quedan
   correctamente fuera del pool intermitente del MASE. Se documenta
   aquí porque un jurado puede cruzar ambas vistas: el backtest evalúa
   el modelo que la RUTA DE DATOS REALES realmente serviría, que es la
   vista relevante para la validación de exactitud.
"""

import math

from .analisis_real import UMBRAL_INTERMITENCIA
from .motor import croston_lite, holt

__all__ = [
    "metricas_pronostico",
    "backtest_item",
    "backtest_dataset",
    "escala_naive",
    "evaluar_origen",
    "es_intermitente",
    "T0_POR_DEFECTO",
    "HORIZONTE_POR_DEFECTO",
    "UMBRAL_INTERMITENCIA",
]

# Origen inicial por defecto: 24 meses de entrenamiento antes del primer
# pronóstico (dos años de historia, criterio conservador para que sigma
# y tendencia sean estables). Horizonte por defecto: 3 meses.
T0_POR_DEFECTO = 24
HORIZONTE_POR_DEFECTO = 3


# ---------------------------------------------------------------------
# Clasificación y escala
# ---------------------------------------------------------------------
def es_intermitente(serie):
    """Clasifica la serie como intermitente con el criterio de analisis_real.

    Intermitente si la proporción de meses en cero es >= UMBRAL_INTERMITENCIA
    (0.40). Serie vacía -> False (no hay demanda observada que clasificar).
    """
    if not serie:
        return False
    ceros = sum(1 for v in serie if v == 0)
    return (ceros / len(serie)) >= UMBRAL_INTERMITENCIA


def escala_naive(serie_entrenamiento):
    """Escala del MASE: MAE del pronóstico ingenuo naïve-1 in-sample.

        escala = mean(|y_i - y_{i-1}|)  para i = 1..len-1

    Es el denominador del MASE (Hyndman & Koehler, 2006). Devuelve None
    (denominador no utilizable) cuando la serie tiene menos de 2 puntos o
    es constante (todas las diferencias 0 -> MAE 0). Devolver None hace
    que el MASE se reporte como None en ese ítem, sin lanzar excepción.
    """
    if len(serie_entrenamiento) < 2:
        return None
    difs = [abs(serie_entrenamiento[i] - serie_entrenamiento[i - 1])
            for i in range(1, len(serie_entrenamiento))]
    mae_naive = sum(difs) / len(difs)
    return mae_naive if mae_naive > 0 else None


# ---------------------------------------------------------------------
# Métricas de exactitud
# ---------------------------------------------------------------------
def metricas_pronostico(reales, pronosticos, escala_entrenamiento):
    """Calcula las métricas de exactitud de un conjunto de pronósticos.

    Parámetros:
    - reales, pronosticos: listas alineadas (mismo largo) de valores
      observados y pronosticados. e_t = real_t - pronostico_t.
    - escala_entrenamiento: MAE naïve-1 in-sample (ver escala_naive);
      None o 0 -> MASE None.

    Devuelve dict:
    - n:    número de puntos evaluados.
    - mae:  media de |e_t|.
    - rmse: sqrt(media de e_t^2).
    - mase: mae / escala_entrenamiento  (None si la escala es None/0).
    - mape: media de |e_t / real_t| * 100 SOLO si todos los reales > 0;
            None si el tramo evaluado contiene algún real = 0 (MAPE no
            aplicable en demanda intermitente, Hyndman 2006).

    Con n = 0 devuelve todas las métricas en None (nada que evaluar).
    """
    n = len(reales)
    if n == 0:
        return {"n": 0, "mae": None, "rmse": None, "mase": None, "mape": None}

    errores = [r - p for r, p in zip(reales, pronosticos)]
    suma_abs = 0.0
    suma_cuad = 0.0
    for e in errores:
        suma_abs += abs(e)
        suma_cuad += e * e
    mae = suma_abs / n
    rmse = math.sqrt(suma_cuad / n)

    if escala_entrenamiento and escala_entrenamiento > 0:
        mase = mae / escala_entrenamiento
    else:
        mase = None

    if all(r > 0 for r in reales):
        suma_pct = 0.0
        for e, r in zip(errores, reales):
            suma_pct += abs(e) / r
        mape = (suma_pct / n) * 100
    else:
        mape = None

    return {"n": n, "mae": mae, "rmse": rmse, "mase": mase, "mape": mape}


# ---------------------------------------------------------------------
# Un solo origen (aislado: sin fuga temporal)
# ---------------------------------------------------------------------
def _pronosticar(entrenamiento, metodo, horizonte):
    """Pronostica `horizonte` pasos reutilizando las funciones del motor.

    metodo ∈ {'holt', 'croston'}. NO reimplementa las fórmulas: delega en
    motor.holt / motor.croston_lite (las mismas que sirve la app).
    """
    if metodo == "holt":
        return holt(entrenamiento, h=horizonte)["forecast"]
    if metodo == "croston":
        return croston_lite(entrenamiento, h=horizonte)["forecast"]
    raise ValueError(
        f"Método de pronóstico desconocido: '{metodo}'. "
        "Use 'holt' o 'croston'.")


def evaluar_origen(serie, metodo, t, horizonte):
    """Errores de un solo origen t (entrena con serie[0:t]).

    Pronostica los pasos h = 1..horizonte y los compara con serie[t+h-1]
    cuando esa posición existe. Devuelve una lista de tuplas
    (h, real, pronostico).

    SIN FUGA TEMPORAL: el resultado depende ÚNICAMENTE de serie[0:t]
    (entrenamiento) y de serie[t : t+horizonte] (reales comparados); es
    decir, de serie[0 : t+horizonte]. Alterar cualquier posición
    >= t+horizonte no cambia esta salida.
    """
    entrenamiento = serie[:t]
    fc = _pronosticar(entrenamiento, metodo, horizonte)
    pares = []
    for h in range(1, horizonte + 1):
        idx = t + h - 1
        if idx < len(serie):
            pares.append((h, serie[idx], fc[h - 1]))
    return pares


# ---------------------------------------------------------------------
# Backtest de un ítem
# ---------------------------------------------------------------------
def backtest_item(serie, metodo, t0=T0_POR_DEFECTO,
                  horizonte=HORIZONTE_POR_DEFECTO):
    """Corre el origen móvil sobre una serie y agrega los errores.

    Parámetros:
    - serie: lista de demanda mensual (>= 0), en orden cronológico.
    - metodo: 'holt' o 'croston' (se reutilizan las funciones del motor).
    - t0: origen inicial (meses de entrenamiento del primer pronóstico).
    - horizonte: pasos H a evaluar en cada origen (1..H).

    Devuelve dict:
    - omitido: True si la serie es demasiado corta (len < t0 + horizonte),
      con `motivo` explicativo y métricas en None. Se exige len >=
      t0 + horizonte para que al menos el primer origen (t0) pueda
      evaluar el horizonte completo.
    - metodo, t0, horizonte, n_origenes, n_evaluaciones, escala.
    - mae, rmse, mase, mape: métricas AGREGADAS sobre todos los pares
      (real, pronóstico) de todos los orígenes y horizontes.
    - por_horizonte: lista con las métricas desagregadas por paso h.

    BORDES:
    - serie corta (len < t0 + horizonte) -> omitido con motivo.
    - escala 0 (serie de entrenamiento constante) -> mase None (ver
      escala_naive), sin excepción.
    """
    n = len(serie)
    minimo = t0 + horizonte
    if n < minimo:
        return {
            "omitido": True,
            "motivo": (f"serie de {n} meses insuficiente para el backtest "
                       f"(se requieren al menos t0+horizonte = {minimo})"),
            "metodo": metodo, "t0": t0, "horizonte": horizonte,
            "n_origenes": 0, "n_evaluaciones": 0, "escala": None,
            "mae": None, "rmse": None, "mase": None, "mape": None,
            "por_horizonte": [],
        }

    # Escala del MASE: tramo inicial serie[0:t0], estrictamente anterior
    # a todo origen evaluado (sin fuga temporal en el denominador).
    escala = escala_naive(serie[:t0])

    reales_todos, pron_todos = [], []
    acum_h = {h: {"reales": [], "pron": []} for h in range(1, horizonte + 1)}
    n_origenes = 0

    for t in range(t0, n):  # orígenes t0, t0+1, ..., n-1
        pares = evaluar_origen(serie, metodo, t, horizonte)
        if pares:
            n_origenes += 1
        for h, real, pron in pares:
            reales_todos.append(real)
            pron_todos.append(pron)
            acum_h[h]["reales"].append(real)
            acum_h[h]["pron"].append(pron)

    agregada = metricas_pronostico(reales_todos, pron_todos, escala)

    por_horizonte = []
    for h in range(1, horizonte + 1):
        m = metricas_pronostico(acum_h[h]["reales"], acum_h[h]["pron"], escala)
        por_horizonte.append({
            "horizonte": h, "n": m["n"], "mae": m["mae"],
            "mase": m["mase"], "mape": m["mape"],
        })

    return {
        "omitido": False, "motivo": None,
        "metodo": metodo, "t0": t0, "horizonte": horizonte,
        "n_origenes": n_origenes, "n_evaluaciones": agregada["n"],
        "escala": escala,
        "mae": agregada["mae"], "rmse": agregada["rmse"],
        "mase": agregada["mase"], "mape": agregada["mape"],
        "por_horizonte": por_horizonte,
    }


# ---------------------------------------------------------------------
# Backtest de un dataset completo (agregación por clase ABC y por tipo)
# ---------------------------------------------------------------------
def backtest_dataset(items_con_series, t0=T0_POR_DEFECTO,
                     horizonte=HORIZONTE_POR_DEFECTO):
    """Corre el backtest sobre un dataset y agrega los resultados.

    Parámetro items_con_series: iterable de dicts con al menos:
    - 'serie': lista de demanda mensual (obligatoria);
    - 'codigo' (o 'id'): identificador del ítem;
    - 'abc': clase ABC ('A'/'B'/'C' o None si no clasificado);
    - 'crit': criticidad VED (opcional, se propaga a la tabla).
    El TIPO (regular/intermitente) y el MÉTODO (holt/croston) se derivan
    del criterio de intermitencia (es_intermitente), NO se leen del dict:
    así el backtest evalúa el modelo que la app realmente elegiría.

    Devuelve dict:
    - resumen: {mape_clase_a_regular, pct_intermitentes_mase_bajo_1,
      n_items_evaluados, n_omitidos, n_items}.
    - por_clase: lista por clase ABC con conteos y métricas ponderadas.
    - por_item: tabla por ítem (código, abc, crit, tipo, método, métricas,
      omitido/motivo).

    PONDERACIÓN del MAPE de clase A regular: media de los MAPE por ítem
    ponderada por su número de evaluaciones (n_evaluaciones). Como el
    MAPE de cada ítem es a su vez la media de sus |e/y|, ponderar por
    n_evaluaciones equivale EXACTAMENTE al MAPE agrupado (pooled) de
    todos los pares (real, pronóstico) de esos ítems. Igual para el MAPE
    ponderado por clase. El '% intermitentes con MASE<1' es la fracción
    de ítems intermitentes evaluados (mase no None) con mase < 1.
    """
    por_item = []
    for it in items_con_series:
        serie = it["serie"]
        codigo = it.get("codigo") or it.get("id")
        intermitente = es_intermitente(serie)
        tipo = "intermitente" if intermitente else "regular"
        metodo = "croston" if intermitente else "holt"

        r = backtest_item(serie, metodo, t0=t0, horizonte=horizonte)
        registro = {
            "codigo": codigo,
            "abc": it.get("abc"),
            "crit": it.get("crit"),
            "tipo": tipo,
            "metodo": metodo,
            "meses_historia": len(serie),
            "omitido": r["omitido"],
            "motivo": r["motivo"],
            "n_origenes": r["n_origenes"],
            "n_evaluaciones": r["n_evaluaciones"],
            "mae": r["mae"],
            "rmse": r["rmse"],
            "mase": r["mase"],
            "mape": r["mape"],
        }
        por_item.append(registro)

    evaluados = [x for x in por_item if not x["omitido"]]
    omitidos = [x for x in por_item if x["omitido"]]

    # ---- MAPE ponderado de clase A regular (KPI de demanda regular) ----
    mape_a_regular = _mape_ponderado(
        x for x in evaluados
        if x["abc"] == "A" and x["tipo"] == "regular" and x["mape"] is not None)

    # ---- % de intermitentes con MASE < 1 (KPI de demanda intermitente) ----
    interm_con_mase = [x for x in evaluados
                       if x["tipo"] == "intermitente" and x["mase"] is not None]
    pct_interm_bajo_1 = _pct_mase_bajo_1(interm_con_mase)

    # ---- Agregación por clase ABC ----
    por_clase = []
    for clase in ("A", "B", "C"):
        del_clase = [x for x in por_item if x["abc"] == clase]
        if not del_clase:
            continue
        eval_clase = [x for x in del_clase if not x["omitido"]]
        regulares = [x for x in eval_clase if x["tipo"] == "regular"]
        intermitentes = [x for x in eval_clase if x["tipo"] == "intermitente"]
        interm_mase = [x for x in intermitentes if x["mase"] is not None]
        por_clase.append({
            "clase": clase,
            "n_items": len(del_clase),
            "n_evaluados": len(eval_clase),
            "n_omitidos": sum(1 for x in del_clase if x["omitido"]),
            "n_regular": len(regulares),
            "n_intermitente": len(intermitentes),
            "mape_regular": _mape_ponderado(
                x for x in regulares if x["mape"] is not None),
            "mase_intermitente": _mase_ponderado(interm_mase),
            "pct_intermitentes_mase_bajo_1": _pct_mase_bajo_1(interm_mase),
        })

    resumen = {
        "n_items": len(por_item),
        "n_items_evaluados": len(evaluados),
        "n_omitidos": len(omitidos),
        "mape_clase_a_regular": mape_a_regular,
        "pct_intermitentes_mase_bajo_1": pct_interm_bajo_1,
        "n_intermitentes_evaluados": len(interm_con_mase),
    }

    return {"resumen": resumen, "por_clase": por_clase, "por_item": por_item}


# ---------------------------------------------------------------------
# Ayudantes de agregación
# ---------------------------------------------------------------------
def _mape_ponderado(registros):
    """MAPE medio ponderado por n_evaluaciones (equivale al MAPE agrupado).

    `registros`: iterable de dicts con 'mape' (no None) y 'n_evaluaciones'.
    Devuelve None si no hay ninguno.
    """
    suma_peso = 0
    suma = 0.0
    for x in registros:
        peso = x["n_evaluaciones"]
        suma += x["mape"] * peso
        suma_peso += peso
    return (suma / suma_peso) if suma_peso else None


def _mase_ponderado(registros):
    """MASE medio ponderado por n_evaluaciones. None si la lista es vacía."""
    suma_peso = 0
    suma = 0.0
    for x in registros:
        peso = x["n_evaluaciones"]
        suma += x["mase"] * peso
        suma_peso += peso
    return (suma / suma_peso) if suma_peso else None


def _pct_mase_bajo_1(registros):
    """Porcentaje (0..100) de registros con mase < 1. None si lista vacía."""
    registros = list(registros)
    if not registros:
        return None
    buenos = sum(1 for x in registros if x["mase"] < 1)
    return (buenos / len(registros)) * 100
