"""SARP-Naval · Selector de régimen de política de inventario.

Decide, ítem por ítem y con criterio publicado, QUÉ política de
inventario le corresponde y, en consecuencia, si el ítem es elegible
para el optimizador de alistamiento (`alistamiento.py`).

POR QUÉ EXISTE ESTE MÓDULO
--------------------------
El optimizador de alistamiento evalúa la disponibilidad de la
plataforma tratándola como un SISTEMA EN SERIE: la lancha necesita
TODOS sus ítems críticos a la vez, de modo que

    A_conjunto = PRODUCTO_i  P(ítem i disponible)

Esa fórmula solo tiene sentido bajo dos condiciones, y este módulo las
declara en vez de esconderlas:

    (a) El ítem debe IMPEDIR OPERAR si falta — código de esencialidad 1
        del DoD (ver `esencialidad.py`). ATENCIÓN: NO es lo mismo que
        la criticidad VED. VED es gestión de inventario («¿cuánto duele
        que falte?»); la esencialidad es ingeniería de misión («¿zarpa
        o no zarpa?»). Son ejes ORTOGONALES, y confundirlos es un error
        medido y documentado por la Armada de EE. UU. (ADA171776: «Almost
        every ship installed item is currently coded 'vital'»). Una
        versión anterior de este módulo filtraba por V/E y metía 37 de
        42 ítems en el producto en serie: el modelo daba por amarrada la
        lancha por la falta de una lata de pintura.

    (b) El ítem debe tener una TASA DE DEMANDA estimable. El modelo de
        backorders necesita lambda = demanda esperada durante el lead
        time. Un ítem bajo política de mínimos (historia < 18 meses,
        dossier §5.5) no tiene sigma confiable ni lambda creíble: si
        entrara, aportaría un número inventado con decimales.

NOTA DE DISEÑO (verificada en el catálogo real, 16-jul-2026)
------------------------------------------------------------
Una versión anterior de este selector exigía además EOQ <= 2 (lote
óptimo unitario), porque el modelo METRIC clásico (Sherbrooke, 1968)
asume reposición uno-a-uno. Se ejecutó contra el catálogo real y ese
criterio dejaba pasar UN SOLO ítem de 42 (1,4 % del gasto): SARP
gestiona CONSUMIBLES con lotes económicos, no reparables uno-a-uno.

La solución no fue relajar el criterio —eso habría sido aplicar METRIC
fuera de su dominio— sino usar en el optimizador la fórmula de
backorders esperados de la política (Q, r) (Hadley y Whitin, 1963), que
admite lotes de cualquier tamaño y se reduce EXACTAMENTE al caso
base-stock cuando Q = 1. Con esa formulación el EOQ deja de ser una
frontera: el modelo es válido con lotes, y la frontera honesta es la
que declaran (a) y (b).

CRITERIO (todo publicado y auditable)
-------------------------------------
1. PATRÓN DE DEMANDA — cortes de Syntetos, Boylan y Croston (2005),
   refinados por Kostenko y Hyndman (2006):

       ADI = intervalo medio entre demandas = n_periodos / n_periodos_no_cero
       CV2 = (sigma_tamanos_no_cero / media_tamanos_no_cero)^2

   con los cortes canónicos ADI = 1.32 y CV2 = 0.49, que parten el
   plano en los cuatro cuadrantes clásicos:

       regular (suave) | errática | intermitente | grumosa

2. ELEGIBILIDAD PARA EL MODELO DE ALISTAMIENTO — las dos condiciones
   (a) y (b) explicadas arriba:

       esencialidad.impide_operar(id)  (código 1 del DoD)
       y  meses_historia >= MESES_HISTORIA_MINIMA  (lambda creíble)

   El régimen resultante es 'alistamiento' (entra al optimizador) o
   'eoq_rop' (se gestiona por lote económico clásico, como hasta hoy).
   Que un ítem NO entre al optimizador no significa que se desatienda:
   sigue gestionado por EOQ/ROP con su criticidad VED. Simplemente deja
   de contarse como si amarrara la unidad al muelle.

ESTE MÓDULO NO CAMBIA NADA DE LO EXISTENTE
------------------------------------------
Es ADITIVO y de solo lectura. NO altera la selección de modelo de
pronóstico (croston vs. holt) de `analisis_real.py`, ni las fórmulas de
`motor.py`. La paridad bit-exacta del ancla de 42 ítems y los KPI
publicados del dataset guardacostas quedan intactos por construcción: aquí solo
se CLASIFICA, no se recalcula nada.

Referencias
-----------
- Syntetos, A. A., Boylan, J. E., y Croston, J. D. (2005). On the
  categorization of demand patterns. *Journal of the Operational
  Research Society, 56*(5), 495-503.
- Kostenko, A. V., y Hyndman, R. J. (2006). A note on the
  categorization of demand patterns. *Journal of the Operational
  Research Society, 57*(10), 1256-1257.
- Sherbrooke, C. C. (1968). METRIC: A multi-echelon technique for
  recoverable item control. *Operations Research, 16*(1), 122-141.
- Hadley, G., y Whitin, T. M. (1963). *Analysis of Inventory Systems*.
  Prentice-Hall. (Backorders esperados de la política (Q, r).)
"""

from .esencialidad import IMPIDE_OPERAR, codigo_de, impide_operar

__all__ = [
    "CORTE_ADI",
    "CORTE_CV2",
    "MESES_HISTORIA_MINIMA",
    "adi",
    "cv2_tamanos",
    "patron_demanda",
    "clasificar_regimen",
    "resumen_regimen",
]

# --- Cortes canónicos de la literatura (Syntetos-Boylan-Croston 2005;
# Kostenko-Hyndman 2006). NO son parámetros ajustables a conveniencia:
# son las fronteras publicadas y por eso el criterio es auditable.
CORTE_ADI = 1.32
CORTE_CV2 = 0.49

# --- Frontera del modelo de alistamiento (condiciones (a) y (b)).
# La condición (a) NO vive aquí: vive en esencialidad.py, con la escala
# doctrinaria del DoD. Este módulo la consulta, no la redefine.

# Historia mínima (meses) para que lambda sea creíble. Coincide con
# MESES_POLITICA_MINIMOS de analisis_real.py (dossier §5.5): por debajo
# de este umbral el ítem se gestiona por política de mínimos y no tiene
# tasa de demanda estimable.
MESES_HISTORIA_MINIMA = 18


def adi(serie):
    """Intervalo medio entre demandas (Average Demand Interval).

    ADI = n_periodos / n_periodos_con_demanda. Un ADI de 1.0 significa
    demanda en todos los periodos; 4.0, demanda una vez cada cuatro.

    Devuelve None si la serie está vacía o no tiene ninguna demanda
    (sin demanda observada no hay patrón que clasificar).
    """
    if not serie:
        return None
    no_cero = sum(1 for v in serie if v > 0)
    if no_cero == 0:
        return None
    return len(serie) / no_cero


def cv2_tamanos(serie):
    """Cuadrado del coeficiente de variación de los TAMAÑOS de demanda.

    Se calcula solo sobre los periodos con demanda > 0 (los ceros son
    intervalos, no tamaños: incluirlos mezclaría las dos dimensiones que
    el criterio ADI/CV2 separa deliberadamente).

    Devuelve None si no hay demanda. Con una sola observación devuelve
    0.0 (no hay dispersión medible: es el valor conservador).
    """
    if not serie:
        return None
    tamanos = [v for v in serie if v > 0]
    if not tamanos:
        return None
    if len(tamanos) == 1:
        return 0.0
    media = sum(tamanos) / len(tamanos)
    if media <= 0:
        return 0.0
    var = sum((v - media) ** 2 for v in tamanos) / (len(tamanos) - 1)
    return var / (media ** 2)


def patron_demanda(valor_adi, valor_cv2):
    """Cuadrante de Syntetos-Boylan-Croston a partir de ADI y CV2.

    Devuelve 'regular', 'erratica', 'intermitente', 'grumosa' o None si
    falta cualquiera de los dos estadísticos.
    """
    if valor_adi is None or valor_cv2 is None:
        return None
    intermitente = valor_adi > CORTE_ADI
    variable = valor_cv2 > CORTE_CV2
    if intermitente and variable:
        return "grumosa"
    if intermitente:
        return "intermitente"
    if variable:
        return "erratica"
    return "regular"


def clasificar_regimen(item):
    """Clasifica un ítem ya analizado y decide su régimen de política.

    Recibe el dict que producen `motor.analizar()` o
    `analisis_real._analizar_item()` — usa solo claves que ambos ya
    exponen: 'id', 'hist' (serie mensual), 'crit'.

    Devuelve un dict ADITIVO (no muta el ítem) con:
        adi, cv2      -- estadísticos del patrón (None si no clasificable)
        patron        -- cuadrante SBC o None
        esencialidad  -- código DoD (1/3/5/6/7) o None si no asignado
        regimen       -- 'alistamiento' | 'eoq_rop'
        elegible_rbs  -- bool: si entra al optimizador de alistamiento
        razon         -- explicación en lenguaje llano (para la ficha
                         de explicabilidad y para la sustentación)
    """
    serie = item.get("hist") or []
    valor_adi = adi(serie)
    valor_cv2 = cv2_tamanos(serie)
    patron = patron_demanda(valor_adi, valor_cv2)

    codigo_item = item.get("id")
    crit = item.get("crit")
    meses = item.get("mesesHistoria")
    if meses is None:
        meses = len(serie)

    # Las dos condiciones de la frontera, evaluadas por separado para
    # poder explicar CUÁL falló.
    detiene = impide_operar(codigo_item)
    cod_esen = codigo_de(codigo_item)
    historia_suficiente = meses >= MESES_HISTORIA_MINIMA

    elegible = bool(detiene and historia_suficiente)
    regimen = "alistamiento" if elegible else "eoq_rop"

    if elegible:
        razon = (
            f"Entra al modelo de alistamiento: su falta deja la unidad "
            f"sin poder operar (esencialidad {cod_esen}), y tiene {meses} "
            f"meses de historia (>= {MESES_HISTORIA_MINIMA}), suficientes "
            f"para estimar su tasa de demanda."
        )
    else:
        faltas = []
        if not detiene:
            if cod_esen is None:
                faltas.append(
                    "no tiene código de esencialidad asignado, así que no "
                    "se asume que impida operar"
                )
            else:
                faltas.append(
                    f"su esencialidad es {cod_esen}: su falta NO deja la "
                    f"unidad sin poder operar (su criticidad de inventario "
                    f"sigue siendo {crit} y se gestiona igual)"
                )
        if not historia_suficiente:
            faltas.append(
                f"tiene {meses} meses de historia (< "
                f"{MESES_HISTORIA_MINIMA}): sin tasa de demanda creíble "
                f"se gestiona por política de mínimos"
            )
        razon = (
            "Fuera del modelo de alistamiento, se gestiona por lote "
            "económico (EOQ/ROP): " + "; ".join(faltas) + "."
        )

    return {
        "adi": None if valor_adi is None else round(valor_adi, 2),
        "cv2": None if valor_cv2 is None else round(valor_cv2, 2),
        "patron": patron,
        "esencialidad": cod_esen,
        "regimen": regimen,
        "elegible_rbs": elegible,
        "razon": razon,
    }


def resumen_regimen(items):
    """Agrega la clasificación de una lista de ítems ya clasificados.

    Cada elemento debe traer las claves de `clasificar_regimen` más
    'costo' y 'valorAnual'. Devuelve los números que se declaran EN
    PANTALLA: cuántos ítems entran al optimizador y qué porcentaje del
    gasto anual representan (la cifra que le interesa a DIGLOG).
    """
    total = len(items)
    elegibles = [i for i in items if i.get("elegible_rbs")]
    gasto_total = sum(i.get("valorAnual", 0.0) or 0.0 for i in items)
    gasto_elegible = sum(i.get("valorAnual", 0.0) or 0.0 for i in elegibles)

    patrones = {}
    for i in items:
        p = i.get("patron") or "sin_clasificar"
        patrones[p] = patrones.get(p, 0) + 1

    return {
        "total_items": total,
        "elegibles_rbs": len(elegibles),
        "pct_items": round(100.0 * len(elegibles) / total, 1) if total else 0.0,
        "gasto_anual_total": round(gasto_total, 2),
        "gasto_anual_elegible": round(gasto_elegible, 2),
        "pct_gasto": (round(100.0 * gasto_elegible / gasto_total, 1)
                      if gasto_total > 0 else 0.0),
        "patrones": patrones,
        "cortes": {"adi": CORTE_ADI, "cv2": CORTE_CV2,
                   "esencialidad_que_entra": IMPIDE_OPERAR,
                   "meses_historia_minima": MESES_HISTORIA_MINIMA},
    }
