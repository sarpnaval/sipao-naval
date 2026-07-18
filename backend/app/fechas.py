"""Formato de fechas de SARP-Naval: dd-mmm-aaaa (regla del proyecto).

Las fechas se ALMACENAN en ISO yyyy-mm-dd (ordenan de forma natural en
SQLite); la API las convierte a dd-mmm-aaaa antes de responder, que es
el formato que ve el usuario (frontend y Swagger).
"""

MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun",
                "jul", "ago", "sep", "oct", "nov", "dic"]


def fecha_larga(fecha_iso):
    """Convierte ISO yyyy-mm-dd en dd-mmm-aaaa (ej. '2026-07-10' → '10-jul-2026').

    Devuelve None si la entrada es None (campos opcionales de la base).
    """
    if fecha_iso is None:
        return None
    anio, mes, dia = fecha_iso.split("-")
    return f"{dia}-{MESES_CORTOS[int(mes) - 1]}-{anio}"


def etiqueta_mes(fecha_iso):
    """Convierte ISO yyyy-mm-dd en etiqueta corta de mes, ej. 'jul-23'."""
    anio, mes = fecha_iso[0:4], int(fecha_iso[5:7])
    return f"{MESES_CORTOS[mes - 1]}-{anio[2:]}"
