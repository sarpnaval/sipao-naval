"""PRNG determinista (mulberry32) y muestreo gaussiano (Box-Muller).

Port bit-exacto del PRNG de sarp_core.js: mulberry32 opera en dominio
uint32 y divide por 2**32, de modo que la secuencia de dobles IEEE-754
es idéntica a la de V8/Node con la misma semilla.
"""

import math

__all__ = ["mulberry32", "crear_gauss"]


def mulberry32(semilla):
    """Devuelve un generador rnd() en [0, 1) idéntico al mulberry32 de JS.

    Implementación verificada contra Node (primeros 100 valores,
    igualdad exacta a 17 dígitos significativos).
    """
    estado = semilla & 0xFFFFFFFF

    def rnd():
        nonlocal estado
        estado = (estado + 0x6D2B79F5) & 0xFFFFFFFF
        t = ((estado ^ (estado >> 15)) * (estado | 1)) & 0xFFFFFFFF
        m = ((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF
        t = (((t + m) & 0xFFFFFFFF) ^ t) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rnd


def crear_gauss(rnd):
    """Crea un muestreador N(0,1) por Box-Muller ligado al rnd dado.

    Reproduce exactamente el orden de consumo del JS: dos draws u, v
    (con re-draw si alguno sale 0) y luego sqrt(-2*ln(u)) * cos(2*pi*v).
    """

    def gauss():
        u = 0.0
        v = 0.0
        while u == 0.0:
            u = rnd()
        while v == 0.0:
            v = rnd()
        return math.sqrt(-2.0 * math.log(u)) * math.cos(2.0 * math.pi * v)

    return gauss
