"""SARP-Naval · Optimizador de alistamiento operativo bajo presupuesto.

Invierte la función objetivo del motor clásico. El motor actual fija un
nivel de servicio por ítem (z según criticidad VED) y suma costos: el
agregado no optimiza nada. Este módulo resuelve el problema inverso,
que es el que la doctrina llama Readiness-Based Sparing (RBS):

    max  A(r) = Π_i P(ítem i disponible | r_i)
    s.a. Σ_i costo_i · r_i ≤ B

El nivel de servicio deja de ser un input decretado y pasa a ser un
OUTPUT deducido, distinto para cada ítem aunque compartan criticidad,
porque depende de la razón (ganancia de alistamiento)/(costo).

POR QUÉ (Q, r) Y NO METRIC CLÁSICO
----------------------------------
METRIC (Sherbrooke, 1968) asume reposición uno-a-uno (base-stock): es
doctrina de REPARABLES. El catálogo de SARP es de CONSUMIBLES con lote
económico (EOQ >> 1): aplicar METRIC ahí es inválido, y el criterio
EOQ<=2 dejaba pasar 1 ítem de 42 (verificado 16-jul-2026). Por eso la
probabilidad de atención se calcula bajo la política (Q, r) de
Hadley-Whitin (1963): la posición de inventario en régimen es uniforme
en {r+1, …, r+Q}, y

    ReadyRate(r, Q, m) = (1/Q) · Σ_{y=r+1}^{r+Q} P(X ≤ y−1),
    con X ~ Poisson(m),  m = λ·LT  (teorema de Palm: solo importa la
    MEDIA del tiempo de reposición, no su distribución).

Cuando Q = 1 la fórmula se reduce EXACTAMENTE a base-stock — verificado
numéricamente en las pruebas (consistencia con el caso METRIC).

QUÉ OPTIMIZA Y QUÉ NO (frontera declarada)
------------------------------------------
- Entra al modelo SOLO el subconjunto elegible del selector de régimen
  (`regimen.py`): ítems cuya falta impide operar (esencialidad 1) y con
  historia suficiente para una λ creíble. La frontera se muestra en
  pantalla, no se esconde.
- El sistema se modela EN SERIE sobre ese subconjunto: la unidad
  necesita todos sus ítems «impide operar» a la vez. Los demás ítems
  degradan (PMC), no detienen — y por eso NO entran al producto.
- El greedy de análisis marginal es exacto SOBRE la envolvente
  eficiente; para un presupuesto arbitrario entre dos vértices se
  reporta el vértice alcanzado (por eso la salida es la CURVA completa,
  no un punto «óptimo» a secas — verificado contra fuerza bruta:
  0/60 de brecha en sus propios vértices).

Referencias: Hadley y Whitin (1963), *Analysis of Inventory Systems*;
Sherbrooke (1968), METRIC, *Operations Research 16*(1); OPNAVINST
4442.5B (RBS, 17-nov-2022); DoD Manual 4140.01 Vol. 2 («will use RBS
methods, where feasible»); ASM/LMI, DTIC ADA320502 (la política de
nivel fijo «say 95 percent» como comparador inferior, Tabla 1-1).
"""

import heapq
import math

__all__ = [
    "ready_rate_qr",
    "alistamiento_conjunto",
    "optimizar",
    "curva_presupuesto",
    "comparar_recortes",
]

# Nivel mínimo de ready-rate para evitar log(0) en ítems sin stock.
_PISO = 1e-12


def _pois_cdf(k, m):
    """P(X <= k) con X ~ Poisson(m). Recursión estable, sin dependencias."""
    if k < 0:
        return 0.0
    p = math.exp(-m)
    acumulado = p
    for x in range(1, k + 1):
        p = p * m / x
        acumulado += p
    return min(1.0, acumulado)


def ready_rate_qr(r, q, m):
    """P(atender la demanda de inmediato) bajo política (Q, r).

    Posición de inventario uniforme en {r+1, …, r+Q} (Hadley-Whitin);
    con q=1 coincide exactamente con base-stock sobre r+1.
    """
    if q <= 0:
        q = 1
    if r < 0:
        return _PISO
    total = sum(_pois_cdf(y - 1, m) for y in range(r + 1, r + q + 1))
    return max(_PISO, min(1.0, total / q))


def _m_de(item):
    """Demanda esperada durante el lead time: m = λ · LT_meses."""
    return max(1e-9, item["lam"] * item["lt_meses"])


def alistamiento_conjunto(items, niveles):
    """A = Π ReadyRate_i: el sistema en serie sobre los ítems elegibles."""
    log_a = 0.0
    for it, r in zip(items, niveles):
        log_a += math.log(ready_rate_qr(int(r), int(it["eoq"]), _m_de(it)))
    return math.exp(log_a)


class _EstadoItem:
    """CDF de Poisson y ventana (Q,r) INCREMENTALES para un ítem.

    ready_rate(r) exige Σ_{k=r}^{r+Q-1} P(X<=k); recalcularla desde cero
    en cada unidad comprada es O(r·Q) y volvía inviable el catálogo real
    (ROP de consumibles en cientos). Aquí la CDF se extiende término a
    término y la ventana se desliza: ws(r+1) = ws(r) − cdf(r) + cdf(r+Q).
    """

    def __init__(self, item):
        self.m = _m_de(item)
        self.q = max(1, int(item["eoq"]))
        self.costo = item["costo"]
        self._pmf = [math.exp(-self.m)]
        self._cdf = [self._pmf[0]]
        self.r = 0
        self.ws = sum(self._cdf_hasta(k) for k in range(0, self.q))

    def _cdf_hasta(self, k):
        while len(self._cdf) <= k:
            x = len(self._pmf)
            self._pmf.append(self._pmf[-1] * self.m / x)
            self._cdf.append(min(1.0, self._cdf[-1] + self._pmf[-1]))
        return self._cdf[k]

    def log_rr(self):
        return math.log(max(_PISO, min(1.0, self.ws / self.q)))

    def ganancia_siguiente(self):
        """Δlog RR de pasar de r a r+1, sin mutar el estado."""
        ws_sig = self.ws - self._cdf_hasta(self.r) + self._cdf_hasta(
            self.r + self.q)
        log_sig = math.log(max(_PISO, min(1.0, ws_sig / self.q)))
        return log_sig - self.log_rr(), ws_sig

    def avanzar(self, ws_sig):
        self.ws = ws_sig
        self.r += 1


def optimizar(items, presupuesto):
    """Asignación por análisis marginal: cada dólar al ítem que más
    alistamiento compra por dólar (Δlog A / costo), partiendo de r=0.

    Devuelve (niveles, gasto, vertices) donde vertices es la lista de
    (gasto_acumulado, alistamiento) de la envolvente eficiente — la
    curva completa, no un punto. Implementación incremental: O(1)
    amortizado por unidad comprada.
    """
    estados = [_EstadoItem(it) for it in items]
    log_a = sum(e.log_rr() for e in estados)
    vertices = [(0.0, math.exp(log_a))]
    monticulo = []
    for k, e in enumerate(estados):
        ganancia, ws_sig = e.ganancia_siguiente()
        if ganancia > 0:
            heapq.heappush(monticulo, (-ganancia / e.costo, k, ws_sig))
    gasto = 0.0
    while monticulo:
        neg_valor, k, ws_sig = heapq.heappop(monticulo)
        e = estados[k]
        if gasto + e.costo > presupuesto:
            continue
        log_a += (-neg_valor) * e.costo
        e.avanzar(ws_sig)
        gasto += e.costo
        vertices.append((gasto, min(1.0, math.exp(log_a))))
        ganancia, ws_sig = e.ganancia_siguiente()
        if ganancia > 1e-15:
            heapq.heappush(monticulo, (-ganancia / e.costo, k, ws_sig))
    return [e.r for e in estados], gasto, vertices


def curva_presupuesto(items, presupuesto_max):
    """Envolvente eficiente completa hasta presupuesto_max, adelgazada
    a ~200 puntos para la pantalla (el primero y el último siempre)."""
    _, _, vertices = optimizar(items, presupuesto_max)
    if len(vertices) <= 200:
        return vertices
    paso = len(vertices) / 200.0
    indices = sorted({0, len(vertices) - 1}
                     | {int(i * paso) for i in range(200)})
    return [vertices[i] for i in indices]


def comparar_recortes(items, niveles_actuales,
                      recortes=(0, 10, 20, 30, 40, 50)):
    """La tabla que decide: recorte lineal (lo que se hace hoy) contra
    asignación optimizada, al mismo presupuesto.

    niveles_actuales = los ROP vigentes del motor clásico (z por VED).
    El recorte lineal reduce cada nivel proporcionalmente; el optimizado
    reasigna el mismo dinero por análisis marginal.
    """
    base = sum(it["costo"] * r for it, r in zip(items, niveles_actuales))
    filas = []
    for pct in recortes:
        b = base * (1 - pct / 100.0)
        lineal = [max(0, int(r * (1 - pct / 100.0)))
                  for r in niveles_actuales]
        a_lineal = alistamiento_conjunto(items, lineal)
        _, gasto_opt, vertices = optimizar(items, b)
        a_opt = vertices[-1][1]
        filas.append({
            "recorte_pct": pct,
            "presupuesto": round(b, 2),
            "alistamiento_lineal": round(a_lineal, 4),
            "alistamiento_optimizado": round(a_opt, 4),
            "gasto_optimizado": round(gasto_opt, 2),
            "ganancia_puntos": round(100 * (a_opt - a_lineal), 1),
        })
    return {"presupuesto_base": round(base, 2), "filas": filas}
