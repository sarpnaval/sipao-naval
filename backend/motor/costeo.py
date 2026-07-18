"""SIPAO-Naval · Matriz de costeo de operación de unidades guardacostas (v3).

Responde la pregunta de un Almirante: «con el presupuesto que me
asignaron, ¿cuántos días de mar sostengo, con qué unidades y qué
operaciones dejo de cubrir? — y ¿cuánto necesito para el plan completo?».

NOVEDADES v3 (18-jul-2026)
--------------------------
1. COSTEO POR RUBROS con captura FÍSICA (cantidad × precio), no montos
   cerrados: el costo variable del día de mar deja de ser un número
   tecleado y pasa a ser la SUMA VERIFICADA de sus rubros. Esto habilita
   el análisis de sensibilidad al precio del galón (característica
   «credible» exigida por GAO-20-195G).
2. UNIDADES PRINCIPALES: solo entran al costeo por día de mar las
   unidades de mar (PGO oceánicas + PGM marítimas). Las menores quedan
   catalogadas con base de costeo por HORA DE MOTOR, para fase posterior.
3. ESTRUCTURA TIPO → MODELO → UNIDAD: el costeo se define por MODELO y
   todas las unidades de ese modelo lo heredan (5 modelos cubren las 16
   unidades principales).

ADVERTENCIA METODOLÓGICA CENTRAL (lo que este modelo NO hace)
------------------------------------------------------------
Las tarifas horarias publicadas por el US Coast Guard (COMDTINST
7310.1P) son de RECUPERACIÓN DE COSTO TOTAL: incluyen sueldos y
combustible fundidos con el mantenimiento. El propio §9.d advierte que
«these rates should not be used to calculate incremental operations
costs». Copiarlas aquí duplicaría tripulación y combustible, que este
modelo cotiza por separado. Por eso el mantenimiento preventivo se
construye BOTTOM-UP: cada tarea se prorratea sobre su intervalo en horas
de motor — técnica para la que el propio USCG da el precedente en el
Anexo (3) del mismo documento (costo de overhaul dividido entre los
meses del ciclo).

REGLAS ANTI-DUPLICACIÓN (obligatorias)
--------------------------------------
- Ningún costo de intervalo CALENDARIO (varada, certificaciones, seguros)
  se divide entre horas de navegación: va al costo fijo anual.
- Los rubros POR EVENTO (recaladas, ejercicios) no se prorratean por día
  de mar: inflarían la tarifa marginal de patrullas largas.
- El factor logístico de importación multiplica SOLO materiales, nunca
  mano de obra.
- El agua producida por evaporador no se costea aparte: su energía ya
  está en el combustible.

DOS TARIFAS, jamás una:
    - costo pleno/día  = CF_anual/días_operables + cv_día  → justificar
    - costo marginal/día = cv_día                           → decidir

PARÁMETROS DE CONFIGURACIÓN INICIAL: todo coeficiente, consumo, precio y
día del plan viene con VALOR REFERENCIAL para operar desde el primer día;
son campos de configuración y cada reparto carga sus cifras al implementar
(el panel de configuración marca el ORIGEN de cada parámetro).
"""

__all__ = [
    "TIPOS", "MODELOS", "UNIDADES", "OPERACIONES", "JERARQUIA", "PARAMETROS",
    "CLASES", "tarifas", "rubros_modelo", "simular_cobertura",
    "curva_cobertura", "presupuesto_para_plan", "matriz_costeo",
    "ficha_modelo", "escalera_conjunta", "catalogo_unidades",
    "aplicar_parametros",
]

# --- Jerarquía orgánica (Manual SYNA 2025 — denominaciones).
JERARQUIA = {
    "autoridad": "DIRNEA — Dirección Nacional de los Espacios Acuáticos",
    "comando": "COGUAR — Comando de Guardacostas",
    "subcomandos": ["SUBNOR", "SUBCEN", "SUBSUR"],
    "nota": ("Las unidades guardacostas NO pertenecen a la Escuadra "
             "Naval; operan en aguas interiores, mar territorial y zona "
             "contigua (la ZEE la controla COOPNA)."),
}

# ---------------------------------------------------------------------
# PARÁMETROS GLOBALES CONFIGURABLES
# ---------------------------------------------------------------------
# `origen` documenta la procedencia de cada valor:
#   referencial  = valor de arranque provisto por el sistema
#   literatura   = respaldo bibliográfico (su valor correcto ES este)
#   institucional= cargado de un documento de la institución
#   medido       = tomado de bitácoras/horómetros propios
#   estimado     = juicio del configurador
PARAMETROS = {
    "precio_diesel_gal": {
        "valor": 2.70, "unidad": "USD/gal", "origen": "institucional",
        "fuente": "EP Petroecuador, precio terminal sin IVA, jun-2026",
        "etiqueta": "Precio del diésel prémium"},
    "precio_gasolina_gal": {
        "valor": 2.69, "unidad": "USD/gal", "origen": "institucional",
        "fuente": "EP Petroecuador, precio terminal sin IVA, jun-2026",
        "etiqueta": "Precio de la gasolina extra/ecopaís"},
    "k_lubricantes": {
        "valor": 0.025, "unidad": "fracción del gasto de combustible",
        "origen": "literatura", "fuente": "Consumo de aceite 0,25–0,5 % del "
        "volumen de combustible; en dinero 1,5–4 % por el mayor precio unitario",
        "etiqueta": "Lubricantes como fracción del combustible"},
    "racion_mar_dia": {
        "valor": 6.50, "unidad": "USD/persona/día", "origen": "referencial",
        "fuente": "", "etiqueta": "Ración embarcada (mar)"},
    "racion_puerto_dia": {
        "valor": 3.50, "unidad": "USD/persona/día", "origen": "referencial",
        "fuente": "", "etiqueta": "Ración en puerto"},
    "factor_logistico": {
        "valor": 0.35, "unidad": "fracción sobre materiales",
        "origen": "estimado", "fuente": "Sobrecosto de importación de repuesto "
        "marino puesto en bodega; calibrar con órdenes de compra ejecutadas",
        "etiqueta": "Factor logístico de importación"},
    "reserva_correctivo": {
        "valor": 0.30, "unidad": "fracción del preventivo anual",
        "origen": "referencial", "fuente": "",
        "etiqueta": "Reserva de mantenimiento correctivo"},
}


def _p(clave):
    return PARAMETROS[clave]["valor"]


def aplicar_parametros(cambios):
    """Aplica cambios de configuración a los parámetros globales.
    `cambios` = {clave: {"valor": x, "origen": ..., "fuente": ...}} o
    {clave: valor}. Devuelve las claves efectivamente modificadas."""
    tocadas = []
    for clave, dato in (cambios or {}).items():
        if clave not in PARAMETROS:
            continue
        if isinstance(dato, dict):
            if "valor" in dato:
                PARAMETROS[clave]["valor"] = float(dato["valor"])
            for meta in ("origen", "fuente"):
                if dato.get(meta):
                    PARAMETROS[clave][meta] = dato[meta]
        else:
            PARAMETROS[clave]["valor"] = float(dato)
        tocadas.append(clave)
    return tocadas


# ---------------------------------------------------------------------
# NIVEL 1 — TIPOS (clase doctrinaria del Manual SYNA)
# ---------------------------------------------------------------------
# Regla de corte de unidad PRINCIPAL: eslora ≥ 19,8 m Y alojamiento para
# pernoctar a bordo. Coincide con la convención onomástica del propio
# SYNA: las unidades de mar llevan nombres de ISLAS; las menores, de RÍOS.
TIPOS = {
    "PGO": {
        "denominacion": "Patrullera Guardacostas Oceánica",
        "es_principal": True, "base_costeo": "dia_mar", "rol": "patrulla",
        "presencia_min": 120, "op_presencia": "VIDA_HUMANA",
        "ambito": ("Zona contigua hacia afuera y todo el litoral; única "
                   "clase con despliegue a cualquier punto del área SAR; "
                   "ZEE solo a requerimiento de COOPNA"),
    },
    "PGM": {
        "denominacion": "Patrullera Guardacostas Marítima",
        "es_principal": True, "base_costeo": "dia_mar", "rol": "patrulla",
        "presencia_min": 150, "op_presencia": "OCTI",
        "ambito": "Mar territorial hasta el límite exterior de la zona contigua",
    },
    # --- Unidades menores: catalogadas, fuera del costeo por día de mar.
    "LGI": {
        "denominacion": "Lancha Guardacostas Interceptora",
        "es_principal": False, "base_costeo": "hora_motor", "rol": "patrulla",
        "presencia_min": 0, "op_presencia": None,
        "ambito": "Radas y línea de costa; empleo ante ilícito cierto",
    },
    "PGC": {
        "denominacion": "Patrullera Guardacostas Costera",
        "es_principal": False, "base_costeo": "hora_motor", "rol": "patrulla",
        "presencia_min": 0, "op_presencia": None,
        "ambito": "Línea de costa, mar territorial y zona contigua",
    },
    "PGR": {
        "denominacion": "Patrullera Guardacostas Ribereña",
        "es_principal": False, "base_costeo": "hora_motor", "rol": "patrulla",
        "presencia_min": 0, "op_presencia": None,
        "ambito": "Franja costanera, aguas y canales interiores",
    },
    "PGB": {
        "denominacion": "Patrullera Guardacostas de Bahía",
        "es_principal": False, "base_costeo": "hora_motor", "rol": "patrulla",
        "presencia_min": 0, "op_presencia": None,
        "ambito": "Muy próxima al perfil costanero, operaciones cortas",
    },
    "LGL": {
        "denominacion": "Lancha Guardacostas Logística",
        "es_principal": False, "base_costeo": "hora_motor", "rol": "apoyo",
        "presencia_min": 0, "op_presencia": None,
        "ambito": "Reabastecimiento de estaciones y unidades destacadas",
    },
    "RSG": {
        "denominacion": "Remolcador de Servicio Guardacostas",
        "es_principal": False, "base_costeo": "hora_motor", "rol": "apoyo",
        "presencia_min": 0, "op_presencia": None,
        "ambito": "Bahía: asistencia, remolque, SAR y contaminación",
    },
}

# ---------------------------------------------------------------------
# NIVEL 2 — MODELOS (aquí se define el costeo; las unidades lo heredan)
# ---------------------------------------------------------------------
# perfil_dia: horas del día de mar en cada régimen (suma = h_nav_dia).
# consumo_gal_h: galones por hora en cada régimen.
#   El régimen máximo se ancla en potencia_hp × 0,050 gal/h/HP (diésel),
#   NUNCA por extrapolación cúbica desde crucero (sobreestima ~64 %).
# mantto_prev_usd_h: mantenimiento preventivo por hora de navegación,
#   construido bottom-up por intervalos de fabricante (§ docstring).
MODELOS = {
    "M1": {
        "nombre": "Damen Stan Patrol 5009", "tipo": "PGO",
        "constructor": "ASTINAVE (licencia Damen)", "eslora_m": 50.1,
        "tripulacion": 28, "velocidad_max_kt": 29.5,
        "velocidad_economica_kt": 12, "autonomia_mn": 2900,
        "num_motores": 4, "potencia_hp": 9000,
        "dias_operables": 200,
        "perfil_dia": {"fondeo": 4, "economico": 16, "sostenido": 3, "maximo": 1},
        "consumo_gal_h": {"fondeo": 12, "economico": 62, "sostenido": 190, "maximo": 450},
        "mantto_prev_usd_h": 95.0, "repuestos_usd_dia": 520.0,
        "fijos": {"remuneraciones": 620_000, "carena_amortizada": 180_000,
                  "certificaciones": 22_000, "seguros": 40_000,
                  "comunicaciones": 18_000, "muellaje_base": 45_000,
                  "administracion": 55_000},
        "origen": "referencial",
        "nota": ("Ficha del constructor: 50,1 m, 2.900 mn a 12 kt, 60,8 m³ "
                 "de combustible. La planta instalada en la configuración "
                 "ecuatoriana debe confirmarse con ASTINAVE."),
    },
    "M2": {
        "nombre": "Astilleros de Murueta 45 m", "tipo": "PGO",
        "constructor": "Astilleros de Murueta (España)", "eslora_m": 45.0,
        "tripulacion": 30, "velocidad_max_kt": 25,
        "velocidad_economica_kt": 12, "autonomia_mn": 3000,
        "num_motores": 2, "potencia_hp": 7000,
        "dias_operables": 200,
        "perfil_dia": {"fondeo": 4, "economico": 16, "sostenido": 3, "maximo": 1},
        "consumo_gal_h": {"fondeo": 11, "economico": 55, "sostenido": 165, "maximo": 350},
        "mantto_prev_usd_h": 85.0, "repuestos_usd_dia": 480.0,
        "fijos": {"remuneraciones": 640_000, "carena_amortizada": 165_000,
                  "certificaciones": 21_000, "seguros": 36_000,
                  "comunicaciones": 18_000, "muellaje_base": 42_000,
                  "administracion": 52_000},
        "origen": "referencial",
        "nota": "45 × 10 m, tripulación 30, >3.000 mn a 12 kt (constructor).",
    },
    "M3": {
        "nombre": "Clase Haeuri (Hyundai HI 53,7 m)", "tipo": "PGO",
        "constructor": "Hyundai Heavy Industries (Corea)", "eslora_m": 53.7,
        "tripulacion": 25, "velocidad_max_kt": 19,
        "velocidad_economica_kt": 11, "autonomia_mn": 2100,
        "num_motores": 2, "potencia_hp": 5400,
        "dias_operables": 190,
        "perfil_dia": {"fondeo": 5, "economico": 16, "sostenido": 2, "maximo": 1},
        "consumo_gal_h": {"fondeo": 10, "economico": 48, "sostenido": 130, "maximo": 270},
        "mantto_prev_usd_h": 105.0, "repuestos_usd_dia": 560.0,
        "fijos": {"remuneraciones": 560_000, "carena_amortizada": 195_000,
                  "certificaciones": 20_000, "seguros": 30_000,
                  "comunicaciones": 16_000, "muellaje_base": 40_000,
                  "administracion": 48_000},
        "origen": "referencial",
        "nota": ("Eslora mayor pero prestaciones menores (19 kt, 2.100 mn): "
                 "su tarifa de combustible es menor que la de los Damen. "
                 "Planta de los años 90 — mayor costo de mantenimiento."),
    },
    "M4": {
        "nombre": "Island class (ex-USCG 110 ft)", "tipo": "PGM",
        "constructor": "Bollinger (EE. UU.)", "eslora_m": 34.0,
        "tripulacion": 16, "velocidad_max_kt": 29.6,
        "velocidad_economica_kt": 12, "autonomia_mn": 3380,
        "num_motores": 2, "potencia_hp": 5760,
        "dias_operables": 180,
        "perfil_dia": {"fondeo": 4, "economico": 16, "sostenido": 3, "maximo": 1},
        "consumo_gal_h": {"fondeo": 8, "economico": 42, "sostenido": 120, "maximo": 288},
        "mantto_prev_usd_h": 65.0, "repuestos_usd_dia": 420.0,
        "fijos": {"remuneraciones": 380_000, "carena_amortizada": 150_000,
                  "certificaciones": 17_000, "seguros": 24_000,
                  "comunicaciones": 14_000, "muellaje_base": 32_000,
                  "administracion": 38_000},
        "origen": "referencial",
        "nota": ("Incorporadas al servicio en 2026. Planta Paxman fuera de "
                 "producción: mayor factor de obsolescencia en repuestos."),
    },
    "M5": {
        "nombre": "Damen Stan Patrol 2606", "tipo": "PGM",
        "constructor": "ASTINAVE (licencia Damen)", "eslora_m": 26.5,
        "tripulacion": 10, "velocidad_max_kt": 25,
        "velocidad_economica_kt": 12, "autonomia_mn": 1500,
        "num_motores": 2, "potencia_hp": 2400,
        "dias_operables": 210,
        "perfil_dia": {"fondeo": 4, "economico": 16, "sostenido": 3, "maximo": 1},
        "consumo_gal_h": {"fondeo": 5, "economico": 30, "sostenido": 78, "maximo": 120},
        "mantto_prev_usd_h": 38.0, "repuestos_usd_dia": 260.0,
        "fijos": {"remuneraciones": 260_000, "carena_amortizada": 95_000,
                  "certificaciones": 14_000, "seguros": 17_000,
                  "comunicaciones": 12_000, "muellaje_base": 26_000,
                  "administracion": 30_000},
        "origen": "referencial",
        "nota": ("26,5 m, 3.766 gal de combustible, 1.500 mn (≈30 gal/h en "
                 "régimen económico). Tripulación 10 (criterio conservador)."),
    },
}

# ---------------------------------------------------------------------
# NIVEL 3 — UNIDADES (las 16 principales; heredan el costeo del modelo)
# ---------------------------------------------------------------------
UNIDADES = [
    {"numeral": "LG-30", "nombre": "LAE Isla Isabela", "modelo": "M1", "subcomando": "SUBSUR"},
    {"numeral": "LG-31", "nombre": "LAE Isla Española", "modelo": "M1", "subcomando": "SUBNOR"},
    {"numeral": "LG-32", "nombre": "LAE Isla San Cristóbal", "modelo": "M2", "subcomando": "SUBSUR"},
    {"numeral": "LG-33", "nombre": "LAE Isla Santa Cruz", "modelo": "M2", "subcomando": "SUBCEN"},
    {"numeral": "LG-34", "nombre": "LAE Isla Floreana", "modelo": "M2", "subcomando": "SUBNOR"},
    {"numeral": "LG-35", "nombre": "LAE Isla Fernandina", "modelo": "M3", "subcomando": "SUBSUR"},
    {"numeral": "LG-36", "nombre": "LAE Isla Marchena", "modelo": "M3", "subcomando": "SUBCEN"},
    {"numeral": "LG-40", "nombre": "LAE Isla Genovesa", "modelo": "M4", "subcomando": "SUBNOR"},
    {"numeral": "LG-41", "nombre": "LAE Isla Pinta", "modelo": "M4", "subcomando": "SUBCEN"},
    {"numeral": "LG-42", "nombre": "LAE Isla Santiago", "modelo": "M5", "subcomando": "SUBSUR"},
    {"numeral": "LG-43", "nombre": "LAE Isla Rábida", "modelo": "M5", "subcomando": "SUBSUR"},
    {"numeral": "LG-44", "nombre": "LAE Isla Pinzón", "modelo": "M5", "subcomando": "SUBCEN"},
    {"numeral": "LG-45", "nombre": "LAE Isla Baltra", "modelo": "M5", "subcomando": "SUBCEN"},
    {"numeral": "LG-46", "nombre": "LAE Isla Seymour", "modelo": "M5", "subcomando": "SUBNOR"},
    {"numeral": "LG-47", "nombre": "LAE Isla Darwin", "modelo": "M5", "subcomando": "SUBNOR"},
    {"numeral": "LG-48", "nombre": "LAE Isla Wolf", "modelo": "M5", "subcomando": "SUBNOR"},
]

# --- Operaciones guardacostas: denominación y ORDEN de prioridad según
# la doctrina de empleo (2021). Respaldo de priorizar: economía de
# fuerzas (Doctrina Básica de la Armada, 2020). req_dias/min_dias =
# valores referenciales configurables del plan anual de operaciones.
OPERACIONES = {
    "VIDA_HUMANA": {
        "nombre": ("Salvaguarda de la vida humana en el mar "
                   "(búsqueda y rescate — SAR)"),
        "peso": 4.0, "min_dias": 320, "req_dias": 620,
        "clases": ["PGO", "PGM"],
        "responde_a": "Siniestros marítimos, emergencias y desastres",
    },
    "CONTAMINACION": {
        "nombre": "Control de la contaminación marino-costera",
        "peso": 3.0, "min_dias": 90, "req_dias": 260,
        "clases": ["PGO", "PGM"],
        "responde_a": ("Derrames y contaminación en los espacios "
                       "acuáticos (áreas sensibles incluidas)"),
    },
    "OCTI": {
        "nombre": ("Control de actividades marítimas y neutralización "
                   "de ilícitos (OCTI)"),
        "peso": 2.5, "min_dias": 420, "req_dias": 1_250,
        "clases": ["PGO", "PGM"],
        "responde_a": ("Narcotráfico, tráficos ilícitos, contrabando, "
                       "pesca INDNR, delincuencia en los espacios acuáticos"),
    },
    "DEFENSA": {
        "nombre": "Apoyo a la defensa interna y externa",
        "peso": 1.5, "min_dias": 90, "req_dias": 420,
        "clases": ["PGO", "PGM"],
        "responde_a": ("Apoyo al control militar de los espacios "
                       "acuáticos; su prioridad SUBE al materializarse "
                       "la amenaza (modo excepcional)"),
    },
}


# ---------------------------------------------------------------------
# Rubros del costo: captura física (cantidad × precio)
# ---------------------------------------------------------------------
def rubros_modelo(codigo_modelo, repuestos_dia=None):
    """Desglose del costo del día de mar de un MODELO, rubro por rubro.

    Bloque A (variable, entra a la tarifa marginal):
      A1 combustible = Σ_régimen horas × gal/h × precio
      A2 lubricantes = A1 × k_lub
      A3 mantenimiento preventivo = USD/hora × horas de navegación del día
      A4 repuestos críticos (manual o pronosticado por el motor SARP)
      A5 racionamiento embarcado = dotación × (ración mar − ración puerto)
    Bloque B (fijo anual, solo entra a la tarifa plena): remuneraciones,
      carena amortizada, certificaciones, seguros, comunicaciones,
      muellaje y apoyo de base, administración, y la reserva de
      mantenimiento correctivo (% del preventivo anualizado).
    """
    m = MODELOS[codigo_modelo]
    precio = _p("precio_diesel_gal")

    # --- A1 combustible, por régimen
    detalle_comb = []
    gal_dia = 0.0
    for regimen, horas in m["perfil_dia"].items():
        gal_h = m["consumo_gal_h"].get(regimen, 0.0)
        gal = horas * gal_h
        gal_dia += gal
        detalle_comb.append({
            "regimen": regimen, "horas": horas, "gal_h": gal_h,
            "galones": round(gal, 1), "usd": round(gal * precio, 2)})
    a1 = gal_dia * precio

    # horas de navegación del día (excluye fondeo: la máquina principal
    # no gira, pero los auxiliares sí — por eso el fondeo sí consume)
    h_nav = sum(h for r, h in m["perfil_dia"].items() if r != "fondeo")

    a2 = a1 * _p("k_lubricantes")
    a3 = m["mantto_prev_usd_h"] * h_nav
    a4 = float(repuestos_dia) if repuestos_dia is not None else m["repuestos_usd_dia"]
    a5 = m["tripulacion"] * (_p("racion_mar_dia") - _p("racion_puerto_dia"))

    variables = [
        {"codigo": "A1", "nombre": "Combustible", "usd_dia": round(a1, 2),
         "base": f"{gal_dia:.0f} gal/día × USD {precio:.2f}/gal",
         "detalle": detalle_comb},
        {"codigo": "A2", "nombre": "Aceites y lubricantes", "usd_dia": round(a2, 2),
         "base": f"{100 * _p('k_lubricantes'):.1f} % del combustible"},
        {"codigo": "A3", "nombre": "Mantenimiento mínimo preventivo",
         "usd_dia": round(a3, 2),
         "base": f"USD {m['mantto_prev_usd_h']:.0f}/hora × {h_nav} h de navegación"},
        {"codigo": "A4", "nombre": "Repuestos críticos de desgaste",
         "usd_dia": round(a4, 2),
         "base": ("pronosticado por el motor de abastecimiento"
                  if repuestos_dia is not None else "valor referencial por día")},
        {"codigo": "A5", "nombre": "Racionamiento embarcado (diferencial)",
         "usd_dia": round(a5, 2),
         "base": (f"{m['tripulacion']} tripulantes × USD "
                  f"{_p('racion_mar_dia') - _p('racion_puerto_dia'):.2f} de diferencial")},
    ]
    cv_dia = sum(r["usd_dia"] for r in variables)

    # --- Bloque B: fijos anuales
    f = dict(m["fijos"])
    preventivo_anual = m["mantto_prev_usd_h"] * h_nav * m["dias_operables"]
    f["correctivo_reserva"] = round(preventivo_anual * _p("reserva_correctivo"), 2)
    etiquetas = {
        "remuneraciones": "Remuneraciones de la dotación",
        "carena_amortizada": "Varada / carena amortizada",
        "certificaciones": "Certificaciones y habilitaciones de seguridad",
        "seguros": "Seguros / autoseguro imputado",
        "comunicaciones": "Comunicaciones y sistemas (abono fijo)",
        "muellaje_base": "Muellaje, servicios de puerto y apoyo de base",
        "administracion": "Apoyo administrativo y de mando superior",
        "correctivo_reserva": "Reserva de mantenimiento correctivo",
    }
    fijos = [{"codigo": f"B{i+1}", "nombre": etiquetas.get(k, k),
              "usd_anual": round(v, 2)}
             for i, (k, v) in enumerate(f.items())]
    cf_anual = sum(r["usd_anual"] for r in fijos)

    return {
        "modelo": codigo_modelo, "nombre_modelo": m["nombre"], "tipo": m["tipo"],
        "h_nav_dia": h_nav, "galones_dia": round(gal_dia, 1),
        "variables": variables, "cv_dia": round(cv_dia, 2),
        "fijos": fijos, "cf_anual": round(cf_anual, 2),
        "origen": m["origen"], "nota": m["nota"],
    }


def _unidades_de(codigo_modelo):
    return [u for u in UNIDADES if u["modelo"] == codigo_modelo]


def _modelos_de(tipo):
    return [c for c, m in MODELOS.items() if m["tipo"] == tipo]


def tarifas(codigo_modelo, repuestos_dia=None):
    """Las DOS TARIFAS del día de mar de un modelo."""
    r = rubros_modelo(codigo_modelo, repuestos_dia=repuestos_dia)
    m = MODELOS[codigo_modelo]
    n = len(_unidades_de(codigo_modelo))
    dias = max(1, m["dias_operables"])
    return {
        "modelo": codigo_modelo, "nombre": m["nombre"], "tipo": m["tipo"],
        "denominacion_tipo": TIPOS[m["tipo"]]["denominacion"],
        "unidades": n, "eslora_m": m["eslora_m"],
        "tripulacion": m["tripulacion"], "dias_operables": m["dias_operables"],
        "cv_dia": r["cv_dia"], "cf_anual": r["cf_anual"],
        "costo_marginal_dia": r["cv_dia"],
        "costo_pleno_dia": round(r["cf_anual"] / dias + r["cv_dia"], 2),
        "galones_dia": r["galones_dia"], "h_nav_dia": r["h_nav_dia"],
        "origen": m["origen"],
    }


def catalogo_unidades():
    """Catálogo completo TIPO → MODELO → UNIDAD para la pantalla."""
    principales, menores = [], []
    for cod, t in TIPOS.items():
        entrada = {"tipo": cod, "denominacion": t["denominacion"],
                   "es_principal": t["es_principal"],
                   "base_costeo": t["base_costeo"], "rol": t["rol"],
                   "ambito": t["ambito"], "presencia_min": t["presencia_min"]}
        if t["es_principal"]:
            entrada["modelos"] = [{
                **tarifas(cm),
                "constructor": MODELOS[cm]["constructor"],
                "nota": MODELOS[cm]["nota"],
                "lista_unidades": _unidades_de(cm),
            } for cm in _modelos_de(cod)]
            entrada["total_unidades"] = sum(len(_unidades_de(cm))
                                            for cm in _modelos_de(cod))
            principales.append(entrada)
        else:
            menores.append(entrada)
    return {"principales": principales, "menores": menores,
            "total_principales": sum(p["total_unidades"] for p in principales),
            "nota_corte": ("Al costeo por día de mar entran solo las unidades "
                           "de mar (eslora ≥ 19,8 m y alojamiento para "
                           "pernoctar). Las menores se catalogan con base de "
                           "costeo por hora de motor para una fase posterior.")}


# ---------------------------------------------------------------------
# Compatibilidad: vista agregada por TIPO (lo que consume el optimizador)
# ---------------------------------------------------------------------
def _clases_operativas(repuestos_dia=None):
    """Agrega los modelos de cada tipo principal en una entrada por TIPO:
    días entregables totales y costo marginal medio ponderado."""
    out = {}
    for tipo, t in TIPOS.items():
        if not t["es_principal"]:
            continue
        modelos = _modelos_de(tipo)
        dias_tot, costo_pond, unidades_tot, cf_tot = 0.0, 0.0, 0, 0.0
        for cm in modelos:
            n = len(_unidades_de(cm))
            if not n:
                continue
            tf = tarifas(cm, repuestos_dia=(repuestos_dia or {}).get(cm))
            dias = tf["dias_operables"] * n
            dias_tot += dias
            costo_pond += tf["cv_dia"] * dias
            cf_tot += tf["cf_anual"] * n
            unidades_tot += n
        if dias_tot <= 0:
            continue
        out[tipo] = {
            "nombre": t["denominacion"], "unidades": unidades_tot,
            "dias_entregables": dias_tot,
            "cv_dia": round(costo_pond / dias_tot, 2),
            "cf_anual_total": round(cf_tot, 2),
            "presencia_min": t["presencia_min"],
            "op_presencia": t["op_presencia"], "rol": t["rol"],
            "ambito": t["ambito"],
        }
    return out


# `CLASES` se mantiene como vista compatible (consumida por el puente de
# alistamiento y las pruebas heredadas).
class _VistaClases(dict):
    def __missing__(self, k):
        raise KeyError(k)


def _refrescar_clases():
    CLASES.clear()
    CLASES.update(_clases_operativas())
    return CLASES


CLASES = _VistaClases()
_refrescar_clases()


def _orden_prioridad():
    return sorted(OPERACIONES, key=lambda o: -OPERACIONES[o]["peso"])


def _orden_presencia(clases):
    con_piso = [c for c, d in clases.items()
                if d["presencia_min"] > 0 and d["op_presencia"]]
    return sorted(con_piso, key=lambda c: (
        -OPERACIONES[clases[c]["op_presencia"]]["peso"], clases[c]["cv_dia"]))


def _dias_max_por_clase(clases, alistamiento=None):
    """Días de mar entregables por tipo × A_c (puente con el optimizador
    de repuestos: sin repuestos, la clase entrega menos días aunque sobre
    combustible). Precedente público: GAO-25-107222 (FY2024, 594
    días-cutter perdidos por demoras de repuestos en el USCG)."""
    return {c: d["dias_entregables"] * (1.0 if not alistamiento
                                        else alistamiento.get(c, 1.0))
            for c, d in clases.items()}


def _costo_fijo_total(clases):
    return sum(d["cf_anual_total"] for d in clases.values())


def simular_cobertura(presupuesto_operativo, alistamiento=None,
                      priorizado=True, repuestos_dia=None):
    """Asigna los días de mar financiables en dos etapas.

    Etapas: 1a mínimos doctrinarios por prioridad (solo priorizado) →
    1b presencia mínima por tipo (ambos modos: es física) → 2 remanente
    (priorizado: orden estricto de prioridad; lineal: recorte parejo).
    """
    clases = _clases_operativas(repuestos_dia)
    tope = _dias_max_por_clase(clases, alistamiento)
    disponible = max(0.0, presupuesto_operativo)

    dias_op = {o: 0.0 for o in OPERACIONES}
    dias_clase = {c: 0.0 for c in clases}
    usado = 0.0

    def asigna(o, c, n):
        nonlocal usado
        cv = clases[c]["cv_dia"]
        cap = tope[c] - dias_clase[c]
        pres = (disponible - usado) / cv if cv > 0 else float("inf")
        d = int(min(n, cap + 1e-9, pres + 1e-9))
        if d > 0:
            dias_op[o] += d
            dias_clase[c] += d
            usado += d * cv
        return max(0, d)

    def clase_mas_barata(o):
        cand = [c for c in OPERACIONES[o]["clases"]
                if c in clases and dias_clase[c] + 1 <= tope[c] + 1e-9
                and usado + clases[c]["cv_dia"] <= disponible + 1e-9]
        return min(cand, key=lambda c: clases[c]["cv_dia"]) if cand else None

    orden = _orden_prioridad()

    # ETAPA 1a — mínimos doctrinarios por prioridad
    if priorizado:
        for o in orden:
            falta = OPERACIONES[o]["min_dias"] - dias_op[o]
            while falta > 0:
                c = clase_mas_barata(o)
                if c is None:
                    break
                p = asigna(o, c, falta)
                if p == 0:
                    break
                falta -= p

    # ETAPA 1b — presencia mínima por tipo (ambos modos)
    for c in _orden_presencia(clases):
        falta = clases[c]["presencia_min"] - dias_clase[c]
        if falta > 0:
            asigna(clases[c]["op_presencia"], c, falta)

    # ETAPA 2 — remanente
    if priorizado:
        for o in orden:
            while dias_op[o] < OPERACIONES[o]["req_dias"]:
                c = clase_mas_barata(o)
                if c is None or asigna(o, c, 1) == 0:
                    break
    else:
        # RECORTE LINEAL: la práctica que se quiere superar — a todas las
        # operaciones se les recorta la MISMA FRACCIÓN de su plan, sin
        # mirar prioridad. Se busca la fracción φ que agota el presupuesto
        # y luego se asigna φ·req_dias a cada operación, repartiendo en
        # rondas para que ninguna quede al final de la cola por azar del
        # orden (eso sería un artefacto, no un recorte lineal).
        def costo_de_fraccion(phi):
            cupo_v, costo = dict(dias_clase), 0.0
            for o in OPERACIONES:
                meta = phi * OPERACIONES[o]["req_dias"] - dias_op[o]
                for c in sorted([x for x in OPERACIONES[o]["clases"] if x in clases],
                                key=lambda cc: clases[cc]["cv_dia"]):
                    if meta <= 0:
                        break
                    usa = min(meta, tope[c] - cupo_v.get(c, 0.0))
                    if usa > 0:
                        costo += usa * clases[c]["cv_dia"]
                        cupo_v[c] = cupo_v.get(c, 0.0) + usa
                        meta -= usa
            return costo

        lo, hi = 0.0, 1.0
        for _ in range(40):                       # búsqueda binaria de φ
            mid = (lo + hi) / 2
            if costo_de_fraccion(mid) <= disponible - usado:
                lo = mid
            else:
                hi = mid
        phi = lo
        metas = {o: phi * OPERACIONES[o]["req_dias"] for o in OPERACIONES}
        avance = True
        while avance:                              # rondas de 1 día
            avance = False
            for o in OPERACIONES:
                if dias_op[o] >= min(metas[o], OPERACIONES[o]["req_dias"]):
                    continue
                c = clase_mas_barata(o)
                if c and asigna(o, c, 1) > 0:
                    avance = True

    coberturas = {
        o: {"nombre": OPERACIONES[o]["nombre"], "peso": OPERACIONES[o]["peso"],
            "dias": round(dias_op[o]), "requerido": OPERACIONES[o]["req_dias"],
            "cobertura": round(min(1.0, dias_op[o]
                                   / OPERACIONES[o]["req_dias"]), 3)}
        for o in OPERACIONES}
    peso_total = sum(OPERACIONES[o]["peso"] for o in OPERACIONES)
    cob_pond = sum(coberturas[o]["cobertura"] * OPERACIONES[o]["peso"]
                   for o in OPERACIONES) / peso_total

    return {
        "presupuesto_operativo": round(presupuesto_operativo, 2),
        "costo_fijo_contexto": round(_costo_fijo_total(clases), 2),
        "gasto_variable": round(usado, 2),
        "cobertura_ponderada": round(cob_pond, 3),
        "operaciones": coberturas,
        "dias_por_clase": {c: round(d) for c, d in dias_clase.items()},
        "unidades_bajo_minimo": [
            c for c in clases
            if dias_clase[c] < clases[c]["presencia_min"] - 1e-9],
        "unidades_sin_zarpar": [c for c in clases if dias_clase[c] == 0],
    }


def curva_cobertura(operativo_max, puntos=24, alistamiento=None):
    """Barrido presupuesto OPERATIVO → cobertura, priorizado vs lineal."""
    insignia = max(OPERACIONES, key=lambda o: OPERACIONES[o]["peso"])
    curva = []
    for i in range(puntos + 1):
        b = operativo_max * i / puntos
        opt = simular_cobertura(b, alistamiento, priorizado=True)
        lin = simular_cobertura(b, alistamiento, priorizado=False)
        curva.append({
            "presupuesto_operativo": round(b, 2),
            "cobertura_priorizada": opt["cobertura_ponderada"],
            "cobertura_pareja": lin["cobertura_ponderada"],
            "sar_priorizada": opt["operaciones"][insignia]["cobertura"],
            "sar_pareja": lin["operaciones"][insignia]["cobertura"],
        })
    return curva


def presupuesto_para_plan(alistamiento=None):
    """Problema inverso: presupuesto OPERATIVO mínimo para el plan completo
    (la munición del comandante ante el escalón superior). Auto-consistente:
    corre la simulación con presupuesto holgado y toma el gasto REAL, que
    incluye lo que cuesta respetar mínimos y presencia por tipo."""
    clases = _clases_operativas()
    tope = _dias_max_por_clase(clases, alistamiento)
    b_cap = sum(tope[c] * clases[c]["cv_dia"] for c in clases)
    lleno = simular_cobertura(b_cap, alistamiento, priorizado=True)
    operativo = lleno["gasto_variable"]
    teorico = sum(
        od["req_dias"] * min(clases[c]["cv_dia"] for c in od["clases"] if c in clases)
        for od in OPERACIONES.values())
    fijo = _costo_fijo_total(clases)
    return {"operativo_minimo": round(operativo, 2),
            "operativo_minimo_teorico": round(teorico, 2),
            "costo_fijo_contexto": round(fijo, 2),
            "presupuesto_total_contexto": round(fijo + operativo, 2)}


def ficha_modelo(codigo_modelo, a_c=None, repuestos_dia=None):
    """Ficha logística digital del modelo (estructura doctrinaria).

    La doctrina ya contempla una ficha logística por unidad que gestiona
    el abastecimiento por niveles (Máximo, Seguridad, Mínimo, Crítico) y
    define el Rango Operativo como la ventana de reaprovisionamiento.
    SIPAO la digitaliza: los niveles se calculan por ítem con la demanda
    real, no como porcentajes fijos.
    """
    if codigo_modelo not in MODELOS:
        return None
    m = MODELOS[codigo_modelo]
    r = rubros_modelo(codigo_modelo, repuestos_dia=repuestos_dia)
    t = tarifas(codigo_modelo, repuestos_dia=repuestos_dia)
    return {
        "modelo": codigo_modelo, "nombre": m["nombre"], "tipo": m["tipo"],
        "denominacion_tipo": TIPOS[m["tipo"]]["denominacion"],
        "constructor": m["constructor"], "origen": m["origen"], "nota": m["nota"],
        "caracteristicas": {
            "eslora_m": m["eslora_m"], "tripulacion": m["tripulacion"],
            "velocidad_max_kt": m["velocidad_max_kt"],
            "velocidad_economica_kt": m["velocidad_economica_kt"],
            "autonomia_mn": m["autonomia_mn"], "num_motores": m["num_motores"],
            "potencia_hp": m["potencia_hp"], "dias_operables": m["dias_operables"],
        },
        "unidades": _unidades_de(codigo_modelo),
        "rubros": r,
        "tarifas": {"marginal_dia": t["costo_marginal_dia"],
                    "pleno_dia": t["costo_pleno_dia"]},
        "niveles_logisticos": {
            "concepto": ("Niveles doctrinarios Máximo · Seguridad · Mínimo · "
                         "Crítico; Rango Operativo = ventana de reaprovisionamiento"),
            "equivalencia": ("Nivel máximo = stock máximo · Nivel de seguridad = "
                             "stock de seguridad (z·σ·√LT) · Nivel mínimo = punto "
                             "de reorden · Crítico = quiebre; calculados por ítem "
                             "con la demanda real, no porcentajes fijos"),
        },
        "alistamiento_repuestos": a_c,
    }


def escalera_conjunta(presupuesto_total, pasos_repuestos=None,
                      alistamiento_base=None, max_decisiones=600):
    """Escalera marginal UNIFICADA repuesto ⇄ día de mar: un solo
    presupuesto donde cada dólar compite entre comprar el siguiente
    repuesto crítico (sube el alistamiento → desbloquea días de mar) y
    financiar el siguiente día de patrulla."""
    clases = _clases_operativas()
    pasos = list(pasos_repuestos or [])
    alist = dict(alistamiento_base or {})
    # el puente se aplica al tipo con catálogo de repuestos en el sistema
    puente = next((c for c in clases if c in alist), None) or \
        (list(clases)[0] if clases else None)
    tope = _dias_max_por_clase(clases, alist)
    disponible = max(0.0, presupuesto_total)

    dias_op = {o: 0.0 for o in OPERACIONES}
    dias_clase = {c: 0.0 for c in clases}
    usado = 0.0
    decisiones = []
    orden = _orden_prioridad()

    objetivos = ([("min", o, OPERACIONES[o]["min_dias"]) for o in orden]
                 + [("presencia", c, None) for c in _orden_presencia(clases)]
                 + [("plan", o, OPERACIONES[o]["req_dias"]) for o in orden])

    def cupo(c):
        return tope[c] - dias_clase[c]

    def clase_para(o):
        cand = [c for c in OPERACIONES[o]["clases"]
                if c in clases and cupo(c) >= 1
                and usado + clases[c]["cv_dia"] <= disponible + 1e-9]
        return min(cand, key=lambda c: clases[c]["cv_dia"]) if cand else None

    def valor_dia(o):
        return OPERACIONES[o]["peso"] / OPERACIONES[o]["req_dias"]

    def registrar(tipo, detalle, costo, ganancia):
        if len(decisiones) < max_decisiones:
            decisiones.append({"tipo": tipo, "detalle": detalle,
                               "costo": round(costo, 2),
                               "acumulado": round(usado, 2),
                               "ganancia_por_usd": round(ganancia, 8)})

    def comprar_repuesto_si_conviene(o):
        nonlocal usado
        if not pasos or puente is None or puente not in OPERACIONES[o]["clases"]:
            return False
        if cupo(puente) >= 1:
            return False
        paso = pasos[0]
        if usado + paso["costo"] > disponible + 1e-9:
            return False
        desbloquea = clases[puente]["dias_entregables"] * paso["delta_a"]
        if desbloquea <= 0:
            return False
        efic_rep = desbloquea * valor_dia(o) / max(paso["costo"], 1e-9)
        c_alt = clase_para(o)
        efic_dia = (valor_dia(o) / clases[c_alt]["cv_dia"]) if c_alt else 0.0
        if efic_rep <= efic_dia:
            return False
        usado += paso["costo"]
        tope[puente] += desbloquea
        alist[puente] = alist.get(puente, 1.0) + paso["delta_a"]
        registrar("repuesto",
                  (f"Compra de repuestos: +{paso['delta_a']:.4f} de "
                   f"alistamiento {puente} desbloquea {desbloquea:.0f} días de mar"),
                  paso["costo"], efic_rep)
        pasos.pop(0)
        return True

    for fase, clave, meta in objetivos:
        if fase == "presencia":
            c = clave
            o = clases[c]["op_presencia"]
            falta = clases[c]["presencia_min"] - dias_clase[c]
            n = int(min(falta, cupo(c), (disponible - usado) / clases[c]["cv_dia"]))
            if n > 0:
                dias_op[o] += n
                dias_clase[c] += n
                costo = n * clases[c]["cv_dia"]
                usado += costo
                registrar("dias", f"Presencia {c}: {n} días → {o}",
                          costo, valor_dia(o) / clases[c]["cv_dia"])
            continue
        o = clave
        while dias_op[o] < meta:
            if comprar_repuesto_si_conviene(o):
                continue
            c = clase_para(o)
            if c is None:
                break
            n = int(min(meta - dias_op[o], cupo(c),
                        (disponible - usado) / clases[c]["cv_dia"]))
            if n <= 0:
                break
            dias_op[o] += n
            dias_clase[c] += n
            usado += n * clases[c]["cv_dia"]
            registrar("dias",
                      f"{'Mínimo' if fase == 'min' else 'Plan'} {o}: {n} días con {c}",
                      n * clases[c]["cv_dia"], valor_dia(o) / clases[c]["cv_dia"])

    peso_total = sum(OPERACIONES[o]["peso"] for o in OPERACIONES)
    cob = sum(min(1.0, dias_op[o] / OPERACIONES[o]["req_dias"])
              * OPERACIONES[o]["peso"] for o in OPERACIONES) / peso_total
    return {
        "presupuesto_total": round(presupuesto_total, 2),
        "gasto": round(usado, 2),
        "cobertura_ponderada": round(cob, 3),
        "clase_puente": puente,
        "a_final": round(alist.get(puente, 1.0), 4) if puente else None,
        "repuestos_comprados": sum(1 for d in decisiones if d["tipo"] == "repuesto"),
        "decisiones": decisiones,
        "nota": ("Escalera marginal unificada: cada dólar compite entre el "
                 "siguiente repuesto crítico (desbloquea días de mar vía "
                 "alistamiento) y el siguiente día de patrulla."),
    }


def matriz_costeo(alistamiento=None, repuestos_dia=None):
    """Respuesta completa que consume la pantalla de mando."""
    _refrescar_clases()
    inverso = presupuesto_para_plan(alistamiento)
    b_op = inverso["operativo_minimo"]
    reps = repuestos_dia or {}
    clases = _clases_operativas(reps)
    return {
        "es_ejemplo": True,
        "jerarquia": JERARQUIA,
        "parametros": PARAMETROS,
        "catalogo": catalogo_unidades(),
        "modelos": [tarifas(cm, repuestos_dia=reps.get(cm)) for cm in MODELOS
                    if TIPOS[MODELOS[cm]["tipo"]]["es_principal"]],
        "rubros_por_modelo": {cm: rubros_modelo(cm, repuestos_dia=reps.get(cm))
                              for cm in MODELOS
                              if TIPOS[MODELOS[cm]["tipo"]]["es_principal"]},
        "clases": [{"tipo": c, **d} for c, d in clases.items()],
        "operaciones": {o: {"nombre": od["nombre"], "peso": od["peso"],
                            "req_dias": od["req_dias"], "min_dias": od["min_dias"],
                            "responde_a": od["responde_a"],
                            "clases": od["clases"]}
                        for o, od in OPERACIONES.items()},
        "presupuesto_plan": inverso,
        "curva": curva_cobertura(b_op * 1.05, alistamiento=alistamiento),
        "escenario_recorte": {
            pct: {
                "priorizado": simular_cobertura(
                    b_op * (1 - pct / 100.0), alistamiento, priorizado=True),
                "parejo": simular_cobertura(
                    b_op * (1 - pct / 100.0), alistamiento, priorizado=False),
            }
            for pct in (0, 20, 40)},
    }
