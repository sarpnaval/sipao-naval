"""Catálogo simulado de repuestos (unidades guardacostas).

Transcripción literal del CATALOG de sarp_core.js. Los ítems se procesan
EN ESTE ORDEN por el motor (el orden determina el consumo del PRNG).
La clave 'intermitente' solo existe en los ítems que la tienen en el JS
(JSON.stringify omite undefined), para que la comparación de dicts contra
el JSON de referencia sea directa.

crit: V=Vital E=Esencial D=Deseable | lt: lead time en días | imp: importado
"""

__all__ = ["CATALOGO"]

CATALOGO = [
    # --- Motores fuera de borda (familia ancla) ---
    {"id": "2815-EC-0101", "nombre": "Bujía NGK BR8HS-10 (motor F/B 200HP)", "cat": "Motor F/B", "um": "u", "costo": 6.5, "lt": 15, "crit": "E", "imp": False, "base": 260, "saz": 0.25, "growth": True},
    {"id": "2815-EC-0102", "nombre": "Impulsor bomba de agua 200-250HP", "cat": "Motor F/B", "um": "u", "costo": 48, "lt": 45, "crit": "V", "imp": True, "base": 34, "saz": 0.30, "growth": True},
    {"id": "2815-EC-0103", "nombre": "Kit empaques power head 200HP", "cat": "Motor F/B", "um": "kit", "costo": 185, "lt": 60, "crit": "V", "imp": True, "base": 9, "saz": 0.20, "growth": True},
    {"id": "2815-EC-0104", "nombre": "Termostato 60°C motor F/B", "cat": "Motor F/B", "um": "u", "costo": 32, "lt": 45, "crit": "E", "imp": True, "base": 18, "saz": 0.15, "growth": True},
    {"id": "2815-EC-0105", "nombre": "Hélice acero inox 3 palas 15.5x17", "cat": "Motor F/B", "um": "u", "costo": 620, "lt": 75, "crit": "E", "imp": True, "base": 5, "saz": 0.35, "growth": True, "intermitente": True},
    {"id": "2815-EC-0106", "nombre": "Ánodo de sacrificio motor F/B", "cat": "Motor F/B", "um": "u", "costo": 14, "lt": 30, "crit": "E", "imp": False, "base": 95, "saz": 0.20, "growth": True},
    {"id": "2815-EC-0107", "nombre": "Filtro de combustible separador agua", "cat": "Motor F/B", "um": "u", "costo": 22, "lt": 20, "crit": "V", "imp": False, "base": 120, "saz": 0.25, "growth": True},
    {"id": "2815-EC-0108", "nombre": "Bomba de combustible alta presión F/B", "cat": "Motor F/B", "um": "u", "costo": 410, "lt": 90, "crit": "V", "imp": True, "base": 4, "saz": 0.20, "growth": True, "intermitente": True},
    {"id": "2815-EC-0109", "nombre": "Cable de dirección 14 pies", "cat": "Motor F/B", "um": "u", "costo": 145, "lt": 45, "crit": "E", "imp": True, "base": 7, "saz": 0.15, "growth": True, "intermitente": True},
    {"id": "2815-EC-0110", "nombre": "Kit reparación carburador/inyección", "cat": "Motor F/B", "um": "kit", "costo": 96, "lt": 60, "crit": "E", "imp": True, "base": 12, "saz": 0.25, "growth": True},
    {"id": "2815-EC-0111", "nombre": "Rectificador/regulador de voltaje F/B", "cat": "Motor F/B", "um": "u", "costo": 168, "lt": 60, "crit": "V", "imp": True, "base": 6, "saz": 0.10, "growth": True, "intermitente": True},
    {"id": "2815-EC-0112", "nombre": "Correa de distribución motor F/B 4T", "cat": "Motor F/B", "um": "u", "costo": 58, "lt": 45, "crit": "V", "imp": True, "base": 15, "saz": 0.15, "growth": True},
    # --- Lubricantes y químicos ---
    {"id": "9150-EC-0201", "nombre": "Aceite 2T TC-W3 (galón)", "cat": "Lubricantes", "um": "gal", "costo": 28, "lt": 10, "crit": "V", "imp": False, "base": 420, "saz": 0.30, "growth": True},
    {"id": "9150-EC-0202", "nombre": "Aceite 10W-30 4T marino (galón)", "cat": "Lubricantes", "um": "gal", "costo": 24, "lt": 10, "crit": "V", "imp": False, "base": 310, "saz": 0.25, "growth": True},
    {"id": "9150-EC-0203", "nombre": "Grasa marina anticorrosiva (lb)", "cat": "Lubricantes", "um": "lb", "costo": 9, "lt": 10, "crit": "E", "imp": False, "base": 150, "saz": 0.15, "growth": False},
    {"id": "9150-EC-0204", "nombre": "Aceite hidráulico ISO 68 (galón)", "cat": "Lubricantes", "um": "gal", "costo": 26, "lt": 15, "crit": "E", "imp": False, "base": 85, "saz": 0.10, "growth": False},
    {"id": "6850-EC-0205", "nombre": "Refrigerante motor diésel (galón)", "cat": "Lubricantes", "um": "gal", "costo": 18, "lt": 15, "crit": "E", "imp": False, "base": 95, "saz": 0.10, "growth": False},
    # --- Casco y cubierta ---
    {"id": "2040-EC-0301", "nombre": "Pintura antiincrustante (galón)", "cat": "Casco/Cubierta", "um": "gal", "costo": 145, "lt": 30, "crit": "E", "imp": True, "base": 40, "saz": 0.45, "growth": False},
    {"id": "2040-EC-0302", "nombre": "Ánodo de zinc casco 5 lb", "cat": "Casco/Cubierta", "um": "u", "costo": 35, "lt": 30, "crit": "E", "imp": False, "base": 60, "saz": 0.30, "growth": False},
    {"id": "4030-EC-0303", "nombre": "Cabo de amarre nylon 1.5\" (m)", "cat": "Casco/Cubierta", "um": "m", "costo": 7, "lt": 15, "crit": "D", "imp": False, "base": 210, "saz": 0.20, "growth": False},
    {"id": "2090-EC-0304", "nombre": "Defensa neumática 30x50 cm", "cat": "Casco/Cubierta", "um": "u", "costo": 88, "lt": 30, "crit": "D", "imp": False, "base": 14, "saz": 0.15, "growth": False},
    {"id": "5330-EC-0305", "nombre": "Sello mecánico eje bomba achique", "cat": "Casco/Cubierta", "um": "u", "costo": 52, "lt": 45, "crit": "V", "imp": True, "base": 16, "saz": 0.15, "growth": False},
    # --- Electrónica y navegación ---
    {"id": "5895-EC-0401", "nombre": "Antena VHF marina 8 pies", "cat": "Electrónica", "um": "u", "costo": 130, "lt": 45, "crit": "E", "imp": True, "base": 6, "saz": 0.10, "growth": False, "intermitente": True},
    {"id": "6140-EC-0402", "nombre": "Batería marina AGM 12V 100Ah", "cat": "Electrónica", "um": "u", "costo": 265, "lt": 30, "crit": "V", "imp": False, "base": 22, "saz": 0.20, "growth": True},
    {"id": "5895-EC-0403", "nombre": "Transductor ecosonda P66", "cat": "Electrónica", "um": "u", "costo": 240, "lt": 75, "crit": "E", "imp": True, "base": 3, "saz": 0.10, "growth": False, "intermitente": True},
    {"id": "6230-EC-0404", "nombre": "Reflector LED búsqueda 12V", "cat": "Electrónica", "um": "u", "costo": 95, "lt": 30, "crit": "E", "imp": False, "base": 9, "saz": 0.15, "growth": False},
    {"id": "5895-EC-0405", "nombre": "GPS/plotter 9\" (unidad reemplazo)", "cat": "Electrónica", "um": "u", "costo": 1150, "lt": 90, "crit": "V", "imp": True, "base": 1.5, "saz": 0.10, "growth": False, "intermitente": True},
    # --- Seguridad de vida ---
    {"id": "4220-EC-0501", "nombre": "Chaleco salvavidas SOLAS adulto", "cat": "Seguridad", "um": "u", "costo": 65, "lt": 30, "crit": "V", "imp": False, "base": 45, "saz": 0.20, "growth": True},
    {"id": "4220-EC-0502", "nombre": "Bengala paracaídas roja MK8", "cat": "Seguridad", "um": "u", "costo": 38, "lt": 60, "crit": "V", "imp": True, "base": 30, "saz": 0.15, "growth": False},
    {"id": "4210-EC-0503", "nombre": "Extintor PQS 10 lb marino", "cat": "Seguridad", "um": "u", "costo": 55, "lt": 20, "crit": "V", "imp": False, "base": 18, "saz": 0.10, "growth": False},
    {"id": "4220-EC-0504", "nombre": "Aro salvavidas c/rabiza 30 m", "cat": "Seguridad", "um": "u", "costo": 48, "lt": 20, "crit": "E", "imp": False, "base": 10, "saz": 0.10, "growth": False},
    # --- Motor diésel (corbetas/patrulleras mayores) ---
    {"id": "2815-EC-0601", "nombre": "Filtro aceite motor diésel principal", "cat": "Motor diésel", "um": "u", "costo": 42, "lt": 30, "crit": "V", "imp": True, "base": 55, "saz": 0.10, "growth": False},
    {"id": "2815-EC-0602", "nombre": "Filtro aire motor diésel principal", "cat": "Motor diésel", "um": "u", "costo": 68, "lt": 30, "crit": "E", "imp": True, "base": 30, "saz": 0.10, "growth": False},
    {"id": "2815-EC-0603", "nombre": "Inyector diésel reconstruido", "cat": "Motor diésel", "um": "u", "costo": 320, "lt": 75, "crit": "V", "imp": True, "base": 8, "saz": 0.10, "growth": False, "intermitente": True},
    {"id": "2815-EC-0604", "nombre": "Turbocargador (reemplazo programado)", "cat": "Motor diésel", "um": "u", "costo": 2850, "lt": 120, "crit": "V", "imp": True, "base": 0.8, "saz": 0.10, "growth": False, "intermitente": True},
    {"id": "2930-EC-0605", "nombre": "Bomba agua salada refrigeración", "cat": "Motor diésel", "um": "u", "costo": 540, "lt": 90, "crit": "V", "imp": True, "base": 2.5, "saz": 0.10, "growth": False, "intermitente": True},
    {"id": "2815-EC-0606", "nombre": "Kit empaquetadura culata diésel", "cat": "Motor diésel", "um": "kit", "costo": 410, "lt": 90, "crit": "E", "imp": True, "base": 3, "saz": 0.10, "growth": False, "intermitente": True},
    # --- Consumibles de mantenimiento ---
    {"id": "5350-EC-0701", "nombre": "Lija de agua #400 (pliego)", "cat": "Consumibles", "um": "u", "costo": 0.9, "lt": 7, "crit": "D", "imp": False, "base": 480, "saz": 0.30, "growth": False},
    {"id": "8030-EC-0702", "nombre": "Sellante marino 3M 5200 (tubo)", "cat": "Consumibles", "um": "u", "costo": 19, "lt": 20, "crit": "E", "imp": False, "base": 65, "saz": 0.20, "growth": False},
    {"id": "9505-EC-0703", "nombre": "Alambre acero inox amarre (rollo)", "cat": "Consumibles", "um": "rollo", "costo": 12, "lt": 10, "crit": "D", "imp": False, "base": 40, "saz": 0.10, "growth": False},
    {"id": "6810-EC-0704", "nombre": "Desengrasante industrial (galón)", "cat": "Consumibles", "um": "gal", "costo": 15, "lt": 10, "crit": "D", "imp": False, "base": 110, "saz": 0.15, "growth": False},
    {"id": "5975-EC-0705", "nombre": "Cinta autofundente eléctrica (rollo)", "cat": "Consumibles", "um": "rollo", "costo": 8, "lt": 15, "crit": "E", "imp": False, "base": 70, "saz": 0.10, "growth": False},
]
