"""Paquete motor: motor analítico SARP-Naval (port Python de sarp_core.js).

API pública:
- construir_dataset() -> dict : equivalente exacto de buildDataset() del JS
- holt(hist, alpha=0.35, beta=0.12, h=6)
- croston_lite(hist, h=6)
- label_for(i)
- N_HIST (=36), CATALOGO (42 ítems), SEMILLA (20260710)
"""

from .catalogo import CATALOGO
from .motor import (
    N_HIST,
    SEMILLA,
    construir_dataset,
    croston_lite,
    holt,
    label_for,
)
from .prng import crear_gauss, mulberry32

__all__ = [
    "construir_dataset", "holt", "croston_lite", "label_for",
    "N_HIST", "CATALOGO", "SEMILLA", "mulberry32", "crear_gauss",
]
