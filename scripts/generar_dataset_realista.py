# -*- coding: utf-8 -*-
"""SARP-Naval — Generador del dataset guardacostas realista.

Produce un inventario CREÍBLE de un Escuadrón de Fuerza Litoral / Área
de guardacostas ("Reparto guardacostas SUBNOR (referencial)"): ~125
ítems repartidos en 11 familias reales de repuestos navales, 36 meses de
movimientos (jul-2023 .. jun-2026) y una foto de existencias al corte del
10-jul-2026. La salida se escribe como PLANTILLA IMPORTABLE (tres CSV con
el formato EXACTO de 03-datos/README_DATOS.md) para que la demo se
alimente por la MISMA tubería que usará el piloto real: el importador
(backend.app.importador) parsea/valida los CSV y backend.motor.analisis_real
calcula parámetros, pronósticos, alertas y clasificación. Así el
entregable ejercita el pipeline de datos reales en vivo.

IMPORTANTE: los datos son 100% FICTICIOS y DETERMINISTAS
(random.Random(20260711)). NO provienen de SISLOG ni de ningún dato real.
Por eso viven en 03-datos/simulado/ (no en 03-datos/reales/, con .gitignore).

QUIRKS de calidad de datos deliberados (leves, para que el informe de
calidad del importador tenga algo real que reportar sin que la demo
parezca rota). Documentados también aquí:
  1) Ítem "2815-EC-1029" (Sensor de trim/tilt 300HP, recién catalogado):
     figura en el maestro y en stock pero SIN movimientos de consumo ->
     entra en política de mínimos y aparece en calidad.sin_movimientos.
  2) Ítem "2910-EC-1030" (Filtro Racor serie nueva 300HP): solo ~8 meses
     de historia (parte reciente por incorporación de interceptoras) ->
     política de mínimos y calidad.historia_corta (< 18 meses).
  3) Ítem "5350-EC-1109" (Brocha/rodillo pintura marina): tiene maestro y
     movimientos pero se OMITE su fila de stock (omisión de bodega) ->
     existencia asumida 0 (QUIEBRE) y calidad.sin_stock.

Nota sobre el quirk 3: el ejemplo del pedido ("una fila de stock de un
ítem no catalogado") se sustituyó por "una fila de stock ausente", porque
el importador trata —correctamente— un código de stock inexistente en el
maestro como ERROR BLOQUEANTE (no como advertencia), lo que impediría la
importación. La omisión de una fila de stock es el análogo realista que
sí produce una entrada en el informe de calidad sin bloquear.

Uso (desde 01-app/v1):
    "%USERPROFILE%\\.venvs\\sarp-naval\\Scripts\\python.exe" scripts/generar_dataset_realista.py
"""
import csv
import io
import math
import random
from pathlib import Path

def _raiz_del_proyecto():
    """Raíz del proyecto, o el directorio del script si no cuelga de ella.

    Solo sirve para DECIDIR DÓNDE ESCRIBIR los CSV cuando este archivo se
    ejecuta a mano. Dentro del contenedor publicado el módulo se IMPORTA
    (la siembra usa construir_archivos(), que trabaja en memoria) y vive
    en /app/scripts/, donde no existen cuatro niveles por encima: asumirlo
    reventaba el arranque con IndexError (18-jul-2026). Sin ruta válida no
    hay nada que escribir, así que basta con no fallar al importar.
    """
    aqui = Path(__file__).resolve()
    return aqui.parents[3] if len(aqui.parents) > 3 else aqui.parent


RAIZ = _raiz_del_proyecto()
DIR_SALIDA = RAIZ / "03-datos" / "simulado" / "efla_guardacostas"

SEMILLA = 20260711
REPARTO = "Reparto guardacostas SUBNOR (referencial)"
FECHA_CORTE_ISO = "2026-07-10"
FECHA_CORTE_DMA = "10/07/2026"

# Histórico: jul-2023 .. jun-2026 (36 meses); índice 0 = julio 2023.
N_MESES = 36
ANIO_INICIO = 2023
MES_INICIO = 6  # 0-11 -> 6 = julio

# Columnas EXACTAS de la plantilla (README_DATOS.md).
COLS_MAESTRO = ["codigo", "nombre", "categoria", "unidad",
                "costo_unitario_usd", "criticidad", "lead_time_dias",
                "importado", "proveedor"]
COLS_MOV = ["codigo", "fecha", "tipo", "cantidad", "reparto", "referencia"]
COLS_STOCK = ["codigo", "existencia", "fecha_corte", "ubicacion"]

# Proveedores ficticios (clave -> razón social simulada).
PROV = {
    "YAM": "Yamaha Motor del Ecuador (distribuidor autorizado)",
    "MPI": "Marine Parts Intl. Cía. Ltda.",
    "NAUP": "Náutica del Pacífico S.A.",
    "RMG": "Repuestos Marinos Guayaquil Cía. Ltda.",
    "IND": "Importadora Naval Manta S.A.",
    "DSL": "Suministros Diésel del Litoral S.A.",
    "ELEC": "ElectroMarine Ecuador Cía. Ltda.",
    "NAV": "NavElectronics Co. (representante)",
    "SEG": "Seguridad Marítima Andina S.A.",
    "LUB": "Lubricantes Industriales del Ecuador",
    "HID": "Hidráulica y Sellos del Guayas",
    "FER": "Ferretería Naval del Puerto",
    "QUIM": "Químicos y Pinturas Marinas EC",
}

# Ubicaciones de bodega para variar la foto de stock.
UBICACIONES = [
    "Bodega A · Estante 1", "Bodega A · Estante 3", "Bodega A · Estante 5",
    "Bodega B · Tanque 1", "Bodega B · Tanque 2", "Bodega C · Jaula 2",
    "Bodega D · Baterías", "Pañol de seguridad", "Bodega E · Cubierta",
    "Bodega F · Ferretería",
]

# ---------------------------------------------------------------------
# Catálogo. Cada fila:
# (codigo, nombre, categoria, unidad, costo, crit, lt, imp, prov,
#  base, saz, growth, interm)
#   base   = demanda media mensual (unidades)
#   saz    = amplitud estacional (pico may-sep)
#   growth = rampa por incorporación escalonada de interceptoras 2025-26
#   interm = demanda intermitente (muchos ceros; ítems caros de baja rotación)
# Los últimos cuatro campos NO se escriben al CSV: solo guían la
# generación sintética de la demanda.
# ---------------------------------------------------------------------
CATALOGO = [
    # ---- Familia 1: Motores fuera de borda (ancla) ----
    ("2815-EC-1001", "Bujía NGK BR8HS-10 (motor F/B 200HP)", "Motor fuera de borda", "u", 6.5, "E", 15, False, "YAM", 260, 0.25, True, False),
    ("2815-EC-1002", "Bujía iridium (motor F/B 250HP)", "Motor fuera de borda", "u", 12, "E", 20, False, "YAM", 90, 0.25, True, False),
    ("2815-EC-1003", "Impulsor bomba de agua 200-250HP", "Motor fuera de borda", "u", 48, "V", 45, True, "MPI", 34, 0.30, True, False),
    ("2815-EC-1004", "Impulsor bomba de agua 60-90HP", "Motor fuera de borda", "u", 32, "V", 40, True, "MPI", 26, 0.30, True, False),
    ("2815-EC-1005", "Kit empaques power head 200HP", "Motor fuera de borda", "kit", 185, "V", 60, True, "MPI", 9, 0.20, True, False),
    ("2815-EC-1006", "Kit empaques power head 300HP", "Motor fuera de borda", "kit", 245, "V", 70, True, "MPI", 5, 0.20, True, True),
    ("2815-EC-1007", "Termostato 60°C motor F/B", "Motor fuera de borda", "u", 32, "E", 45, True, "YAM", 18, 0.15, True, False),
    ("2815-EC-1008", "Hélice acero inox 3 palas 15.5x17", "Motor fuera de borda", "u", 620, "E", 75, True, "MPI", 5, 0.35, True, True),
    ("2815-EC-1009", "Hélice aluminio 3 palas 13x19", "Motor fuera de borda", "u", 180, "E", 45, True, "NAUP", 8, 0.30, True, False),
    ("2815-EC-1010", "Ánodo de sacrificio motor F/B", "Motor fuera de borda", "u", 14, "E", 30, False, "NAUP", 95, 0.20, True, False),
    ("2910-EC-1011", "Filtro de combustible separador de agua", "Motor fuera de borda", "u", 22, "V", 20, False, "RMG", 120, 0.25, True, False),
    ("2910-EC-1012", "Elemento filtrante Racor 10 micras", "Motor fuera de borda", "u", 16, "V", 25, False, "RMG", 140, 0.25, True, False),
    ("2910-EC-1013", "Bomba de combustible alta presión F/B", "Motor fuera de borda", "u", 410, "V", 90, True, "MPI", 4, 0.20, True, True),
    ("2815-EC-1014", "Cable de dirección 14 pies", "Motor fuera de borda", "u", 145, "E", 45, True, "MPI", 7, 0.15, True, True),
    ("2815-EC-1015", "Kit reparación carburador/inyección", "Motor fuera de borda", "kit", 96, "E", 60, True, "MPI", 12, 0.25, True, False),
    ("2920-EC-1016", "Rectificador/regulador de voltaje F/B", "Motor fuera de borda", "u", 168, "V", 60, True, "ELEC", 6, 0.10, True, True),
    ("2815-EC-1017", "Correa de distribución motor F/B 4T", "Motor fuera de borda", "u", 58, "V", 45, True, "MPI", 15, 0.15, True, False),
    ("2920-EC-1018", "Bobina de encendido F/B", "Motor fuera de borda", "u", 74, "E", 45, True, "ELEC", 16, 0.15, True, False),
    ("2920-EC-1019", "Estátor/alternador F/B 200HP", "Motor fuera de borda", "u", 320, "V", 75, True, "ELEC", 3, 0.10, True, True),
    ("2815-EC-1020", "Motor de arranque F/B", "Motor fuera de borda", "u", 380, "V", 75, True, "ELEC", 2.5, 0.10, True, True),
    ("2815-EC-1021", "Solenoide de arranque F/B", "Motor fuera de borda", "u", 58, "E", 40, True, "ELEC", 10, 0.10, True, False),
    ("2815-EC-1022", "Juego de segmentos (anillos) 200HP", "Motor fuera de borda", "kit", 130, "V", 70, True, "MPI", 4, 0.15, True, True),
    ("2815-EC-1023", "Pistón sobredimensión 0.5mm 200HP", "Motor fuera de borda", "u", 165, "V", 80, True, "MPI", 3, 0.15, True, True),
    ("2815-EC-1024", "Cojinete de biela motor F/B", "Motor fuera de borda", "u", 42, "E", 60, True, "MPI", 9, 0.10, True, False),
    ("2815-EC-1025", "Retén de cigüeñal superior F/B", "Motor fuera de borda", "u", 24, "E", 45, True, "MPI", 14, 0.10, True, False),
    ("9150-EC-1026", "Aceite de cola/engranaje (litro)", "Motor fuera de borda", "l", 12, "V", 15, False, "LUB", 160, 0.20, True, False),
    ("2815-EC-1027", "Kit de leva/varillaje selector de marcha", "Motor fuera de borda", "kit", 88, "E", 60, True, "MPI", 5, 0.15, True, True),
    ("2815-EC-1028", "Cilindro hidráulico trim/tilt F/B", "Motor fuera de borda", "u", 260, "E", 75, True, "HID", 3, 0.10, True, True),
    ("2815-EC-1029", "Sensor de trim/tilt F/B 300HP (nuevo)", "Motor fuera de borda", "u", 55, "E", 45, True, "ELEC", 0, 0.0, True, False),
    ("2910-EC-1030", "Filtro separador Racor serie nueva 300HP", "Motor fuera de borda", "u", 34, "V", 30, False, "RMG", 20, 0.20, True, False),
    ("4720-EC-1031", "Manguera de combustible baja presión (m)", "Motor fuera de borda", "m", 6, "E", 20, False, "RMG", 70, 0.15, True, False),
    ("2815-EC-1032", "Empaque de escape / mofle F/B", "Motor fuera de borda", "u", 46, "E", 55, True, "MPI", 8, 0.15, True, False),

    # ---- Familia 2: Motor diésel principal/auxiliar ----
    ("2815-EC-2001", "Filtro de aceite motor diésel principal", "Motor diésel", "u", 42, "V", 30, True, "DSL", 55, 0.10, False, False),
    ("2815-EC-2002", "Filtro de aire motor diésel principal", "Motor diésel", "u", 68, "E", 30, True, "DSL", 30, 0.10, False, False),
    ("2910-EC-2003", "Filtro de combustible primario diésel", "Motor diésel", "u", 38, "V", 30, True, "DSL", 60, 0.10, False, False),
    ("2910-EC-2004", "Filtro de combustible secundario diésel", "Motor diésel", "u", 44, "V", 35, True, "DSL", 48, 0.10, False, False),
    ("2815-EC-2005", "Inyector diésel reconstruido", "Motor diésel", "u", 320, "V", 75, True, "DSL", 8, 0.10, False, True),
    ("2815-EC-2006", "Bomba de inyección (remanufacturada)", "Motor diésel", "u", 1650, "V", 120, True, "DSL", 0.6, 0.10, False, True),
    ("2815-EC-2007", "Turbocargador (reemplazo programado)", "Motor diésel", "u", 2850, "V", 120, True, "DSL", 0.8, 0.10, False, True),
    ("2930-EC-2008", "Bomba de agua salada de refrigeración", "Motor diésel", "u", 540, "V", 90, True, "DSL", 2.5, 0.10, False, True),
    ("2930-EC-2009", "Intercambiador de calor (haz tubular)", "Motor diésel", "u", 780, "V", 110, True, "DSL", 0.7, 0.10, False, True),
    ("2815-EC-2010", "Kit empaquetadura de culata diésel", "Motor diésel", "kit", 410, "E", 90, True, "DSL", 3, 0.10, False, True),
    ("2815-EC-2011", "Termostato diésel 82°C", "Motor diésel", "u", 36, "E", 40, True, "DSL", 12, 0.10, False, False),
    ("2920-EC-2012", "Alternador 24V 80A diésel", "Motor diésel", "u", 460, "V", 90, True, "ELEC", 1.5, 0.10, False, True),
    ("2815-EC-2013", "Correa múltiple de accesorios diésel", "Motor diésel", "u", 52, "E", 45, True, "DSL", 14, 0.10, False, False),
    ("2815-EC-2014", "Sensor de temperatura de refrigerante", "Motor diésel", "u", 48, "E", 40, True, "DSL", 10, 0.10, False, False),

    # ---- Familia 3: Gobierno e hidráulica ----
    ("2010-EC-3001", "Cilindro hidráulico de timón", "Gobierno e hidráulica", "u", 690, "V", 90, True, "HID", 1.2, 0.10, False, True),
    ("4320-EC-3002", "Bomba hidráulica de dirección (helm)", "Gobierno e hidráulica", "u", 420, "V", 75, True, "HID", 1.5, 0.10, False, True),
    ("4320-EC-3003", "Kit de reparación bomba de timón", "Gobierno e hidráulica", "kit", 95, "V", 60, True, "HID", 5, 0.10, False, False),
    ("4730-EC-3004", "Manguera hidráulica alta presión (m)", "Gobierno e hidráulica", "m", 18, "E", 30, False, "HID", 40, 0.10, False, False),
    ("4730-EC-3005", "Racor hidráulico JIC 3/8", "Gobierno e hidráulica", "u", 6, "E", 20, False, "FER", 60, 0.10, False, False),
    ("2010-EC-3006", "Rótula/tie-bar de dirección dual", "Gobierno e hidráulica", "u", 78, "E", 45, True, "HID", 6, 0.10, True, False),
    ("2010-EC-3007", "Cojinete de mecha del timón", "Gobierno e hidráulica", "u", 145, "V", 75, True, "HID", 1.5, 0.10, False, True),
    ("9150-EC-3008", "Aceite hidráulico ATF de timón (galón)", "Gobierno e hidráulica", "gal", 26, "E", 20, False, "LUB", 55, 0.10, False, False),
    ("2010-EC-3009", "Sensor de ángulo de timón", "Gobierno e hidráulica", "u", 190, "E", 60, True, "ELEC", 1.5, 0.10, False, True),

    # ---- Familia 4: Casco y cubierta ----
    ("2040-EC-4001", "Pintura antiincrustante (galón)", "Casco y cubierta", "gal", 145, "E", 30, True, "QUIM", 40, 0.45, False, False),
    ("2040-EC-4002", "Imprimante epóxico de casco (galón)", "Casco y cubierta", "gal", 95, "E", 30, True, "QUIM", 22, 0.30, False, False),
    ("2040-EC-4003", "Ánodo de zinc de casco 5 lb", "Casco y cubierta", "u", 35, "E", 30, False, "NAUP", 60, 0.30, False, False),
    ("4030-EC-4004", "Cabo de amarre nylon 1.5\" (m)", "Casco y cubierta", "m", 7, "D", 15, False, "FER", 210, 0.20, False, False),
    ("4030-EC-4005", "Cabo de remolque poliéster 2\" (m)", "Casco y cubierta", "m", 11, "E", 25, False, "FER", 60, 0.20, False, False),
    ("2090-EC-4006", "Defensa neumática 30x50 cm", "Casco y cubierta", "u", 88, "D", 30, False, "NAUP", 14, 0.15, False, False),
    ("5330-EC-4007", "Sello mecánico eje bomba de achique", "Casco y cubierta", "u", 52, "V", 45, True, "HID", 16, 0.15, False, False),
    ("4320-EC-4008", "Bomba de achique sumergible 2000GPH", "Casco y cubierta", "u", 120, "V", 30, False, "NAUP", 8, 0.15, False, False),
    ("5930-EC-4009", "Interruptor automático de nivel de achique", "Casco y cubierta", "u", 28, "E", 25, False, "ELEC", 12, 0.10, False, False),
    ("2090-EC-4010", "Junta de sello de escotilla de cubierta", "Casco y cubierta", "u", 42, "D", 40, True, "NAUP", 6, 0.10, False, False),
    ("5340-EC-4011", "Bisagra inox pasamano/candado cubierta", "Casco y cubierta", "u", 15, "D", 15, False, "FER", 40, 0.10, False, False),

    # ---- Familia 5: Electrónica y navegación ----
    ("5895-EC-5001", "Antena VHF marina 8 pies", "Electrónica y navegación", "u", 130, "E", 45, True, "NAV", 6, 0.10, False, True),
    ("5820-EC-5002", "Radio VHF fija con DSC", "Electrónica y navegación", "u", 320, "V", 60, True, "NAV", 4, 0.10, False, True),
    ("5820-EC-5003", "Radio VHF portátil IP67", "Electrónica y navegación", "u", 180, "E", 45, True, "NAV", 8, 0.10, False, False),
    ("5826-EC-5004", "GPS/plotter 9\" (unidad de reemplazo)", "Electrónica y navegación", "u", 1150, "V", 90, True, "NAV", 1.5, 0.10, False, True),
    ("5841-EC-5005", "Radar domo 4kW 24\"", "Electrónica y navegación", "u", 2100, "V", 120, True, "NAV", 0.6, 0.10, False, True),
    ("5845-EC-5006", "Transductor de ecosonda P66", "Electrónica y navegación", "u", 240, "E", 75, True, "NAV", 3, 0.10, False, True),
    ("5826-EC-5007", "Antena GPS externa", "Electrónica y navegación", "u", 90, "E", 45, True, "NAV", 5, 0.10, False, False),
    ("6230-EC-5008", "Reflector LED de búsqueda 12V", "Electrónica y navegación", "u", 95, "E", 30, False, "ELEC", 9, 0.15, False, False),
    ("6220-EC-5009", "Luz de navegación LED (juego)", "Electrónica y navegación", "jgo", 60, "E", 25, False, "ELEC", 14, 0.10, False, False),
    ("5895-EC-5010", "Compás magnético con iluminación", "Electrónica y navegación", "u", 165, "E", 45, True, "NAV", 2, 0.10, False, True),
    ("5826-EC-5011", "Piloto automático (unidad de control)", "Electrónica y navegación", "u", 1450, "E", 120, True, "NAV", 0.5, 0.10, False, True),
    ("6605-EC-5012", "Sensor de rumbo/compás satelital", "Electrónica y navegación", "u", 380, "E", 75, True, "NAV", 1, 0.10, False, True),

    # ---- Familia 6: Seguridad de vida SOLAS ----
    ("4220-EC-6001", "Chaleco salvavidas SOLAS adulto", "Seguridad SOLAS", "u", 65, "V", 30, False, "SEG", 45, 0.20, True, False),
    ("4220-EC-6002", "Chaleco inflable automático 150N", "Seguridad SOLAS", "u", 120, "V", 45, True, "SEG", 12, 0.15, True, False),
    ("4220-EC-6003", "Balsa salvavidas inflable 8 personas", "Seguridad SOLAS", "u", 2400, "V", 120, True, "SEG", 0.5, 0.10, False, True),
    ("4220-EC-6004", "Unidad de disparo hidrostático (HRU)", "Seguridad SOLAS", "u", 85, "V", 60, True, "SEG", 4, 0.10, False, True),
    ("1370-EC-6005", "Bengala paracaídas roja MK8", "Seguridad SOLAS", "u", 38, "V", 60, True, "SEG", 30, 0.15, False, False),
    ("1370-EC-6006", "Señal fumígena flotante naranja", "Seguridad SOLAS", "u", 34, "V", 45, True, "SEG", 18, 0.15, False, False),
    ("4210-EC-6007", "Extintor PQS 10 lb marino", "Seguridad SOLAS", "u", 55, "V", 20, False, "SEG", 18, 0.10, False, False),
    ("4220-EC-6008", "Aro salvavidas con rabiza 30 m", "Seguridad SOLAS", "u", 48, "E", 20, False, "SEG", 10, 0.10, False, False),
    ("5820-EC-6009", "Radiobaliza EPIRB 406 MHz", "Seguridad SOLAS", "u", 620, "V", 90, True, "SEG", 1, 0.10, False, True),

    # ---- Familia 7: Lubricantes y químicos ----
    ("9150-EC-7001", "Aceite 2T TC-W3 (galón)", "Lubricantes y químicos", "gal", 28, "V", 10, False, "LUB", 420, 0.30, True, False),
    ("9150-EC-7002", "Aceite 10W-30 4T marino (galón)", "Lubricantes y químicos", "gal", 24, "V", 10, False, "LUB", 310, 0.25, True, False),
    ("9150-EC-7003", "Aceite 15W-40 diésel marino (galón)", "Lubricantes y químicos", "gal", 22, "V", 12, False, "LUB", 180, 0.15, False, False),
    ("9150-EC-7004", "Grasa marina anticorrosiva (lb)", "Lubricantes y químicos", "lb", 9, "E", 10, False, "LUB", 150, 0.15, False, False),
    ("9150-EC-7005", "Aceite hidráulico ISO 68 (galón)", "Lubricantes y químicos", "gal", 26, "E", 15, False, "LUB", 85, 0.10, False, False),
    ("6850-EC-7006", "Refrigerante de motor diésel (galón)", "Lubricantes y químicos", "gal", 18, "E", 15, False, "QUIM", 95, 0.10, False, False),
    ("6810-EC-7007", "Desengrasante industrial (galón)", "Lubricantes y químicos", "gal", 15, "D", 10, False, "QUIM", 110, 0.15, False, False),
    ("6850-EC-7008", "Líquido limpiador de inyectores (litro)", "Lubricantes y químicos", "l", 20, "E", 20, False, "QUIM", 40, 0.10, False, False),
    ("6810-EC-7009", "Inhibidor de corrosión en spray", "Lubricantes y químicos", "u", 11, "D", 15, False, "QUIM", 60, 0.10, False, False),

    # ---- Familia 8: Neumática y aire de arranque ----
    ("4310-EC-8001", "Compresor de aire de arranque", "Neumática y aire", "u", 980, "V", 110, True, "DSL", 0.4, 0.10, False, True),
    ("4310-EC-8002", "Kit de válvulas del compresor de aire", "Neumática y aire", "kit", 140, "E", 75, True, "DSL", 2, 0.10, False, True),
    ("4820-EC-8003", "Válvula de seguridad de botella de aire", "Neumática y aire", "u", 90, "V", 60, True, "DSL", 3, 0.10, False, False),
    ("4720-EC-8004", "Manguera neumática de arranque (m)", "Neumática y aire", "m", 14, "E", 25, False, "FER", 30, 0.10, False, False),
    ("6685-EC-8005", "Manómetro de botella de aire 0-40 bar", "Neumática y aire", "u", 45, "E", 30, False, "FER", 8, 0.10, False, False),

    # ---- Familia 9: Sistema eléctrico y baterías ----
    ("6140-EC-9001", "Batería marina AGM 12V 100Ah", "Sistema eléctrico y baterías", "u", 265, "V", 30, False, "ELEC", 22, 0.20, True, False),
    ("6140-EC-9002", "Batería de arranque diésel 12V 150Ah", "Sistema eléctrico y baterías", "u", 320, "V", 35, False, "ELEC", 8, 0.15, False, False),
    ("6145-EC-9003", "Cable de batería 2/0 AWG (m)", "Sistema eléctrico y baterías", "m", 12, "E", 20, False, "ELEC", 45, 0.10, False, False),
    ("5920-EC-9004", "Fusible ANL 200A", "Sistema eléctrico y baterías", "u", 8, "E", 20, False, "ELEC", 30, 0.10, False, False),
    ("5925-EC-9005", "Interruptor/breaker de batería 300A", "Sistema eléctrico y baterías", "u", 55, "E", 30, False, "ELEC", 10, 0.10, False, False),
    ("6130-EC-9006", "Cargador/convertidor 24V 40A", "Sistema eléctrico y baterías", "u", 480, "E", 75, True, "ELEC", 1.5, 0.10, False, True),
    ("6240-EC-9007", "Foco/lámpara halógena de proyector", "Sistema eléctrico y baterías", "u", 18, "D", 20, False, "FER", 40, 0.10, False, False),
    ("5977-EC-9008", "Escobillas/carbones de alternador (juego)", "Sistema eléctrico y baterías", "jgo", 12, "E", 30, True, "ELEC", 12, 0.10, False, False),

    # ---- Familia 10: Consumibles de mantenimiento ----
    ("5350-EC-1101", "Lija de agua #400 (pliego)", "Consumibles de mantenimiento", "u", 0.9, "D", 7, False, "FER", 480, 0.30, False, False),
    ("5345-EC-1102", "Disco de corte inox 4.5\"", "Consumibles de mantenimiento", "u", 1.8, "D", 10, False, "FER", 200, 0.15, False, False),
    ("8030-EC-1103", "Sellante marino 3M 5200 (tubo)", "Consumibles de mantenimiento", "u", 19, "E", 20, False, "QUIM", 65, 0.20, False, False),
    ("8030-EC-1104", "Silicona RTV de alta temperatura (tubo)", "Consumibles de mantenimiento", "u", 9, "E", 15, False, "QUIM", 55, 0.10, False, False),
    ("9505-EC-1105", "Alambre de acero inox de amarre (rollo)", "Consumibles de mantenimiento", "rollo", 12, "D", 10, False, "FER", 40, 0.10, False, False),
    ("5975-EC-1106", "Cinta autofundente eléctrica (rollo)", "Consumibles de mantenimiento", "rollo", 8, "E", 15, False, "FER", 70, 0.10, False, False),
    ("7920-EC-1107", "Trapo industrial / estopa (kg)", "Consumibles de mantenimiento", "kg", 3, "D", 7, False, "FER", 130, 0.10, False, False),
    ("8040-EC-1108", "Adhesivo epóxico 2 componentes (kit)", "Consumibles de mantenimiento", "kit", 14, "D", 15, False, "QUIM", 35, 0.10, False, False),
    ("5350-EC-1109", "Brocha/rodillo de pintura marina", "Consumibles de mantenimiento", "u", 4, "D", 10, False, "FER", 90, 0.15, False, False),
    ("6810-EC-1110", "Diluyente epóxico (galón)", "Consumibles de mantenimiento", "gal", 17, "D", 12, False, "QUIM", 45, 0.10, False, False),

    # ---- Familia 11: Ferretería naval ----
    ("5305-EC-1201", "Perno inox A4 M10x60", "Ferretería naval", "u", 0.8, "D", 15, False, "FER", 300, 0.10, False, False),
    ("5310-EC-1202", "Tuerca autoblocante inox M10", "Ferretería naval", "u", 0.3, "D", 15, False, "FER", 320, 0.10, False, False),
    ("5306-EC-1203", "Grillete inox 1/2\"", "Ferretería naval", "u", 9, "E", 20, False, "FER", 40, 0.10, False, False),
    ("4030-EC-1204", "Guardacabo inox 1/2\"", "Ferretería naval", "u", 3, "D", 15, False, "FER", 60, 0.10, False, False),
    ("5340-EC-1205", "Abrazadera inox de manguera", "Ferretería naval", "u", 1.5, "E", 12, False, "FER", 150, 0.10, False, False),
    ("5340-EC-1206", "Candado/cerradura inox de pañol", "Ferretería naval", "u", 22, "D", 20, False, "FER", 8, 0.10, False, False),
]

# --- Quirks de calidad de datos (ver docstring del módulo) ---
COD_SIN_MOVIMIENTOS = "2815-EC-1029"   # figura en maestro/stock, sin consumo
COD_HISTORIA_CORTA = "2910-EC-1030"    # ~8 meses de historia
MESES_HISTORIA_CORTA = 8
COD_SIN_STOCK = "5350-EC-1109"         # sin fila en stock_actual


# ---------------------------------------------------------------------
# Generación determinista de la demanda
# ---------------------------------------------------------------------
def _demanda_mes(item, i, rnd):
    """Demanda del mes i (0..35) para un ítem, misma forma que la demo.

    Estacionalidad (pico may-sep), rampa de crecimiento por incorporación
    de interceptoras 2025-26 y demanda intermitente para ítems caros de
    baja rotación. Determinista: consume `rnd` en orden fijo.
    """
    base, saz, growth, interm = item[9], item[10], item[11], item[12]
    m = (MES_INICIO + i) % 12
    estacional = 1 + saz * math.sin((2 * math.pi * (m - 4)) / 12)
    rampa = (1 + 0.55 * max(0.0, min(1.0, (i - 22) / 12))) if growth else 1.0
    mu = base * estacional * rampa
    if mu <= 0:
        return 0
    if interm:
        p = min(0.85, mu / (mu + 2))
        if rnd.random() < p:
            return max(1, int(round(mu / p + rnd.gauss(0, 1) * math.sqrt(mu))))
        return 0
    return max(0, int(round(mu + rnd.gauss(0, 1) * mu * 0.18)))


def _serie_item(item, rnd):
    """Serie mensual de consumo (lista de 36 enteros) para un ítem estándar.

    Garantiza consumo en el primer mes (jul-2023) para que la historia
    útil sea de 36 meses y el informe de calidad no marque historia corta
    en ítems que no son quirks deliberados.
    """
    serie = [_demanda_mes(item, i, rnd) for i in range(N_MESES)]
    if serie[0] == 0:
        serie[0] = 1
    return serie


def _existencia(serie, lt, rnd):
    """Existencia al corte, buscando una mezcla realista de situaciones.

    No reusa las fórmulas SS/ROP/EOQ (esas las calcula analisis_real): usa
    un proxy de punto de reorden para colocar el stock en bandas
    (quiebre / bajo ROP / normal / exceso). El ESTADO final lo decide
    analisis_real comparando esta existencia contra su ROP/nivel máximo.
    """
    if not serie:
        return 1
    ventana = serie[-6:]
    reciente = sum(ventana) / len(ventana)
    lt_m = lt / 30
    proxy_rop = reciente * lt_m + reciente * 0.6
    r = rnd.random()
    if r < 0.07:
        return 0                                             # quiebre
    if r < 0.24:
        return max(1, int(round(proxy_rop * rnd.uniform(0.15, 0.7))))  # bajo ROP
    if r < 0.85:
        return max(1, int(round(proxy_rop * rnd.uniform(1.25, 2.3)
                                + reciente)))                # normal
    return int(round(proxy_rop * rnd.uniform(3.5, 6.0)
                     + reciente * 8 + 5))                    # exceso


def _fecha_dma(i, dia):
    """Fecha dd/mm/aaaa del día `dia` del mes i (0 = jul-2023)."""
    anio = ANIO_INICIO + (MES_INICIO + i) // 12
    mes = (MES_INICIO + i) % 12 + 1
    return f"{dia:02d}/{mes:02d}/{anio}"


def _anio_mes(i):
    anio = ANIO_INICIO + (MES_INICIO + i) // 12
    mes = (MES_INICIO + i) % 12 + 1
    return anio, mes


# ---------------------------------------------------------------------
# Construcción de las tres tablas
# ---------------------------------------------------------------------
def construir_tablas():
    """Genera (maestro, movimientos, stock) como listas de listas (filas).

    Determinista con random.Random(SEMILLA). Devuelve las filas ya en el
    orden y formato de las columnas de la plantilla (sin encabezado).
    """
    rnd = random.Random(SEMILLA)
    maestro, movimientos, stock = [], [], []
    seq_ref = 0  # secuencia global -> referencias únicas (evita duplicados)

    for item in CATALOGO:
        cod, nombre, cat, um, costo, crit, lt, imp = item[:8]
        prov = PROV[item[8]]
        maestro.append([cod, nombre, cat, um, ("%g" % costo), crit,
                        int(lt), "S" if imp else "N", prov])

        # --- Serie de consumo según el tipo de ítem (con quirks) ---
        if cod == COD_SIN_MOVIMIENTOS:
            serie = []           # quirk 1: sin movimientos de consumo
        elif cod == COD_HISTORIA_CORTA:
            # quirk 2: solo los últimos MESES_HISTORIA_CORTA meses
            serie_full = _serie_item(item, rnd)
            serie = serie_full[-MESES_HISTORIA_CORTA:]
            serie = [max(1, v) for v in serie]  # asegura 8 meses efectivos
        else:
            serie = _serie_item(item, rnd)

        # --- Movimientos de CONSUMO (uno consolidado por mes activo) ---
        if cod == COD_HISTORIA_CORTA:
            offset = N_MESES - MESES_HISTORIA_CORTA
        else:
            offset = 0
        for k, cantidad in enumerate(serie):
            if cantidad <= 0:
                continue
            i = offset + k
            anio, _ = _anio_mes(i)
            dia = rnd.randint(3, 26)
            seq_ref += 1
            movimientos.append([cod, _fecha_dma(i, dia), "CONSUMO",
                                int(cantidad), REPARTO,
                                f"OT-{anio}-{seq_ref:04d}"])

        # --- INGRESO ocasional (reabastecimiento; el análisis lo ignora) ---
        base = item[9]
        if serie and base > 0 and rnd.random() < 0.45:
            i = rnd.randint(1, N_MESES - 1)
            anio, _ = _anio_mes(i)
            dia = rnd.randint(3, 26)
            seq_ref += 1
            lote = max(1, int(round(base * rnd.uniform(3, 6))))
            movimientos.append([cod, _fecha_dma(i, dia), "INGRESO", lote,
                                REPARTO, f"GR-{anio}-{seq_ref:04d}"])

        # --- AJUSTE de inventario ocasional (corrección de conteo) ---
        if serie and rnd.random() < 0.18:
            i = rnd.randint(1, N_MESES - 1)
            anio, _ = _anio_mes(i)
            dia = rnd.randint(3, 26)
            seq_ref += 1
            delta = rnd.choice([-3, -2, -1, 1, 2])
            movimientos.append([cod, _fecha_dma(i, dia), "AJUSTE", delta,
                                REPARTO, f"ACTA-INV-{anio}-{seq_ref:04d}"])

        # --- Existencia al corte (salvo el quirk 3: sin fila de stock) ---
        if cod == COD_SIN_STOCK:
            continue
        if cod == COD_SIN_MOVIMIENTOS:
            existencia = 1  # recién catalogado: una unidad en bodega
        else:
            existencia = _existencia(serie, lt, rnd)
        ubic = UBICACIONES[rnd.randrange(len(UBICACIONES))]
        stock.append([cod, int(existencia), FECHA_CORTE_DMA, ubic])

    return maestro, movimientos, stock


# ---------------------------------------------------------------------
# Serialización a CSV
# ---------------------------------------------------------------------
_COMENTARIO = ("# Reparto guardacostas SUBNOR (REFERENCIAL, simulado). "
               "Generado por scripts/generar_dataset_realista.py "
               "(semilla 20260711). NO son datos reales de SISLOG.")


def _csv_texto(columnas, filas):
    """Serializa (encabezado + comentario de procedencia + filas) a texto."""
    buffer = io.StringIO()
    escritor = csv.writer(buffer)
    escritor.writerow(columnas)
    escritor.writerow([_COMENTARIO] + [""] * (len(columnas) - 1))
    for fila in filas:
        escritor.writerow(fila)
    return buffer.getvalue()


def construir_csv():
    """Devuelve {'maestro_items': str, 'movimientos': str, 'stock_actual': str}."""
    maestro, movimientos, stock = construir_tablas()
    return {
        "maestro_items": _csv_texto(COLS_MAESTRO, maestro),
        "movimientos": _csv_texto(COLS_MOV, movimientos),
        "stock_actual": _csv_texto(COLS_STOCK, stock),
    }


def construir_archivos():
    """Los tres CSV como [(nombre, bytes)] para backend.app.importador.

    Esta es la entrada que consume el seed: alimenta el importador REAL
    con el dataset simulado, sin depender del sistema de archivos.
    """
    csv_por_tabla = construir_csv()
    return [
        ("maestro_items.csv", csv_por_tabla["maestro_items"].encode("utf-8")),
        ("movimientos.csv", csv_por_tabla["movimientos"].encode("utf-8")),
        ("stock_actual.csv", csv_por_tabla["stock_actual"].encode("utf-8")),
    ]


def escribir(directorio=DIR_SALIDA):
    """Escribe los tres CSV en `directorio` (plantilla importable en disco)."""
    directorio = Path(directorio)
    directorio.mkdir(parents=True, exist_ok=True)
    csv_por_tabla = construir_csv()
    nombres = {"maestro_items": "maestro_items.csv",
               "movimientos": "movimientos.csv",
               "stock_actual": "stock_actual.csv"}
    for clave, nombre in nombres.items():
        # write_bytes evita que el modo texto de Windows retraduzca el
        # \r\n que ya emite csv.writer a \r\r\n (líneas en blanco entre
        # filas). Mismo contenido que consume construir_archivos().
        (directorio / nombre).write_bytes(csv_por_tabla[clave].encode("utf-8"))
    return directorio


def main():
    maestro, movimientos, stock = construir_tablas()
    destino = escribir()
    consumos = sum(1 for m in movimientos if m[2] == "CONSUMO")
    ingresos = sum(1 for m in movimientos if m[2] == "INGRESO")
    ajustes = sum(1 for m in movimientos if m[2] == "AJUSTE")
    print(f"Dataset guardacostas realista escrito en: {destino}")
    print(f"  maestro_items.csv : {len(maestro)} ítems")
    print(f"  movimientos.csv   : {len(movimientos)} filas "
          f"({consumos} CONSUMO, {ingresos} INGRESO, {ajustes} AJUSTE)")
    print(f"  stock_actual.csv  : {len(stock)} filas "
          f"(quirks: {COD_SIN_MOVIMIENTOS} sin movimientos, "
          f"{COD_HISTORIA_CORTA} ~{MESES_HISTORIA_CORTA} meses, "
          f"{COD_SIN_STOCK} sin fila de stock)")


if __name__ == "__main__":
    main()
