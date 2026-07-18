"""SARP-Naval · Esencialidad operativa: ¿este ítem impide zarpar?

Responde una pregunta que la criticidad VED NO responde, y que es la
única que gobierna el modelo de alistamiento:

    ¿La falta de este ítem deja a la unidad SIN PODER OPERAR?

POR QUÉ ESTE MÓDULO EXISTE (el error que corrige)
--------------------------------------------------
El modelo de alistamiento multiplicaba la disponibilidad de los 37
ítems clasificados V/E del catálogo, asumiendo que la unidad necesita
los 37 a la vez para zarpar. Eso es FALSO, y la doctrina lo dice con
todas las letras.

El Departamento de Defensa de EE. UU. asigna a cada ítem un CÓDIGO DE
ESENCIALIDAD que distingue exactamente lo que aquí se modela
(US Army TM 1-1500-204-23-6, Tabla 7-2 «Essentiality Codes»; la misma
escala de cinco códigos aparece en DoDM 4140.01):

    1 = «Failure of this part will render the end item inoperable»
    3 = «Failure of this part will not render the end item inoperable»
    5 = no califica para el código 1, pero se necesita para la
        SEGURIDAD DEL PERSONAL
    6 = no califica para el código 1, pero se necesita por requisitos
        legales, climáticos o del entorno operativo planificado
    7 = no califica para el código 1, pero «is needed to prevent
        impairment or temporary reduction of operational effectiveness»

La existencia misma de los códigos 3 y 7 es la prueba doctrinaria: hay
ítems gestionados, incluso caros e importantes, cuya falta NO deja a la
unidad inoperable.

VED NO ES ESENCIALIDAD DE MISIÓN — SON EJES ORTOGONALES
--------------------------------------------------------
VED (Vital/Esencial/Deseable) es una técnica de GESTIÓN DE INVENTARIO:
clasifica por consecuencia de un quiebre de stock para decidir política
de compra. La esencialidad operativa es INGENIERÍA DE MISIÓN: ¿el buque
zarpa sin esto? Son preguntas distintas. Los 37 ítems V/E son «los que
duele que falten», no «los que impiden zarpar».

Confundirlas es un error DOCUMENTADO Y MEDIDO por la propia Armada de
EE. UU. El estudio «IMEC Implementation in TARSLLs» (Fleet Material
Support Office, DTIC ADA171776) lo diagnostica verbatim:

    «Almost every ship installed item is currently coded 'vital' to the
    ship's mission, thus it is almost impossible for the [...] model to
    distinguish between the most essential items and the other less
    important candidates.»

y concluye que eliminar esa medida de esencialidad «had almost no
impact on effectiveness or cost proving the uselessness of current
essentiality measures». Cuando «todo es vital», la esencialidad deja de
ser información y el modelo deja de discriminar.

CALIBRACIÓN CONTRA DATO PUBLICADO
----------------------------------
El mismo estudio publica la distribución real de esencialidad en
catálogos de buques (Tabla IV): solo el 16 % (buque AS-11) y el 26 %
(buques AD/AR) de los ítems causan PÉRDIDA TOTAL de la capacidad
primaria. La asignación de este módulo se calibra dentro de esa banda
publicada — no a criterio libre. Ver `verificar_calibracion()`.

VALIDEZ MATEMÁTICA DE RESTRINGIR EL PRODUCTO
---------------------------------------------
Restringir el producto de disponibilidades al subconjunto esencial es
formalmente válido por teoría de sistemas coherentes (Barlow &
Proschan): los ítems no esenciales son componentes IRRELEVANTES de la
función de estructura «puede salir a operar», y un componente
irrelevante no altera la función. No es un atajo: es la definición.

DECLARACIÓN OBLIGATORIA DE HONESTIDAD
--------------------------------------
Al restringir el producto a menos ítems, la disponibilidad calculada
SUBE mecánicamente. Eso NO es «mejorar el número»: es responder a otra
pregunta (¿puede zarpar? en vez de ¿está todo completo?). Debe
declararse en pantalla y en la sustentación. Ocultarlo lo convertiría
en maquillaje.

Los códigos de este módulo son DATOS DE EJEMPLO declarados, asignados
con criterio de ingeniería sobre una lancha guardacostas con motores
fuera de borda y motor diésel. En una implementación real los asigna la
unidad (ver la ficha de unidad tipo MESM del cronograma sugerido), no
el sistema.

Referencias
-----------
- US Army TM 1-1500-204-23-6, Tabla 7-2 «Essentiality Codes (ESNTL-CD)».
- DoDM 4140.01, códigos de esencialidad de ítem.
- DeHart, B. M. «IMEC Implementation in TARSLLs». Navy Fleet Material
  Support Office, Mechanicsburg. DTIC ADA171776. (Tablas I y IV.)
- Barlow, R. E., y Proschan, F. *Statistical Theory of Reliability and
  Life Testing.* (Sistemas coherentes; componentes irrelevantes.)
"""

__all__ = [
    "CODIGOS",
    "IMPIDE_OPERAR",
    "BANDA_CALIBRACION",
    "ESENCIALIDAD",
    "codigo_de",
    "impide_operar",
    "explicar",
    "verificar_calibracion",
]

# --- Escala doctrinaria del DoD (TM 1-1500-204-23-6, Tabla 7-2).
CODIGOS = {
    1: "Su falta deja la unidad SIN PODER OPERAR",
    3: "Su falta NO deja la unidad sin poder operar",
    5: "No impide operar, pero se necesita para la seguridad del personal",
    6: "No impide operar, pero lo exige una norma legal o del entorno",
    7: "No impide operar, pero su falta degrada la efectividad operativa",
}

# El único código que gobierna el modelo de alistamiento.
IMPIDE_OPERAR = 1

# Banda publicada de ítems que causan pérdida total de capacidad
# primaria en catálogos navales reales (ADA171776, Tabla IV):
# 16 % (AS-11) a 26 % (AD/AR).
BANDA_CALIBRACION = (0.16, 0.26)

# --- Asignación por ítem: código + por qué (para explicabilidad).
# Criterio: código 1 SOLO si su falta impide físicamente que la lancha
# zarpe o navegue (propulsión, gobierno, arranque, achique).
ESENCIALIDAD = {
    # === Motor fuera de borda: propulsión y gobierno ===
    "2815-EC-0102": (1, "Sin impulsor, la bomba de agua no refrigera y el motor se detiene"),
    "2815-EC-0103": (1, "Empaques del power head: sin ellos el motor no puede armarse ni operar"),
    "2815-EC-0105": (1, "Sin hélice no hay propulsión"),
    "2815-EC-0108": (1, "Sin bomba de alta presión no llega combustible al motor"),
    "2815-EC-0109": (1, "Sin cable de dirección la lancha no gobierna"),
    "2815-EC-0112": (1, "Sin correa de distribución el motor no gira"),
    "2815-EC-0101": (7, "Bujía: el motor arranca con las restantes; degrada rendimiento"),
    "2815-EC-0104": (7, "Termostato: el motor opera vigilando temperatura; degrada"),
    "2815-EC-0106": (3, "Ánodo de sacrificio: protege del galvanismo a largo plazo"),
    "2815-EC-0107": (7, "Filtro separador: se puede zarpar con vigilancia; degrada y arriesga"),
    "2815-EC-0110": (7, "Kit de carburación: afecta rendimiento, no impide zarpar"),
    "2815-EC-0111": (7, "Rectificador: el motor arranca y opera con la batería cargada; su falta degrada la operación sostenida"),
    # === Lubricantes ===
    "9150-EC-0201": (7, "Aceite 2T: sin él no se opera sostenidamente; se raciona a corto plazo"),
    "9150-EC-0202": (7, "Aceite 4T: igual que el 2T; degrada la sostenibilidad, no el zarpe"),
    "9150-EC-0203": (3, "Grasa: mantenimiento preventivo, no condiciona el zarpe"),
    "9150-EC-0204": (3, "Aceite hidráulico: reposición programada"),
    "6850-EC-0205": (7, "Refrigerante: degrada; se puede completar con agua tratada"),
    # === Casco y cubierta ===
    "2040-EC-0301": (3, "Pintura antiincrustante: mantenimiento de varada"),
    "2040-EC-0302": (3, "Ánodo de zinc: protección catódica de largo plazo"),
    "4030-EC-0303": (3, "Cabo de amarre: no condiciona la navegación"),
    "2090-EC-0304": (3, "Defensa neumática: protege el atraque"),
    "5330-EC-0305": (1, "Sin sello del eje de achique la lancha embarca agua: no zarpa"),
    # === Electrónica y navegación ===
    "5895-EC-0401": (7, "Antena VHF: degrada comunicaciones; hay equipos portátiles"),
    "6140-EC-0402": (1, "Sin batería no hay arranque ni electrónica: no zarpa"),
    "5895-EC-0403": (7, "Ecosonda: degrada seguridad náutica en aguas someras"),
    "6230-EC-0404": (7, "Reflector: degrada la capacidad nocturna, no el zarpe diurno"),
    "5895-EC-0405": (7, "GPS/plotter: degrada; queda navegación por medios alternos"),
    # === Seguridad del personal (código 5: no impiden operar, pero son norma) ===
    "4220-EC-0501": (5, "Chalecos salvavidas: seguridad del personal"),
    "4220-EC-0502": (5, "Bengalas: señalización de emergencia"),
    "4210-EC-0503": (5, "Extintor: seguridad contra incendios"),
    "4220-EC-0504": (5, "Aro salvavidas: rescate de hombre al agua"),
    # === Motor diésel principal ===
    "2815-EC-0601": (7, "Filtro de aceite: degrada; se opera vigilando presión"),
    "2815-EC-0602": (7, "Filtro de aire: degrada rendimiento"),
    "2815-EC-0603": (1, "Sin inyector no hay combustión en el cilindro: el motor no opera"),
    "2815-EC-0604": (7, "Turbocargador: el diésel opera atmosférico, con potencia degradada"),
    "2930-EC-0605": (1, "Sin bomba de agua salada no hay refrigeración: el motor se detiene"),
    "2815-EC-0606": (7, "Empaquetadura de culata: reparación mayor programada"),
    # === Consumibles ===
    "5350-EC-0701": (3, "Lija: mantenimiento de superficies"),
    "8030-EC-0702": (3, "Sellante: reparaciones menores"),
    "9505-EC-0703": (3, "Alambre de amarre: uso general"),
    "6810-EC-0704": (3, "Desengrasante: limpieza"),
    "5975-EC-0705": (3, "Cinta autofundente: reparaciones eléctricas menores"),

    # === Catálogo demo realista (125 ítems, generar_dataset_realista.py) ===
    # Asignación por reglas doctrinarias explícitas (ver criterio arriba):
    # 1=propulsión/combustible/gobierno/arranque/achique/energía · 6=norma
    # para zarpar · 5=seguridad del personal · 7=degrada (V no crítico de
    # parada) · 3=no impide operar.
    "2815-EC-1001": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1002": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1003": (1, "Sin impulsor no hay refrigeración: el motor se detiene en minutos"),
    "2815-EC-1004": (1, "Sin impulsor no hay refrigeración: el motor se detiene en minutos"),
    "2815-EC-1005": (1, "Sin empaques el power head no puede armarse: la unidad queda sin propulsión"),
    "2815-EC-1006": (1, "Sin empaques el power head no puede armarse: la unidad queda sin propulsión"),
    "2815-EC-1007": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1008": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1009": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1010": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2910-EC-1011": (1, "Combustible contaminado con agua detiene el motor: sin filtro no se navega"),
    "2910-EC-1012": (1, "Sin elemento filtrante el circuito de combustible queda fuera de servicio"),
    "2910-EC-1013": (1, "Sin bomba de alta presión no hay inyección: el motor no funciona"),
    "2815-EC-1014": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1015": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2920-EC-1016": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "2815-EC-1017": (1, "Su rotura detiene el motor y puede destruir el conjunto motriz"),
    "2920-EC-1018": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2920-EC-1019": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "2815-EC-1020": (1, "Sin motor de arranque la unidad no zarpa"),
    "2815-EC-1021": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1022": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "2815-EC-1023": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "2815-EC-1024": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1025": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "9150-EC-1026": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "2815-EC-1027": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1028": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1029": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2910-EC-1030": (1, "Sin filtro separador el motor de 300HP queda fuera de servicio"),
    "4720-EC-1031": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-1032": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-2001": (1, "Sin filtro de aceite el motor principal no puede operar con seguridad"),
    "2815-EC-2002": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2910-EC-2003": (1, "Sin filtro primario el combustible no llega limpio: el motor se detiene"),
    "2910-EC-2004": (1, "Sin filtro secundario la inyección diésel queda desprotegida y se detiene"),
    "2815-EC-2005": (1, "Un inyector fuera de servicio deja el motor principal inoperable"),
    "2815-EC-2006": (1, "Sin bomba de inyección el motor diésel no funciona"),
    "2815-EC-2007": (1, "Sin turbocargador el motor principal no entrega potencia de operación"),
    "2930-EC-2008": (1, "Sin bomba de agua salada no hay refrigeración: el motor se detiene"),
    "2930-EC-2009": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "2815-EC-2010": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-2011": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2920-EC-2012": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "2815-EC-2013": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2815-EC-2014": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2010-EC-3001": (1, "Sin cilindro hidráulico no hay gobierno del timón: no se puede maniobrar"),
    "4320-EC-3002": (1, "Sin bomba de dirección la unidad queda sin gobierno"),
    "4320-EC-3003": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "4730-EC-3004": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "4730-EC-3005": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2010-EC-3006": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2010-EC-3007": (1, "Sin cojinete de mecha el timón queda fuera de servicio"),
    "9150-EC-3008": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2010-EC-3009": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2040-EC-4001": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2040-EC-4002": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2040-EC-4003": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "4030-EC-4004": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "4030-EC-4005": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2090-EC-4006": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5330-EC-4007": (1, "Sin sello mecánico la bomba de achique falla: no es seguro hacerse a la mar"),
    "4320-EC-4008": (1, "Sin achique operativo no es seguro hacerse a la mar"),
    "5930-EC-4009": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "2090-EC-4010": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5340-EC-4011": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5895-EC-5001": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5820-EC-5002": (6, "Radio VHF con DSC exigida por normativa para zarpar"),
    "5820-EC-5003": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5826-EC-5004": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "5841-EC-5005": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "5845-EC-5006": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5826-EC-5007": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6230-EC-5008": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6220-EC-5009": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5895-EC-5010": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5826-EC-5011": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6605-EC-5012": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "4220-EC-6001": (6, "Chalecos SOLAS exigidos por normativa para zarpar"),
    "4220-EC-6002": (5, "Protección individual del tripulante"),
    "4220-EC-6003": (6, "Balsa salvavidas exigida por normativa para zarpar"),
    "4220-EC-6004": (5, "Libera la balsa en emergencia: seguridad del personal"),
    "1370-EC-6005": (5, "Señalización de emergencia para el personal"),
    "1370-EC-6006": (5, "Señalización de emergencia para el personal"),
    "4210-EC-6007": (5, "Lucha contra incendios a bordo"),
    "4220-EC-6008": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5820-EC-6009": (6, "Radiobaliza EPIRB exigida por normativa para zarpar"),
    "9150-EC-7001": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "9150-EC-7002": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "9150-EC-7003": (7, "Su falta degrada seriamente la efectividad, pero la unidad puede operar con limitaciones"),
    "9150-EC-7004": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "9150-EC-7005": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6850-EC-7006": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6810-EC-7007": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6850-EC-7008": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6810-EC-7009": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "4310-EC-8001": (1, "Sin aire de arranque el motor principal no parte"),
    "4310-EC-8002": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "4820-EC-8003": (5, "Protege la botella de aire de sobrepresión: seguridad del personal"),
    "4720-EC-8004": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6685-EC-8005": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6140-EC-9001": (1, "Sin batería no hay arranque ni energía de a bordo"),
    "6140-EC-9002": (1, "Sin batería de arranque el motor diésel no parte: la unidad no zarpa"),
    "6145-EC-9003": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5920-EC-9004": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5925-EC-9005": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6130-EC-9006": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6240-EC-9007": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5977-EC-9008": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5350-EC-1101": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5345-EC-1102": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "8030-EC-1103": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "8030-EC-1104": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "9505-EC-1105": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5975-EC-1106": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "7920-EC-1107": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "8040-EC-1108": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5350-EC-1109": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "6810-EC-1110": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5305-EC-1201": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5310-EC-1202": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5306-EC-1203": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "4030-EC-1204": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5340-EC-1205": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),
    "5340-EC-1206": (3, "Su falta no deja la unidad sin poder operar; se gestiona por reposición normal"),

}


def codigo_de(codigo_item):
    """Código de esencialidad de un ítem. Devuelve None si no está asignado.

    Un ítem sin código NO entra al modelo de alistamiento: no se asume
    esencial ni prescindible. El silencio no se rellena con supuestos.
    """
    par = ESENCIALIDAD.get(codigo_item)
    return par[0] if par else None


def impide_operar(codigo_item):
    """True solo si la falta del ítem deja la unidad sin poder operar."""
    return codigo_de(codigo_item) == IMPIDE_OPERAR


def explicar(codigo_item):
    """Frase en lenguaje llano del porqué del código, para la ficha."""
    par = ESENCIALIDAD.get(codigo_item)
    if not par:
        return "Sin código de esencialidad asignado: no entra al modelo de alistamiento."
    codigo, razon = par
    return f"Código {codigo} — {CODIGOS[codigo]}. {razon}."


def verificar_calibracion(codigos_items):
    """Comprueba que la proporción de ítems «impide operar» sea creíble.

    Contrasta contra la banda publicada del estudio TARSLL (16-26 %). Si
    la asignación se sale de la banda, el modelo está mal calibrado: o
    «todo es vital» otra vez, o se dejó a la unidad sin sistemas que la
    detienen. Devuelve el diagnóstico; no lanza excepción (es un aviso
    de honestidad, no un error de programa).
    """
    total = len(codigos_items)
    if total == 0:
        return {"total": 0, "impiden_operar": 0, "proporcion": 0.0,
                "en_banda": False, "banda": BANDA_CALIBRACION,
                "diagnostico": "Catálogo vacío: nada que calibrar."}
    n = sum(1 for c in codigos_items if impide_operar(c))
    p = n / total
    lo, hi = BANDA_CALIBRACION
    en_banda = lo <= p <= hi
    if en_banda:
        diag = (f"Calibración correcta: {n} de {total} ítems ({p:.1%}) "
                f"impiden operar, dentro de la banda publicada "
                f"{lo:.0%}-{hi:.0%} para catálogos navales (ADA171776).")
    elif p > hi:
        diag = (f"Sobrecalibrado: {p:.1%} de los ítems impiden operar, por "
                f"encima del {hi:.0%} publicado. Riesgo de «todo es vital»: "
                f"el modelo pierde capacidad de discriminar.")
    else:
        diag = (f"Subcalibrado: solo {p:.1%} de los ítems impiden operar, "
                f"bajo el {lo:.0%} publicado. Puede haber sistemas que "
                f"detienen la unidad sin marcar.")
    return {"total": total, "impiden_operar": n, "proporcion": round(p, 4),
            "en_banda": en_banda, "banda": BANDA_CALIBRACION,
            "diagnostico": diag}
